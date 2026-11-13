"""Groq 의도를 DB 메뉴 선정·식당 검색·검증된 후속 답변에 연결합니다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from secrets import choice

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .chat_sessions import ChatSessionState
from .schemas import Conditions, SelectedLocation
from .clients.kakao import KakaoClient
from .clients.groq import GroqClient, GroqError
from .chat_policy import load_replies
from .database import Database, MenuCatalog, Restaurant
from .recommendation_engine import current_open_status
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
        verified_fields=["menu", "price", "business_hours", "radius"],
        unverified_fields=["serving_size", "live_availability", "travel_time"])
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
    result["message"] = f"추천 메뉴: {selected['name']} · DB의 현재 영업시간·표시 가격 기준입니다."
    if selected["serving_unverified"]:
        result["message"] += " 인분 미확인 상품이 포함되어 있습니다."
    if not search_restaurants:
        return result
    await _emit(progress, "searching", "DB에서 선택 메뉴를 판매하는 식당을 조회하고 있어요.")
    result["restaurants"] = restaurant_payloads([p for p in products if p["catalog"].id == selected["id"]])
    await _emit(progress, "filtering", "DB 식당의 위치·예산·영업 조건 확인을 완료했어요.")
    result["message"] += f" 조건에 맞는 식당 {len(result['restaurants'])}곳입니다."
    return result


def _menu_matches(restaurant: Restaurant, catalog: MenuCatalog | None):
    """후속 가격 질문에서도 추천 필터와 같은 대표명·별칭 기준을 사용한다."""

    if catalog is None:
        return []
    return [
        menu
        for menu in restaurant.menus
        if menu.menu_catalog_id == catalog.id and menu.availability_status != "sold_out"
    ]


def _restaurant_detail_answer(
    session: Session,
    restaurant_id: str,
    requested_detail: str,
    selected_menu_id: str | None,
    budget: int,
) -> tuple[str, dict]:
    """DB에서 확인한 값만으로 식당 후속 질문의 문장과 구조화 결과를 만든다."""

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

    catalog = None
    if selected_menu_id:
        catalog = session.scalar(
            select(MenuCatalog)
            .where(MenuCatalog.id == selected_menu_id)
            .options(selectinload(MenuCatalog.aliases))
        )
    detail = {
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "requested_detail": requested_detail,
        "place_url": restaurant.place_url,
    }

    if requested_detail == "address":
        if restaurant.address:
            detail["address"] = restaurant.address
            return f"{restaurant.name}의 주소는 {restaurant.address}입니다.", detail
        return f"{restaurant.name}의 주소는 확인할 수 없습니다.", detail

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

    if requested_detail == "price":
        matches = _menu_matches(restaurant, catalog)
        known = [
            menu
            for menu in matches
            if menu.price_status == "known" and menu.price is not None
        ]
        if known:
            selected = min(known, key=lambda item: item.price or 0)
            detail.update(menu_name=selected.name, price=selected.price)
            budget_text = "예산 이내" if selected.price <= budget else "예산 초과"
            return (
                f"{restaurant.name}의 {selected.name} 가격은 "
                f"{selected.price:,}원이며 현재 예산 기준 {budget_text}입니다. 인분 미확인 상품은 표시 가격 기준입니다."
            ), detail
        menu_name = catalog.name if catalog else "선정 메뉴"
        return f"{restaurant.name}의 {menu_name} 가격 확인 불가 상태입니다.", detail

    if requested_detail == "hours":
        if (
            restaurant.detail_status is None
            or restaurant.detail_status.hours_status != "success"
        ):
            return f"{restaurant.name}의 현재 영업 상태를 알 수 없습니다.", detail
        status, holiday_unknown = current_open_status(restaurant.business_hours)
        if status == "unknown":
            return f"{restaurant.name}의 현재 영업 상태를 알 수 없습니다.", detail
        detail.update(open_status=status, holiday_unknown=holiday_unknown)
        state_text = "영업 중" if status == "open" else "영업 종료"
        text = (
            f"수집된 영업시간과 현재 한국 시간을 비교하면 "
            f"{restaurant.name}은 지금 {state_text}입니다."
        )
        if holiday_unknown:
            text += " 다만 휴무일 확인이 필요합니다."
        return text, detail

    # 추천 이유는 저장된 메뉴·가격·영업정보를 각각 확인해 근거가 있는 부분만 설명한다.
    matches = _menu_matches(restaurant, catalog)
    known = [
        menu
        for menu in matches
        if menu.price_status == "known" and menu.price is not None
    ]
    status = "unknown"
    if restaurant.detail_status and restaurant.detail_status.hours_status == "success":
        status, _ = current_open_status(restaurant.business_hours)
    reasons = []
    if matches:
        reasons.append(f"{catalog.name if catalog else '선정 메뉴'} 판매가 확인됨")
    if known and min(menu.price for menu in known if menu.price is not None) <= budget:
        reasons.append("가격이 예산 이내임")
    if status == "open":
        reasons.append("수집된 영업시간 기준 현재 영업 중임")
    detail["reasons"] = reasons
    if reasons:
        return f"{restaurant.name}은 " + ", ".join(reasons) + " 때문에 추천됐습니다.", detail
    return f"{restaurant.name}의 추천 근거를 현재 DB에서 확인할 수 없습니다.", detail


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
            conversation_state.restaurant_ids = []
            conversation_state.candidate_restaurant_ids = []
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

    # Groq에는 최근 식당의 ID·이름만 전달하고 가격·주소·영업정보는 보내지 않는다.
    recent_places, candidate_places = [], []
    if session is not None and conversation_state is not None:
        for target, ids in (
            (recent_places, conversation_state.restaurant_ids),
            (candidate_places, conversation_state.candidate_restaurant_ids),
        ):
            for restaurant_id in ids:
                restaurant = session.get(Restaurant, restaurant_id)
                if restaurant is not None:
                    target.append({"id": restaurant.id, "name": restaurant.name})
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
    if parsed.intent == "change_conditions":
        # 현재와 같은 값은 제외하고 변경안만 반환합니다. 이 단계에서는 검색하지 않습니다.
        current = {**conditions.model_dump(), "radius_m": radius_m}
        patch = {k:v for k,v in parsed.condition_patch.model_dump(exclude_none=True).items() if current[k] != v}
        response.update(
            text="변경할 조건을 확인하고 적용해 주세요." if patch else "이미 해당 조건이 적용되어 있습니다.",
            suggested_patch=patch or None,
            search_after_change=parsed.search_after_change,
        )
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
    elif parsed.intent in {"ask_menu_detail", "explain_menu"}:
        menu = next(item for item in catalog_payloads if item["id"] == parsed.menu_id)
        from .db_recommendations import qualifying_products, candidate_payloads
        matches = candidate_payloads(qualifying_products(session, latitude=location.lat,
            longitude=location.lng, radius_m=radius_m, budget=conditions.budget,
            cuisine=conditions.cuisine, menu_id=parsed.menu_id))
        if matches:
            item = matches[0]
            response["text"] = (f"{menu['name']}: 현재 조건에 맞는 DB 식당 {item['nearby_restaurant_count']}곳, "
                f"표시 가격 {item['verified_price']:,}~{item['verified_price_max']:,}원입니다. "
                + ("인분 미확인 상품이 포함되어 있습니다." if item['serving_unverified'] else ""))
        else:
            response["text"] = f"{menu['name']}은 DB 대표 메뉴지만 현재 위치·예산·영업 조건에 맞는 식당이 없습니다."
    elif parsed.intent == "ask_restaurant_detail":
        if parsed.restaurant_id not in {p['id'] for p in [*recent_places, *candidate_places]}:
            response.update(text="현재 조건으로 식당을 다시 조회한 뒤 질문해주세요.", _session=session_meta)
            return response
        # Groq가 최근 추천 목록에서 식별한 대상만 실제 DB 사실 조회에 사용한다.
        await _emit(progress, "checking_database", "저장된 식당 정보를 확인하고 있어요.")
        text, detail = _restaurant_detail_answer(
            session,
            parsed.restaurant_id,
            parsed.requested_detail,
            selected_menu_id,
            conditions.budget,
        )
        response.update(text=text, restaurant_detail=detail, restaurant_guidance=bool(selected_menu_id))
    else:
        target = parsed.menu_id
        if parsed.intent == "search_restaurants":
            target = target or selected_menu_id
        # 재추천은 세션의 최근 메뉴도 제외하여 같은 메뉴 반복을 줄인다.
        excluded = set()
        if parsed.intent == "reroll_menu":
            if conversation_state:
                excluded.update(conversation_state.recent_menu_ids)
            if selected_menu_id:
                excluded.add(selected_menu_id)
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
        text = (f"추천 메뉴: {result['menu']['name']}\n{summary}\n"
                f"추천 식당: {len(result['restaurants'])}곳 · 확인 필요 후보: "
                f"{len(result.get('candidate_restaurants', []))}곳\n{replies['notice']}") if has_places else result["message"]
        if has_places and result["menu"].get("serving_unverified"):
            text += "\n인분 미확인 상품은 매장 표시 가격 기준입니다."
        if result.get("menu") and parsed.intent in {"recommend_menu", "reroll_menu"}:
            text += "\n식당을 안내해 드릴까요?"
        response.update(result=result, text=text, restaurant_guidance=bool(result.get("menu")))
    response["_session"] = session_meta
    return response
