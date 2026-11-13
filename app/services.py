"""Groq 의도를 DB 메뉴 선정·식당 검색·검증된 후속 답변에 연결합니다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import re
from secrets import choice

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .chat_sessions import ChatSessionState, DisplayedRestaurant
from .schemas import Conditions, SelectedLocation
from .clients.kakao import KakaoClient
from .clients.groq import GroqClient, GroqError
from .chat_policy import load_replies
from .database import Database, MenuCatalog, Restaurant
from .food_types import catalog_food_type

ProgressCallback = Callable[[dict], Awaitable[None]]
logger = logging.getLogger("lunchrun.services")


async def _emit(
    progress: ProgressCallback | None, event: str, message: str, **data
) -> None:
    """일반 API에서는 아무 일도 하지 않고 스트림 요청에서만 진행 이벤트를 보낸다."""

    if progress is not None:
        await progress({"event": event, "message": message, **data})


def _active_catalogs(session: Session) -> list[MenuCatalog]:
    """Groq와 서버가 같은 활성 메뉴 목록을 사용하도록 DB에서 한 번에 읽는다."""

    return list(
        session.scalars(
            select(MenuCatalog)
            .where(MenuCatalog.active.is_(True))
            .options(selectinload(MenuCatalog.aliases))
            .order_by(MenuCatalog.name)
        ).all()
    )


def _catalog_payload(catalog: MenuCatalog) -> dict:
    """Groq에는 식별 정보만, 서버 응답에는 검증 가능한 카탈로그 설명을 사용한다."""

    return {
        "id": catalog.id,
        "name": catalog.name,
        "cuisine": catalog_food_type(catalog.cuisine),
        "description": catalog.description,
        "search_keyword": catalog.search_keyword,
    }


async def recommend(conditions: Conditions, location: SelectedLocation, radius_m: int,
                    client: KakaoClient, menu_id: str | None = None,
                    session: Session | None = None,
                    database: Database | None = None,
                    excluded_menu_ids: set[str] | None = None,
                    search_restaurants: bool = True,
                    detail_success_ttl_hours: int = 168,
                    detail_failure_retry_minutes: int = 60,
                    progress: ProgressCallback | None = None) -> dict:
    """추천 데이터는 DB에서만 조회한다. 외부 검색·수집·저장은 실행하지 않는다."""
    from .db_recommendations import qualifying_products, candidate_payloads, restaurant_payloads
    result = dict(demo=False, menu_catalog_demo=False, constraints_verified=False,
        source="database", menus=[], menu=None, restaurants=[], candidate_restaurants=[], has_more=False,
        verified_fields=["menu", "radius"],
        unverified_fields=["price", "business_hours", "travel_time"])
    if session is None:
        result["message"] = "메뉴 DB에 연결할 수 없습니다."
        return result
    await _emit(progress, "checking_database", "DB에서 메뉴·표시 가격·현재 영업시간을 확인하고 있어요.")
    products = qualifying_products(session, latitude=location.lat, longitude=location.lng,
        radius_m=radius_m, budget=conditions.budget, cuisine=conditions.cuisine,
        excluded_menu_ids=excluded_menu_ids)
    candidates = candidate_payloads(products)
    result["menus"] = [{**item, "emoji": "🍽️", "catalog_demo": False, "price": item["verified_price"]} for item in candidates]
    selected = next((m for m in result["menus"] if m["id"] == menu_id), None) if menu_id else (
        choice(result["menus"]) if result["menus"] else None)
    result["menu"] = selected
    if selected is None:
        result["message"] = "현재 위치·반경·예산·영업 조건에 맞는 DB 메뉴가 없습니다. 조건을 변경해주세요."
        return result
    result["message"] = f"추천 메뉴: {selected['name']} · 저장된 식당 정보를 기준으로 선정했습니다."
    if not search_restaurants:
        return result
    await _emit(progress, "searching", "DB에서 선택 메뉴를 판매하는 식당을 조회하고 있어요.")
    result["restaurants"] = restaurant_payloads([p for p in products if p["catalog"].id == selected["id"]])
    await _emit(progress, "filtering", "DB 식당의 위치·예산·영업 조건 확인을 완료했어요.")
    result["message"] += f" 조건에 맞는 식당 {len(result['restaurants'])}곳입니다."
    return result


def _restaurant_lines(restaurants):
    """확정된 최대 3곳의 표시 상품과 누락 안내를 같은 형식으로 만든다."""
    lines = []
    for index,place in enumerate(restaurants,1):
        price = f"{place['price']:,}원" if place['price'] is not None else '해당 식당의 메뉴 가격 확인 불가'
        lines.append(f"{index}. {place['name']} · {place['menu_name']} · {price}")
        lines.extend(w for w in place['warnings'] if w != '해당 식당의 메뉴 가격 확인 불가')
    return lines


def _restaurant_detail_answer(
    session: Session,
    restaurant_id: str,
    requested_detail: str,
    selected_menu_id: str | None,
    budget: int,
    displayed: DisplayedRestaurant | None = None,
) -> tuple[str, dict]:
    """DB에서 확인한 값만으로 식당 후속 질문의 문장과 구조화 결과를 만든다."""

    # 3단계: 가격 질문은 당시 표시한 상품으로 답한다. 다른 메뉴의 최저가로 바꾸지 않는다.
    if requested_detail == 'price':
        if displayed is None:
            return '식당 목록을 다시 조회한 뒤 가격을 질문해주세요.', {'restaurant_id': restaurant_id}
        detail = dict(restaurant_id=restaurant_id, restaurant_name=displayed.name,
                      requested_detail='price', product_id=displayed.product_id,
                      menu_name=displayed.menu_name, price=displayed.price)
        if displayed.price is None:
            return '해당 식당의 메뉴 가격 확인 불가', detail
        budget_text = '예산 이내' if displayed.price <= budget else '예산에 적합하지 않음'
        return (f"{displayed.name}의 {displayed.menu_name} 가격은 {displayed.price:,}원입니다. "
                f"{budget_text} (앞서 표시한 가격 기준)", detail)

    restaurant = session.scalar(
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(
            selectinload(Restaurant.detail_status),
            selectinload(Restaurant.menus),
            selectinload(Restaurant.business_hours),
        )
    )
    if restaurant is None:
        return "식당 정보를 DB에서 찾을 수 없습니다.", {"restaurant_id": restaurant_id}

    detail = {
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "requested_detail": requested_detail,
        "place_url": restaurant.place_url,
    }

    if requested_detail == "address":
        if restaurant.address and restaurant.address.strip():
            detail["address"] = restaurant.address
            return f"{restaurant.name}의 주소는 {restaurant.address}입니다.", detail
        return "주소가 명시되어 있지 않습니다", detail

    if requested_detail == "menu":
        if (
            restaurant.detail_status is None
            or restaurant.detail_status.menu_status != "success"
            or not restaurant.menus
        ):
            return f"{restaurant.name}의 메뉴 확인 불가 상태입니다.", detail
        names = [menu.name for menu in restaurant.menus[:10]]
        detail["menus"] = names
        suffix = " 외" if len(restaurant.menus) > 10 else ""
        return f"{restaurant.name}에서 확인된 메뉴는 {', '.join(names)}{suffix}입니다.", detail

    if requested_detail == "hours":
        # 추천과 같은 시간 판정을 사용하되 매 질문 시 한국 시간을 다시 읽는다.
        from .db_recommendations import recommendation_hours
        status, holiday_unknown = recommendation_hours(restaurant)
        detail.update(open_status=status, holiday_unknown=holiday_unknown)
        if status == 'unknown':
            return '영업시간 미기재로 인해 알 수 없습니다', detail
        state_text = '영업 중' if status == 'open' else '영업 종료'
        text = f"수집된 영업시간과 현재 한국 시간을 비교하면 {restaurant.name}은 지금 {state_text}입니다."
        if holiday_unknown:
            text += ' 휴무일 확인 필요'
        return text, detail

    return '현재 위치를 기반으로 추천한 메뉴를 판매하는 식당을 추천드렸습니다.', detail


def _recommendation_reason(state: ChatSessionState | None) -> str:
    """3단계: 후속 질문을 여러 번 해도 마지막 추천 종류와 당시 조건을 사용한다."""
    if state is None or state.last_recommendation_kind is None:
        return '먼저 메뉴 또는 식당을 추천받아 주세요.'
    if state.last_recommendation_kind == 'restaurant':
        return '현재 위치를 기반으로 추천한 메뉴를 판매하는 식당을 추천드렸습니다.'
    conditions = state.recommendation_conditions
    if conditions is None:
        return '메뉴를 다시 추천받은 뒤 질문해주세요.'
    location = state.recommendation_location
    return (
        f"추천 당시 조건\n위치: {location.name if location else '미설정'}\n"
        f"반경: {state.recommendation_radius_m}m\n음식 종류: {conditions.cuisine}\n"
        f"예산: {conditions.budget:,}원 이하\n점심시간: {conditions.minutes}분\n"
        '앞서 입력해주신 조건에 부합하는 메뉴를 추천드렸습니다.'
    )


def _displayed_target(message, state, model_id):
    """순서 표현은 서버 목록으로 확정하고, 모호한 지칭은 임의 매칭하지 않는다."""
    items = state.displayed_restaurants if state else []
    match = re.search(r'첫\s*번째|첫째|두\s*번째|둘째|세\s*번째|셋째|(\d+)\s*번(?:째)?', message)
    if match:
        word = match.group().replace(' ', '')
        index = int(match.group(1)) - 1 if match.group(1) else (
            0 if word in {'첫번째', '첫째'} else 1 if word in {'두번째', '둘째'} else 2)
        return items[index] if 0 <= index < len(items) else None
    named = [item for item in items if item.name and item.name in message]
    if len(named) == 1:
        return named[0]
    if re.search(r'그\s*식당|이\s*식당|거기', message):
        focused = next((item for item in items if item.restaurant_id == state.focused_restaurant_id), None) if state else None
        return focused or (items[0] if len(items) == 1 else None)
    return next((item for item in items if item.restaurant_id == model_id), None)


async def chat(message: str, conditions: Conditions, menu_id: str | None, location: SelectedLocation,
               radius_m: int, client: KakaoClient, groq: GroqClient,
               session: Session | None = None,
               database: Database | None = None,
               conversation_state: ChatSessionState | None = None,
               *,
               detail_success_ttl_hours: int = 168,
               detail_failure_retry_minutes: int = 60,
               progress: ProgressCallback | None = None) -> dict:
    # 조건을 바꾼 뒤 과거 식당이나 선택 메뉴를 새 요청에 재사용하지 않는다.
    if conversation_state is not None:
        old = conversation_state
        changed = (old.conditions is not None and
            (old.conditions.budget != conditions.budget or old.conditions.cuisine != conditions.cuisine))
        changed = changed or (old.location is not None and
            (old.location.lat != location.lat or old.location.lng != location.lng))
        changed = changed or (old.radius_m is not None and old.radius_m != radius_m)
        changed = changed or (menu_id is not None and menu_id != old.selected_menu_id)
        if changed:
            conversation_state = old.model_copy(deep=True)
            conversation_state.selected_menu_id = menu_id
            conversation_state.clear_recommendation_context()
            conversation_state.pending_action = None
    # AI는 의도만 해석하고 실제 메뉴 선정·조건 검증·식당 조회는 서버가 실행합니다.
    catalogs = _active_catalogs(session) if session is not None else []
    catalog_payloads = [_catalog_payload(item) for item in catalogs]
    selected_menu_id = menu_id or (
        conversation_state.selected_menu_id if conversation_state else None
    )
    if selected_menu_id and not any(
        item["id"] == selected_menu_id for item in catalog_payloads
    ):
        return dict(text="선택 메뉴가 유효하지 않습니다. 메뉴를 다시 골라주세요.", suggested_patch=None, result=None)

    # 3단계: 당시 표시한 이름과 순서를 유지한다. 삭제된 DB 행 때문에 순서를 당기지 않는다.
    recent_places, candidate_places = [], []
    if conversation_state is not None:
        recent_places = [{'id':item.restaurant_id, 'name':item.name}
                         for item in conversation_state.displayed_restaurants]
    await _emit(progress, "interpreting", "질문을 이해하고 있어요.")
    parsed = await groq.interpret(
        message,
        conditions,
        radius_m,
        catalog_payloads,
        selected_menu_id,
        conversation_history=(
            [turn.model_dump() for turn in conversation_state.turns]
            if conversation_state else None
        ),
        restaurants=recent_places,
        candidate_restaurants=candidate_places,
        pending_action=(
            conversation_state.pending_action.model_dump()
            if conversation_state and conversation_state.pending_action else None
        ),
    )
    try:
        replies = load_replies()
    except (OSError, ValueError, TypeError):
        raise GroqError("groq_policy", "답변 안내문 설정을 확인해 주세요.", 503) from None
    response = dict(text="", suggested_patch=None, result=None)
    session_meta = {"intent": parsed.intent, "clear_pending": True}
    if parsed.intent == "explain_recommendation":
        response['text'] = _recommendation_reason(conversation_state)
    elif parsed.intent == "change_conditions":
        # 4단계: 모델은 값/방향만 제안한다. 적용값과 전후 비교는 서버가 확정한다.
        current = {**conditions.model_dump(), 'radius_m':radius_m}
        proposed = parsed.condition_patch.model_dump(exclude_none=True)
        radius_notice = ''
        if parsed.radius_adjustment:
            delta = 50 if parsed.radius_adjustment == 'increase' else -50
            adjusted = min(500, max(50, radius_m + delta))
            proposed['radius_m'] = adjusted
            if adjusted == radius_m:
                radius_notice = '최대 반경입니다.' if delta > 0 else '최소 반경입니다.'
            else:
                direction = '확대' if delta > 0 else '축소'
                radius_notice = f"{abs(adjusted-radius_m)} m {direction} 하였습니다."
        patch = {key:value for key,value in proposed.items() if current[key] != value}
        response.update(applied_patch=patch, search_performed=False)
        if not patch and not parsed.search_after_change:
            response['text'] = radius_notice or '이미 해당 조건이 적용되어 있습니다.'
        else:
            updated = conditions.model_copy(update={key:value for key,value in patch.items() if key!='radius_m'})
            updated_radius = patch.get('radius_m',radius_m)
            # 세션도 새 조건으로 기록해야 다음 질문에서 과거 식당을 재사용하지 않는다.
            session_meta.update(effective_conditions=updated.model_dump(),
                                effective_radius_m=updated_radius, conditions_changed=bool(patch))
            result = await recommend(updated,location,updated_radius,client,session=session,
                database=database,search_restaurants=parsed.search_after_change,progress=progress)
            labels = {'budget':'예산','cuisine':'음식 종류','radius_m':'반경','minutes':'점심시간'}
            def display(key,value):
                return f"{value:,}원" if key=='budget' else f"{value}m" if key=='radius_m' else f"{value}분" if key=='minutes' else str(value)
            lines = [f"{labels[key]} 변경 전: {display(key,current[key])} → 변경 후: {display(key,value)}"
                     for key,value in patch.items()]
            if not patch: lines.append('이미 해당 조건이 적용되어 있습니다.')
            if radius_notice: lines.append(radius_notice)
            if result['menu']:
                lines.append(f"바뀐 조건에 의한 메뉴는 {result['menu']['name']}입니다.")
                lines.append(f"적용 조건: 반경 {updated_radius}m · 예산 {updated.budget:,}원 이하 · {updated.cuisine} · 점심시간 {updated.minutes}분")
                if parsed.search_after_change:
                    lines.extend(_restaurant_lines(result['restaurants']))
                else:
                    lines.append('식당까지 추천해드릴까요?')
            else:
                lines.append('변경된 조건에 맞는 메뉴가 없습니다. 조건을 조정해주세요.')
            text = '\n'.join(lines)
            result['message'] = text
            response.update(text=text,result=result,search_performed=parsed.search_after_change)
    elif parsed.intent == "clarify":
        # 모델이 만든 확인 문장에 매장 사실이나 지시가 섞여도 사용자에게 그대로 전달하지 않습니다.
        response["text"] = replies[parsed.clarification_kind or "ambiguous"]
        pending_by_kind = {
            "radius": {"kind": "change_radius", "original_message": message, "current_value": radius_m},
            "budget": {"kind": "change_budget", "original_message": message, "current_value": conditions.budget},
            "restaurant": {
                "kind": "select_restaurant",
                "original_message": message,
                "restaurant_ids": [item["id"] for item in [*recent_places, *candidate_places]],
            },
        }
        pending = pending_by_kind.get(parsed.clarification_kind)
        session_meta.update(clear_pending=pending is None, pending_action=pending)
    elif parsed.intent == "out_of_scope":
        response["text"] = replies["out_of_scope"]
        session_meta.update(
            clear_pending=False,
            pending_action={"kind": "unsupported_input", "original_message": message},
        )
    elif parsed.intent == 'list_menus':
        # 6단계: 후보만 최대 세 개 안내하며 현재 선택 메뉴나 식당 목록을 덮어쓰지 않는다.
        from .db_recommendations import qualifying_products, candidate_payloads
        options = candidate_payloads(qualifying_products(session,latitude=location.lat,longitude=location.lng,
            radius_m=radius_m,budget=conditions.budget,cuisine=conditions.cuisine))[:3]
        response['menu_options'] = [{'id':item['id'],'name':item['name']} for item in options]
        response['text'] = ('현재 조건에 맞는 메뉴 후보입니다.\n' + '\n'.join(
            f"{i}. {item['name']}" for i,item in enumerate(options,1))) if options else '현재 조건에 맞는 메뉴 후보가 없습니다.'
    elif parsed.intent in {"ask_menu_detail", "explain_menu"}:
        # 예전 클라이언트의 의도는 받되 삭제한 음식 설명을 DB/모델에서 생성하지 않는다.
        response['text'] = '음식 설명은 제공하지 않습니다. 메뉴 추천이나 식당 조회를 요청해주세요.'
    elif parsed.intent == "ask_restaurant_detail":
        displayed = _displayed_target(message, conversation_state, parsed.restaurant_id)
        if displayed is None:
            # 후보가 여러 개이거나 순서가 범위를 벗어나면 대상을 먼저 확인한다.
            if recent_places:
                choices = '\n'.join(f"{i}. {item['name']}" for i,item in enumerate(recent_places,1))
                response['text'] = f"어느 식당인지 번호나 이름을 알려주세요.\n{choices}"
                session_meta.update(clear_pending=False, pending_action={
                    'kind':'select_restaurant','original_message':message,
                    'restaurant_ids':[item['id'] for item in recent_places]})
            else:
                response['text'] = '현재 조건으로 식당을 다시 조회한 뒤 질문해주세요.'
        else:
            await _emit(progress, "checking_database", "저장된 식당 정보를 확인하고 있어요.")
            text, detail = _restaurant_detail_answer(
                session, displayed.restaurant_id, parsed.requested_detail,
                selected_menu_id, conditions.budget, displayed,
            )
            response.update(text=text, restaurant_detail=detail, restaurant_guidance=bool(selected_menu_id))
    else:
        target = parsed.menu_id
        if parsed.intent == "search_restaurants":
            target = target or selected_menu_id
        # 2단계: 메뉴가 없는 식당 요청에 무작위 메뉴를 끼워 넣지 않는다.
        # 명시한 메뉴가 있으면 그 메뉴, 없으면 화면/세션의 현재 메뉴만 사용한다.
        if parsed.intent == "search_restaurants" and target is None:
            response.update(
                text="먼저 메뉴를 정해주세요. '메뉴 추천해줘' 또는 '짜장면 식당 알려줘'처럼 말씀해주세요.",
                _session=session_meta,
            )
            return response
        # 2단계: 재추천에서는 현재 메뉴 한 개만 제외한다.
        # recent_menu_ids는 대화 기록으로 보관하되 후보 제외에는 사용하지 않는다.
        excluded = {selected_menu_id} if parsed.intent == "reroll_menu" and selected_menu_id else set()
        # 지정 메뉴도 현재 예산·음식 분류 후보에 포함될 때만 검색할 수 있다.
        result = await recommend(
            conditions,
            location,
            radius_m,
            client,
            target,
            session,
            database,
            excluded,
            search_restaurants=parsed.intent == "search_restaurants",
            detail_success_ttl_hours=detail_success_ttl_hours,
            detail_failure_retry_minutes=detail_failure_retry_minutes,
            progress=progress,
        )
        # 추천 답변은 서버 카탈로그와 확정 조건만 사용해 중복 경고를 줄입니다.
        summary = (f"적용 조건: 반경 {radius_m}m · 예산 {conditions.budget:,}원 이하 · {conditions.cuisine} · "
                   f"점심시간 {conditions.minutes}분")
        has_places = result["restaurants"] or result.get("candidate_restaurants")
        text = result["message"]
        if parsed.intent != "search_restaurants":
            # 2단계: 메뉴 선정은 목록 표시와 분리한다. 조건을 확인한 뒤 조회를 제안한다.
            # 후보를 만들기 위한 DB 조회는 하지만 식당 목록 생성·외부 검색은 실행하지 않는다.
            if result["menu"] is not None:
                text = f"추천 메뉴: {result['menu']['name']}\n{summary}\n식당까지 추천해드릴까요?"
            elif parsed.intent == "reroll_menu":
                text = f"현재 메뉴를 제외하면 조건에 맞는 다른 메뉴가 없습니다. 조건을 변경해주세요.\n{summary}"
            else:
                text = f"{result['message']}\n{summary}"
        elif not has_places:
            # 2단계: 특정 메뉴 조회 실패를 다른 메뉴 무작위 선정으로 대체하지 않는다.
            menu_name = next(item['name'] for item in catalog_payloads if item['id'] == target)
            text = (f"선택 메뉴: {menu_name}\n{summary}\n"
                    "현재 이 메뉴에 맞는 영업 중인 식당이 없어요. 다른 메뉴를 추천해드릴까요?")
        # 1단계: 채팅에서도 실제 표시 상품의 가격과 누락 경고를 함께 보여준다.
        if has_places:
            lines = _restaurant_lines(result['restaurants'])
            text = f"추천 메뉴: {result['menu']['name']}\n{summary}\n" + '\n'.join(lines)
        # 응답의 최상위 문장과 구조화 결과의 안내문이 서로 다르지 않게 맞춘다.
        result["message"] = text
        response.update(result=result, text=text, restaurant_guidance=bool(result.get("menu")))
    response["_session"] = session_meta
    return response
