"""Groq 의도를 DB 메뉴 선정·식당 검색·검증된 후속 답변에 연결합니다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
import anyio
from secrets import choice

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .chat_sessions import ChatSessionState
from .schemas import Conditions, SelectedLocation
from .clients.kakao import KakaoClient
from .clients.groq import GroqClient, GroqError
from .chat_policy import load_replies
from .database import Database, MenuCatalog, Restaurant
from .detail_collection import collect_restaurant_details_batch
from .menu_catalog import MenuCandidate, menu_candidates
from .place_details import normalize_menu_name
from .recommendation_engine import (
    current_open_status,
    filter_recommendation_candidates,
)
from .repositories import save_restaurants
from .food_types import catalog_food_type

# 음식 조건에서 제거한 항목 대신 현재 확인하는 데이터와 소요시간 한계만 안내한다.
CANDIDATE_NOTICE = "메뉴·가격·현재 영업 여부를 확인한 결과입니다. 총소요시간은 아직 확인하지 않습니다."
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


def _candidate_payload(candidate: MenuCandidate) -> dict:
    """실제 가격과 카탈로그 기준가격을 섞지 않는 메뉴 응답을 만든다."""

    return {
        **candidate.to_dict(),
        "emoji": "🍽️",
        "catalog_demo": False,
        # 기존 화면과의 호환 필드이며 실제 가격이 확인됐을 때만 값을 넣는다.
        "price": candidate.verified_price if candidate.price_verified else None,
    }


def _filter_with_database(
    database: Database,
    candidates: list[dict],
    menu_name: str,
    budget: int,
    menu_aliases: list[str],
    cuisine: str,
):
    """상세 수집이 끝난 뒤 새 세션에서 최신 DB 값으로 추천을 판정한다."""

    with database.session_factory() as detail_session:
        return filter_recommendation_candidates(
            detail_session,
            candidates,
            menu_name,
            budget,
            menu_aliases=menu_aliases,
            cuisine=cuisine,
        )


async def recommend(conditions: Conditions, location: SelectedLocation, radius_m: int,
                    client: KakaoClient, menu_id: str | None = None,
                    session: Session | None = None,
                    database: Database | None = None,
                    excluded_menu_ids: set[str] | None = None,
                    search_restaurants: bool = True,
                    detail_success_ttl_hours: int = 168,
                    detail_failure_retry_minutes: int = 60,
                    progress: ProgressCallback | None = None) -> dict:
    """DB에서 메뉴를 고르고, 요청된 경우에만 카카오 식당 검색까지 수행한다."""

    if session is None:
        return {
            "demo": False,
            "menu_catalog_demo": False,
            "constraints_verified": False,
            "menus": [],
            "menu": None,
            "restaurants": [],
            "candidate_restaurants": [],
            "message": "메뉴 DB에 연결할 수 없습니다.",
            "has_more": False,
        }

    await _emit(
        progress,
        "checking_database",
        "저장된 메뉴와 식당 정보를 확인하고 있어요.",
    )
    # 2단계 메뉴 서비스가 주변의 확인 가격을 우선하고 부족할 때만 카탈로그로 보완한다.
    candidate_models = menu_candidates(
        session,
        latitude=location.lat,
        longitude=location.lng,
        radius_m=radius_m,
        budget=conditions.budget,
        cuisine=conditions.cuisine,
        excluded_menu_ids=excluded_menu_ids,
    )
    candidates = [_candidate_payload(item) for item in candidate_models]
    if menu_id:
        selected_model = next(
            (item for item in candidate_models if item.id == menu_id), None
        )
    else:
        # SystemRandom은 프로세스 전역 난수 상태에 영향을 주지 않는 단순 무작위 추첨이다.
        selected_model = choice(candidate_models) if candidate_models else None
    selected = _candidate_payload(selected_model) if selected_model else None
    result = dict(
        demo=False,
        menu_catalog_demo=False,
        constraints_verified=False,
        menus=candidates,
        menu=selected,
        restaurants=[],
        candidate_restaurants=[],
        message=CANDIDATE_NOTICE,
        has_more=False,
    )
    if selected_model is None:
        result["message"] = (
            "현재 위치와 조건에 맞는 메뉴 후보가 없습니다. "
            "예산·음식 종류·반경을 조정해 주세요."
        )
        return result
    if not search_restaurants:
        source_text = (
            "주변 식당의 확인된 메뉴·가격을 기준으로 골랐어요."
            if selected_model.source == "database"
            else "메뉴 카탈로그 기준으로 골랐으며 실제 식당 가격은 아직 확인 전이에요."
        )
        result["message"] = f"추천 메뉴: {selected_model.name}\n{source_text}"
        return result

    catalog = session.scalar(
        select(MenuCatalog)
        .where(MenuCatalog.id == selected_model.id)
        .options(selectinload(MenuCatalog.aliases))
    )
    aliases = [alias.name for alias in catalog.aliases] if catalog else []
    # 표시명과 검색어를 분리해 카카오에는 DB에 관리하는 search_keyword만 보낸다.
    await _emit(progress, "searching", "주변 식당을 검색하고 있어요.")
    search_options = {}
    if conditions.cuisine == "카페/빵" or selected_model.cuisine == "카페/빵":
        search_options["category_group_code"] = "CE7"
    found = await client.search_restaurants(
        selected_model.search_keyword,
        location.lat,
        location.lng,
        radius_m=radius_m,
        **search_options,
    )
    logger.info(
        "restaurant_search_completed",
        extra={"event": "restaurant_search_completed", "searched_count": len(found["items"])},
    )
    if session is not None:
        # 동기 SQLAlchemy 작업은 스레드에서 실행해 비동기 API 이벤트 루프를 막지 않는다.
        saved = await anyio.to_thread.run_sync(save_restaurants, session, found["items"])
        # 저장 결과를 응답에 넣어 신규·갱신·제외·실패 건수를 검증할 수 있게 한다.
        result["storage"] = saved.model_dump()
    if database is not None:
        # 새 식당 중 최대 3곳만 상세 수집하여 요청 지연과 페이지 접근량을 제한한다.
        collection = await collect_restaurant_details_batch(
            database,
            [str(item["id"]) for item in found["items"]],
            limit=3,
            success_ttl=timedelta(hours=detail_success_ttl_hours),
            failure_retry=timedelta(minutes=detail_failure_retry_minutes),
            progress=progress,
        )
        result["collection"] = {
            "attempted": len(collection),
            "success": sum(
                item["menu_status"] in {"success", "missing"}
                and item["hours_status"] in {"success", "missing"}
                for item in collection
            ),
        }
        logger.info(
            "detail_collection_completed",
            extra={
                "event": "detail_collection_completed",
                "collected_count": len(collection),
            },
        )
        await _emit(progress, "filtering", "추천 조건을 확인하고 있어요.")
        filtered = await anyio.to_thread.run_sync(
            _filter_with_database,
            database,
            found["items"],
            selected_model.name,
            conditions.budget,
            aliases,
            conditions.cuisine,
        )
        result["restaurants"] = filtered.restaurants
        result["candidate_restaurants"] = filtered.candidate_restaurants
        result["excluded"] = filtered.excluded
        result["verified_fields"] = ["menu", "price", "business_hours"]
        logger.info(
            "recommendation_filter_completed",
            extra={
                "event": "recommendation_filter_completed",
                "recommended_count": len(filtered.restaurants),
                "candidate_count": len(filtered.candidate_restaurants),
            },
        )
    else:
        # DB가 주입되지 않는 독립 단위 테스트에서는 기존 검색 응답 형식을 유지한다.
        result["restaurants"] = found["items"]
    result["has_more"] = found["has_more"]
    # 이동시간은 거리로 추측하지 않으며, 현재는 첫 검색 페이지의 후보만 표시합니다.
    if not found["items"]:
        result["message"] = "선택 반경 안에 해당 메뉴의 식당 검색 결과가 없습니다. 다른 메뉴를 고르거나 위치·반경을 변경해 주세요."
    elif result["restaurants"]:
        result["message"] = (
            f"현재 영업 중이며 메뉴와 예산이 확인된 식당 {len(result['restaurants'])}곳입니다."
        )
        if result["candidate_restaurants"]:
            result["message"] += (
                f" 추가로 확인이 필요한 후보 {len(result['candidate_restaurants'])}곳이 있습니다."
            )
    elif result["candidate_restaurants"]:
        result["message"] = (
            f"조건이 모두 확인된 식당은 없고, 확인이 필요한 후보 "
            f"{len(result['candidate_restaurants'])}곳이 있습니다."
        )
    else:
        result["message"] = "현재 영업 중이면서 메뉴와 예산 조건이 확인된 식당이 없습니다."
    return result


def _menu_matches(restaurant: Restaurant, catalog: MenuCatalog | None):
    """후속 가격 질문에서도 추천 필터와 같은 대표명·별칭 기준을 사용한다."""

    if catalog is None:
        return []
    targets = {
        normalize_menu_name(value).replace(" ", "")
        for value in [catalog.name, *(alias.name for alias in catalog.aliases)]
    }
    return [
        menu
        for menu in restaurant.menus
        if any(target in menu.normalized_name.replace(" ", "") for target in targets)
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
                f"{selected.price:,}원이며 현재 예산 기준 {budget_text}입니다."
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
        response["text"] = (
            menu["description"]
            + " 실제 매장의 재료·가격 정보는 식당별 수집 결과로 별도 확인합니다."
        )
    elif parsed.intent == "ask_restaurant_detail":
        # Groq가 최근 추천 목록에서 식별한 대상만 실제 DB 사실 조회에 사용한다.
        await _emit(progress, "checking_database", "저장된 식당 정보를 확인하고 있어요.")
        text, detail = _restaurant_detail_answer(
            session,
            parsed.restaurant_id,
            parsed.requested_detail,
            selected_menu_id,
            conditions.budget,
        )
        response.update(text=text, restaurant_detail=detail)
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
        response.update(result=result, text=text)
    response["_session"] = session_meta
    return response
