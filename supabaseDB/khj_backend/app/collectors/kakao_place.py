"""5단계: 카카오 상세페이지를 렌더링해 공개 메뉴·영업시간 원문을 수집."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from playwright.async_api import (
    Browser,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


@dataclass(frozen=True, slots=True)
class RawMenu:
    """페이지에 표시된 가공 전 메뉴명과 가격 문자열."""

    name: str
    price_text: str


@dataclass(frozen=True, slots=True)
class RawBusinessDay:
    """요일 표시와 그 아래의 영업·브레이크·라스트오더 문자열."""

    day_text: str
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawPlacePage:
    """브라우저에서 읽었지만 아직 DB 형식으로 변환하지 않은 페이지 데이터."""

    menu_section_present: bool
    hours_section_present: bool
    menus: tuple[RawMenu, ...]
    business_days: tuple[RawBusinessDay, ...]
    hours_notes: str = ''


@dataclass(frozen=True, slots=True)
class PlaceCollectionError(Exception):
    """외부 오류 원문을 노출하지 않는 통제된 수집 오류."""

    status: str
    code: str

    def __str__(self) -> str:
        return self.code


def validate_place_url(kakao_id: str, place_url: str) -> str:
    """임의 사이트 접속을 막고 카카오 ID와 일치하는 공식 URL만 반환한다."""

    # DB의 URL을 그대로 브라우저에 넘기기 전에 호스트·경로·포트를 검사한다.
    parsed = urlsplit(place_url.strip())
    path_parts = [part for part in parsed.path.split("/") if part]
    try:
        port = parsed.port
    except ValueError:
        raise PlaceCollectionError("fetch_failed", "invalid_place_url") from None
    if (
        not kakao_id.isdigit()
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname != "place.map.kakao.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
        or path_parts != [kakao_id]
    ):
        raise PlaceCollectionError("fetch_failed", "invalid_place_url")
    # HTTP로 저장된 과거 URL도 실제 수집에서는 HTTPS 표준 주소로 통일한다.
    return f"https://place.map.kakao.com/{kakao_id}"


class KakaoPlaceCollector:
    """Playwright 브라우저로 동적 페이지를 읽는 재사용 가능한 수집기."""

    def __init__(self, *, timeout_ms: int = 15_000):
        self.timeout_ms = timeout_ms
        self._manager = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> KakaoPlaceCollector:
        # 여러 식당을 연속 수집할 때는 브라우저 하나를 재사용할 수 있다.
        try:
            self._manager = await async_playwright().start()
            self._browser = await self._manager.chromium.launch(headless=True)
            return self
        except PlaywrightError:
            # 브라우저 시작 실패 중 만들어진 Playwright 관리자도 남기지 않는다.
            if self._manager is not None:
                await self._manager.stop()
            self._manager = None
            self._browser = None
            raise PlaceCollectionError("fetch_failed", "browser_unavailable") from None

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._manager is not None:
            await self._manager.stop()
        self._browser = None
        self._manager = None

    async def collect(self, kakao_id: str, place_url: str) -> RawPlacePage:
        """식당 한 곳을 수집하고 브라우저 오류를 내부 상태 코드로 변환한다."""

        canonical_url = validate_place_url(kakao_id, place_url)
        if self._browser is not None:
            try:
                return await self._collect_with_browser(self._browser, canonical_url)
            except PlaceCollectionError:
                raise
            except PlaywrightError:
                raise PlaceCollectionError(
                    "fetch_failed", "page_browser_error"
                ) from None
        try:
            # 단건 호출에서는 브라우저를 이 함수 안에서 열고 반드시 닫는다.
            async with async_playwright() as manager:
                browser = await manager.chromium.launch(headless=True)
                try:
                    return await self._collect_with_browser(browser, canonical_url)
                finally:
                    await browser.close()
        except PlaceCollectionError:
            raise
        except PlaywrightError:
            raise PlaceCollectionError("fetch_failed", "browser_unavailable") from None

    async def _collect_with_browser(
        self, browser: Browser, canonical_url: str
    ) -> RawPlacePage:
        """열려 있는 브라우저에서 실제 페이지를 읽어 원문 자료형으로 반환한다."""

        # 한국 시간대·한국어 페이지를 사용해 요일과 시간 표시를 일관되게 만든다.
        context = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
        page = await context.new_page()
        try:
            response = await page.goto(
                canonical_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            if response is None or response.status >= 400:
                raise PlaceCollectionError("fetch_failed", "page_http_error")
            await page.wait_for_selector("#mainContent", timeout=self.timeout_ms)
            # mainContent는 스켈레톤에도 있으므로 실제 장소 정보가 나올 때까지 기다린다.
            await page.get_by_text('장소명', exact=True).wait_for(state='attached', timeout=self.timeout_ms)

            hours_unit = page.locator('.unit_default').filter(
                has=page.locator('.tit_info', has_text='영업정보')
            ).first
            hours_toggle = hours_unit.locator('button[aria-expanded]').first
            if await hours_toggle.count() and await hours_toggle.get_attribute('aria-expanded') != 'true':
                await hours_toggle.click(timeout=self.timeout_ms)
                await page.wait_for_function("""() => [...document.querySelectorAll('.unit_default')]
                  .find(el=>el.querySelector('.tit_info')?.innerText==='영업정보')
                  ?.querySelector('button[aria-expanded]')?.getAttribute('aria-expanded')==='true'""", timeout=self.timeout_ms)

            # '메뉴 더보기'가 메뉴 탭으로 이동시키므로 홈 탭의 영업시간을 먼저 읽는다.
            hours_payload = await page.evaluate(
                """() => {
                    const hoursUnit = [...document.querySelectorAll('.unit_default')]
                      .find(el => el.querySelector('.tit_info')?.textContent?.includes('영업정보'));
                    const hourRows = hoursUnit
                      ? [...hoursUnit.querySelectorAll('.line_fold')]
                      : [];
                    return {
                      hoursSectionPresent: Boolean(hoursUnit),
                      hoursNotes: hoursUnit?.innerText || '',
                      businessDays: hourRows.map(row => ({
                        dayText: row.querySelector('.tit_fold')?.textContent?.trim() || '',
                        details: (row.querySelector('.detail_fold')?.innerText || '')
                          .split('\\n').map(value=>value.trim()).filter(Boolean)
                      }))
                    };
                }"""
            )

            # 배달 탭이 기본 선택된 매장은 가격이 다를 수 있으므로 매장 메뉴를 우선한다.
            product = page.locator('.section_product')
            regular = product.get_by_role('tab', name=re.compile(r'^메뉴\s*총 목록 개수'))
            if await regular.count() and await regular.first.get_attribute('aria-selected') != 'true':
                await regular.first.click(timeout=self.timeout_ms)
                await page.wait_for_function("""() => [...document.querySelectorAll('.section_product [role=tab]')]
                    .some(el=>el.innerText.trim().startsWith('메뉴') && el.getAttribute('aria-selected')==='true')""", timeout=self.timeout_ms)

            # 홈 화면은 메뉴 일부만 보여주므로 더보기 후 전체 메뉴 DOM을 읽는다.
            for _ in range(10):
                more = page.locator(".section_product .link_more").first
                if await more.count() == 0 or not await more.is_visible():
                    break
                before = await page.locator(
                    ".section_product .list_goods > li"
                ).count()
                await more.click(timeout=self.timeout_ms)
                try:
                    await page.wait_for_function("""before => document.querySelectorAll(
                        '.section_product .list_goods > li').length > before""", arg=before, timeout=4000)
                except PlaywrightTimeoutError:
                    break
                after = await page.locator(
                    ".section_product .list_goods > li"
                ).count()
                if after <= before:
                    break

            payload = await page.evaluate(
                """() => {
                    const menuSection = document.querySelector('.section_product');
                    const menuRows = menuSection
                      ? [...menuSection.querySelectorAll('.list_goods > li')]
                      : [];
                    return {
                      menuSectionPresent: Boolean(menuSection),
                      menus: menuRows.map(row => ({
                        name: row.querySelector('.tit_item')?.textContent?.trim() || '',
                        priceText: row.querySelector('.desc_item')?.textContent?.trim() || ''
                      }))
                    };
                }"""
            )
            # JavaScript 반환 구조가 예상과 다르면 정보 없음이 아니라 분석 실패로 처리한다.
            if not isinstance(payload, dict) or not isinstance(hours_payload, dict):
                raise PlaceCollectionError("parse_failed", "page_structure")
            return RawPlacePage(
                menu_section_present=bool(payload.get("menuSectionPresent")),
                hours_section_present=bool(hours_payload.get("hoursSectionPresent")),
                hours_notes=str(hours_payload.get('hoursNotes', '')),
                menus=tuple(
                    RawMenu(str(item.get("name", "")), str(item.get("priceText", "")))
                    for item in payload.get("menus", [])
                    if isinstance(item, dict)
                ),
                business_days=tuple(
                    RawBusinessDay(
                        str(item.get("dayText", "")),
                        tuple(str(value) for value in item.get("details", [])),
                    )
                    for item in hours_payload.get("businessDays", [])
                    if isinstance(item, dict) and isinstance(item.get("details", []), list)
                ),
            )
        except PlaceCollectionError:
            raise
        except PlaywrightTimeoutError:
            raise PlaceCollectionError("fetch_failed", "page_timeout") from None
        except PlaywrightError:
            raise PlaceCollectionError("fetch_failed", "page_browser_error") from None
        finally:
            # 성공·실패와 관계없이 페이지 컨텍스트를 닫아 브라우저 자원을 회수한다.
            await context.close()
