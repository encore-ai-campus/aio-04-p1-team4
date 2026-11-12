import { configure, request, demoRestaurants } from "./api.js";
const $ = (s) => document.querySelector(s),
  state = {
    budget: 5000,
    remaining_minutes: 50,
    distance_m: 500,
    people: 1,
    category: "전체",
    origin: null,
    end_time: new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Seoul",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date(Date.now() + 60 * 60 * 1000)),
    participant_menus: [],
    game: null,
    menu: null,
    restaurants: [],
    selected: null,
    route: null,
    context: "",
  };
const settingsKey = "lunchrun-page-settings";
const reloaded =
  performance.getEntriesByType("navigation")[0]?.type === "reload";
try {
  if (reloaded) sessionStorage.removeItem(settingsKey);
  else
    Object.assign(
      state,
      JSON.parse(sessionStorage.getItem(settingsKey) || "{}"),
    );
} catch {}
function saveSettings() {
  try {
    sessionStorage.setItem(settingsKey, JSON.stringify(state));
  } catch {}
}
window.addEventListener("pagehide", saveSettings);
state.chat ||= [];
function consumeGameHandoff() {
  try {
    const handoff = JSON.parse(
      sessionStorage.getItem("lunchrun-game-handoff") || "null",
    );
    if (!handoff || typeof handoff.menu !== "string" || !handoff.menu.trim())
      return;
    state.menu = handoff.menu.trim();
    if (Number.isFinite(handoff.budget)) state.budget = handoff.budget;
    if (Number.isFinite(handoff.time)) {
      const parts = new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Seoul",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const get = (type) =>
        Number(parts.find((part) => part.type === type).value);
      const total = (get("hour") * 60 + get("minute") + handoff.time) % 1440;
      const endHour = String(Math.floor(total / 60)).padStart(2, "0");
      const endMinute = String(total % 60).padStart(2, "0");
      state.end_time = `${endHour}:${endMinute}`;
    }
    if (Number.isFinite(handoff.distance)) state.distance_m = handoff.distance;
    if (Number.isFinite(handoff.people)) state.people = handoff.people;
    if (typeof handoff.category === "string") state.category = handoff.category;
    if (
      Array.isArray(handoff.origin) &&
      handoff.origin.length === 2 &&
      handoff.origin.every(Number.isFinite)
    ) {
      state.origin = {
        latitude: handoff.origin[0],
        longitude: handoff.origin[1],
      };
    }
    sessionStorage.removeItem("lunchrun-game-handoff");
  } catch {}
}
consumeGameHandoff();
let demo = true,
  busy = false;
const escape = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const button = (label, action, cls = "") =>
  `<button class="${cls}" data-action="${action}">${label}</button>`;
function payload() {
  return {
    budget: Number(state.budget),
    remaining_minutes: remainingLunch(),
    lunch_end_time: state.end_time,
    distance_m: Number(state.distance_m),
    people: Number(state.people),
    origin: state.origin,
    menu: state.menu,
    game: state.game,
    context: state.context,
    time: new Date().toISOString(),
    participant_menus: state.participant_menus,
    category: state.people > 1 ? "전체" : state.category,
    restaurants: undefined,
    selected: undefined,
    route: undefined,
  };
}
function invalidate() {
  state.menu = null;
  state.restaurants = [];
  state.selected = null;
  state.route = null;
}
function go(r, gameSource = null) {
  saveSettings();
  if (r === "backend-games") {
    if (remainingLunch() < 10) {
      showTimeRequiredDialog();
      return;
    }
    try {
      sessionStorage.setItem(
        "lunchrun-games-settings",
        JSON.stringify({
          budget: Number(state.budget),
          time: remainingLunch(),
          distance: Number(state.distance_m),
          people: Number(state.people),
          categories: state.category === "전체" ? [] : [state.category],
          origin: state.origin,
        }),
      );
    } catch {
      $("#status").textContent =
        "게임에 조건을 전달하지 못했습니다. 브라우저 저장소 사용을 확인해주세요.";
      return;
    }
    location.assign("/games/");
    return;
  }
  if (r === "restaurants" && !state.menu) {
    $("#status").textContent = "게임에서 메뉴를 먼저 결정해주세요.";
    return;
  }
  if (r === "route" && (!state.menu || !state.selected || !state.route)) {
    $("#status").textContent = !state.menu
      ? "메뉴를 먼저 결정해주세요."
      : "식당 선택 화면에서 식당을 선택한 뒤 경로를 확인해주세요.";
    return;
  }
  if (["games", "group-input", "play"].includes(r) && state.people > 12) {
    $("#status").textContent =
      "12명 초과시 게임추천 서비스는 사용 할 수 없습니다.";
    return;
  }
  history.pushState(null, "", "#" + r);
  render();
  window.scrollTo(0, 0);
}

function showTimeRequiredDialog() {
  if (document.querySelector(".time-required-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.className = "location-dialog time-required-dialog";
  dialog.setAttribute("aria-labelledby", "time-required-title");
  dialog.innerHTML = `
    <form method="dialog" class="location-dialog-form">
      <h2 id="time-required-title">점심 종료시간을 설정 해주세요.</h2>
      <p>남은 시간이 10분 미만 입니다.</p>
      <button type="submit" class="location-apply">확인</button>
    </form>
  `;
  document.body.appendChild(dialog);
  dialog.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();
    dialog.close();
    go("time");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
}

async function run(fn) {
  if (busy) return;
  busy = true;
  $("#status").textContent = "처리 중…";
  try {
    await fn();
    $("#status").textContent = "";
  } catch (e) {
    $("#status").textContent =
      e.name === "AbortError"
        ? "요청 시간이 초과되었습니다. 다시 시도해주세요."
        : e.message;
  } finally {
    busy = false;
  }
}

// Keep the main app's navigation identical to the standalone game shell.
function renderNavigation(route, stage) {
  const items = [
    { label: "조건 설정", target: "conditions", active: stage === 0 },
    { label: "AI 추천", target: "ai", active: route === "ai" },
    {
      label: "게임 선택",
      target: "backend-games",
      active: stage === 1 && route !== "ai",
    },
    { label: "식당 선택", target: "restaurants", active: stage === 2 },
    { label: "경로 확인", target: "route", active: stage === 3 },
  ];
  $("#dock").innerHTML = items
    .map((item) =>
      button(item.label, "go:" + item.target, item.active ? "active" : ""),
    )
    .join("");
}

function render() {
  saveSettings();
  const r = location.hash.slice(1) || "conditions";
  const app = document.querySelector(".app"),
    previous = app.dataset.view;
  app.dataset.view = r;
  const enterDock =
    previous === undefined ||
    (previous !== r && (r === "conditions" || r === "games"));
  if (enterDock) {
    const dock = $("#dock");
    dock.classList.remove("dock-enter");
    void dock.offsetWidth;
    dock.classList.add("dock-enter");
  }
  let stage = [
    "conditions",
    "budget",
    "time",
    "end-time",
    "people",
    "distance",
  ].includes(r)
    ? 0
    : r === "restaurants"
      ? 2
      : r === "route"
        ? 3
        : 1;
  renderNavigation(r, stage);
  $("#summary").textContent = stage
    ? `${state.budget.toLocaleString()}원 / ${remainingLunch()}분 남음 / ${state.distance_m}m / ${state.people}명${state.people === 1 ? " / " + state.category : ""}`
    : "";
  let title = "오늘 점심, 어떻게 고를까요?",
    html = "";
  if (r === "conditions") {
    html =
      '<div class="grid">' +
      [
        ["예산설정", "budget", state.budget.toLocaleString() + "원"],
        ["남은시간", "time", remainingLunch() + "분"],
        ["거리설정", "distance", state.distance_m + "m"],
        ["인원 수 설정", "people", state.people + "명"],
      ]
        .map(
          ([l, p, v]) =>
            `<div class="field">${l}${button(v, "go:" + p, "card")}</div>`,
        )
        .join("") +
      '</div><p class="category-label">음식 카테고리</p><div class="chips">' +
      ["전체", "한식", "일식", "중식", "양식", "샐러드"]
        .map(
          (c) =>
            `<button data-category="${c}" ${state.people > 1 ? "disabled" : ""} class="${c === state.category ? "active" : ""}">${c}</button>`,
        )
        .join("") +
      '</div><p class="notice">다인 이용 시 음식 카테고리 선택이 비활성화됩니다.</p><div class="actions">' +
      (state.people > 12
        ? '<button class="primary" disabled>게임으로 메뉴 고르기</button>'
        : button("게임으로 메뉴 고르기", "go:backend-games", "primary")) +
      button("AI에게 추천받기", "go:ai") +
      "</div>";
  } else if (r === "budget") {
    html =
      '<div class="setting"><p>예산설정</p><div class="value">' +
      button("−", "money:-1000") +
      '<label class="money-field"><input id="budget-input" aria-label="예산 금액" inputmode="numeric" type="text" value="' +
      state.budget.toLocaleString("ko-KR") +
      '" autocomplete="off"><span>원</span></label>' +
      button("+", "money:1000") +
      '</div></div><div class="actions">' +
      button("적용", "apply-budget", "primary") +
      "</div>";
  } else if (r === "time" || r === "end-time") {
    const [hour, minute] = state.end_time.split(":").map(Number);
    html =
      '<div class="setting"><p>점심 종료 시간</p><div class="value time-value">' +
      button("−", "clock:-10") +
      '<div class="time-fields"><select id="period" aria-label="오전 오후"><option value="AM" ' +
      (hour < 12 ? "selected" : "") +
      '>AM</option><option value="PM" ' +
      (hour >= 12 ? "selected" : "") +
      '>PM</option></select><label><input id="end-hour" aria-label="종료 시" type="number" min="1" max="12" value="' +
      (hour % 12 || 12) +
      '"><span>시</span></label><label><input id="end-minute" aria-label="종료 분" type="number" min="0" max="59" value="' +
      String(minute).padStart(2, "0") +
      '"><span>분</span></label></div>' +
      button("+", "clock:10") +
      '</div><p class="input-hint">− / + 버튼으로 10분씩 조정합니다.</p></div><div class="actions">' +
      button("적용", "apply-time", "primary") +
      "</div>";
  } else if (r === "people") {
    html =
      '<div class="setting"><p>인원 수 설정</p><div class="value">' +
      button("−", "people-step:-1") +
      '<label class="people-field"><input id="people-input" aria-label="인원 수" aria-describedby="people-warning" type="number" min="1" step="1" value="' +
      state.people +
      '"><span>명</span></label>' +
      button("+", "people-step:1") +
      '</div><p id="people-warning" class="people-warning" role="status" ' +
      (state.people > 12 ? "" : "hidden") +
      '>12명 초과시 게임추천 서비스는 사용 할 수 없습니다.</p></div><div class="actions">' +
      button("적용", "apply-people", "primary") +
      "</div>";
  } else if (r === "distance") {
    html =
      '<div class="setting"><p>거리설정</p><div class="value">' +
      button("−", "adjust:distance_m:-100") +
      "<strong>" +
      state.distance_m +
      "m</strong>" +
      button("+", "adjust:distance_m:100") +
      '</div><input aria-label="거리설정" type="range" data-key="distance_m" min="0" max="1000" step="100" value="' +
      state.distance_m +
      '"><div class="ends"><span>0m</span><span>1000m</span></div></div><div class="actions">' +
      button("적용", "go:conditions", "primary") +
      "</div>";
  } else if (r === "games") {
    title =
      state.people === 1 ? "혼자서 가볍게 골라요" : "함께 먹을 메뉴를 골라요";
    html =
      '<div class="grid">' +
      (state.people === 1
        ? ["제비뽑기", "가챠", "행운권 뽑기", "랜덤게임"]
        : ["룰렛", "사다리"]
      )
        .map(
          (g) =>
            '<button class="card game-card" data-game="' +
            g +
            '" ' +
            (g === "사다리" && state.people > 8 ? "disabled" : "") +
            "><strong>" +
            g +
            "</strong><small>" +
            (g === "랜덤게임"
              ? "혼자 게임 중 하나를 자동 선택"
              : "선택 후 게임 진행") +
            "</small></button>",
        )
        .join("") +
      '</div><div class="actions">' +
      button("조건 변경", "go:conditions") +
      button("AI 추천", "go:ai") +
      "</div>";
  } else if (r === "group-input") {
    title = "각자의 메뉴를 입력해주세요";
    html =
      Array.from(
        { length: state.people },
        (_, i) =>
          `<label class="field">사용자 ${i + 1}<input data-participant="${i}" maxlength="50" value="${escape(state.participant_menus[i] || "")}" placeholder="메뉴 입력"></label>`,
      ).join("") + button("메뉴 결정", "prepare-group", "primary");
  } else if (r === "play") {
    title = "점심 메뉴를 뽑고 있어요";
    html =
      `<div class="card result">${escape(state.game)}</div>` +
      button("메뉴 뽑기", "draw", "primary");
  } else if (r === "ai") {
    title = "지금 나에게 맞는 메뉴";
    const nickname = window.LunchRunProfile.readName() || "게스트";
    html =
      `<div class="ai-chat" role="log" aria-label="AI와 대화" aria-live="polite">${state.chat.length ? state.chat.map((message) => `<div class="chat-row ${message.role}"><div class="chat-bubble">${message.role === "user" ? escape(message.name || nickname) : "✦ AI"} : ${escape(message.text)}</div><time class="chat-time">${message.time ? escape(new Date(message.time).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })) : ""}</time></div>`).join("") : '<p class="chat-welcome">✦ AI : 안녕하세요. 오늘 먹고 싶은 음식이나 컨디션을 알려주세요.</p>'}</div>
      <div class="ai-compose"><textarea id="context" aria-label="AI에게 메시지 입력" maxlength="1000" placeholder="날씨·기온·컨디션을 알려주세요">${escape(state.context)}</textarea><button type="button" data-action="chat" hidden></button></div>` +
      button("메뉴 추천받기", "recommend", "primary");
  } else if (r === "result") {
    title = "오늘의 점심 메뉴";
    html = `<div class="card result">${escape(state.menu || "아직 결정된 메뉴가 없습니다.")}</div><p>식당은 다음 단계에서 선택합니다.</p><div class="actions">${button("한번더", state.game ? "draw" : "recommend")}${button("OK · 식당 탐색", "find", "primary")}</div>`;
  } else if (r === "restaurants") {
    if (demo && !state.restaurants.length) {
      state.menu ||= "김치찌개";
      state.restaurants = demoRestaurants.map((restaurant) => ({
        ...restaurant,
        menu: state.menu,
      }));
    }
    title = "이 메뉴를 먹을 수 있는 곳";
    html =
      '<div class="restaurant-layout"><div class="restaurant-list">' +
      state.restaurants
        .map(
          (x) =>
            '<button class="card restaurant-card ' +
            (state.selected?.id === x.id ? "selected" : "") +
            '" data-restaurant="' +
            escape(x.id) +
            '"><strong>' +
            escape(x.name) +
            "</strong>" +
            escape(x.menu) +
            " " +
            escape(x.price) +
            "원<span>" +
            escape(x.distance_m) +
            "m · " +
            (x.walk_minutes === null
              ? "도보 시간 미확인"
              : "도보 " + escape(x.walk_minutes) + "분") +
            "</span></button>",
        )
        .join("") +
      '</div><figure class="map-preview"><img src="assets/restaurants.png" alt="예시 식당 지도"></figure></div><div class="actions">' +
      button("식당 랜덤", "random") +
      button("OK · 경로 확인", "route", "primary") +
      "</div>";
    if (!state.restaurants.length)
      html =
        "<p>후보가 없습니다. 조건을 변경해주세요.</p>" +
        button("식당 검색", "find");
  } else if (r === "route") {
    title = "선택한 식당으로 출발";
    html = state.route
      ? '<div class="map"><div class="card route-summary"><strong>총소요예상 ' +
        escape(state.route.walk_minutes) +
        "분　│　총거리 " +
        escape(state.route.distance_m) +
        "m</strong><p>현재 위치 → " +
        escape(state.selected?.name) +
        ' / 편도 도보 예상 · 예시</p></div><img src="assets/route.png" alt="도보 경로 예시"><button class="route-back" data-action="go:restaurants">다른 식당 선택</button></div><p class="route-note">대기·식사·왕복 시간 포함 여부는 미확정입니다.</p>'
      : "<p>식당을 먼저 선택해주세요.</p>" +
        button("식당 선택", "go:restaurants");
  } else {
    html = button("조건 설정으로", "go:conditions");
  }
  $("#title").textContent = title;
  $("#screen").innerHTML = html;
  window.LunchRunMotion?.enter(document.querySelector(".app main"), r);
  fitBudgetWidth();
  const expanded = document.querySelector(".setting .value");
  if (expanded) expanded.style.viewTransitionName = "condition-expand";
  const icons = {
    전체: "M3 17h26M5 16a11 11 0 0 1 22 0M14 3h4M16 3v3",
    한식: "M4 14h24c0 8-5 13-12 13S4 22 4 14M8 10l2-4m6 4V5m6 5 2-4",
    일식: "M4 20c0-9 24-13 24-3v6H4ZM10 15l3 7m4-10 3 9",
    중식: "M4 16h24c0 8-5 12-12 12S4 24 4 16M9 11c-5-5 5-5 0-10m7 10c-5-5 5-5 0-10m7 10c-5-5 5-5 0-10",
    양식: "M8 3v12m-4-12v8c0 5 8 5 8 0V3M8 15v14M24 3c-8 5-8 13 0 13V3v26",
    샐러드:
      "M4 17h24c-1 7-5 11-12 11S5 24 4 17M16 16C4 16 6 3 10 6c4 2 6 6 6 10Zm0 0c0-12 9-13 10-10-1 5-4 8-10 10Z",
  };
  document
    .querySelectorAll("[data-category]")
    .forEach((b) =>
      b.insertAdjacentHTML(
        "afterbegin",
        '<svg class="food-icon" width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="' +
          icons[b.dataset.category] +
          '"/></svg>',
      ),
    );

  const img = (name, alt) =>
    '<img class="visual-asset" src="assets/' +
    name +
    '.png" alt="' +
    alt +
    '">';
  if (r === "play") {
    document.querySelector(".result").style.viewTransitionName = "game-expand";
    const names = {
      제비뽑기: "draw",
      가챠: "gacha",
      "행운권 뽑기": "ticket",
      랜덤게임: "random",
      룰렛: "roulette",
      사다리: "ladder",
    };
    $("#screen .result").innerHTML = img(
      names[state.game] || "gacha",
      state.game || "게임 예시",
    );
    $("#screen .result").insertAdjacentHTML(
      "afterend",
      '<p class="play-note">설정 조건 안에서 음식 메뉴만 추첨합니다.</p>',
    );
  }
  if (r === "games") {
    const names = {
      제비뽑기: "draw",
      가챠: "gacha",
      "행운권 뽑기": "ticket",
      랜덤게임: "random",
      룰렛: "roulette",
      사다리: "ladder",
    };
    document
      .querySelectorAll("[data-game]")
      .forEach((b) =>
        b.insertAdjacentHTML(
          "beforeend",
          img("option-" + names[b.dataset.game], b.dataset.game + " 예시"),
        ),
      );
  }
  if (r === "result") {
    const result = $("#screen .result");
    result.className = "card menu-result";
    result.innerHTML =
      img("result", "선택 메뉴 예시") +
      "<div><small>선택된 음식 메뉴</small><strong>" +
      escape(state.menu || "아직 미결정") +
      "</strong><p>식당은 다음 단계에서 선택합니다.</p></div>";
    result.nextElementSibling.remove();
  }
  if (false)
    $("#screen").insertAdjacentHTML(
      "afterbegin",
      '<figure class="map-preview">' +
        img("restaurants", "식당 위치 예시 지도") +
        "</figure>",
    );
  if (false)
    $("#screen .map").innerHTML =
      img("route", "선택 식당까지 도보 경로 예시") +
      "<p>예시 경로 · 실제 길찾기 연동 전</p>";
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.category) {
    state.category = b.dataset.category;
    invalidate();
    render();
  }
  if (b.dataset.game) {
    state.game = b.dataset.game;
    state.participant_menus = [];
    go(
      state.people > 1 ? "group-input" : "play",
      state.people === 1 ? b : null,
    );
  }
  if (b.dataset.restaurant) {
    state.selected = state.restaurants.find(
      (x) => x.id === b.dataset.restaurant,
    );
    render();
    $("#status").textContent = state.selected.name + " 선택됨";
  }
  const a = b.dataset.action;
  if (!a) return;
  if (a.startsWith("money:")) {
    commitBudget();
    state.budget = Math.max(
      1000,
      Math.min(100000000, state.budget + Number(a.split(":")[1])),
    );
    invalidate();
    render();
    return;
  }
  if (a === "apply-people") {
    if (commitPeople()) go("conditions");
    return;
  }
  if (a.startsWith("people-step:")) {
    if (!commitPeople()) return;
    state.people = Math.max(1, state.people + Number(a.split(":")[1]));
    invalidate();
    render();
    return;
  }
  if (a === "apply-budget") {
    commitBudget();
    go("conditions");
    return;
  }
  if (a.startsWith("clock:")) {
    if (!commitTime()) return;
    const [h, m] = state.end_time.split(":").map(Number);
    const total = (h * 60 + m + Number(a.split(":")[1]) + 1440) % 1440;
    state.end_time =
      String(Math.floor(total / 60)).padStart(2, "0") +
      ":" +
      String(total % 60).padStart(2, "0");
    invalidate();
    render();
    return;
  }
  if (a === "apply-time") {
    if (commitTime()) {
      invalidate();
      go("conditions");
    }
    return;
  }
  if (a.startsWith("go:")) return go(a.slice(3));
  if (a.startsWith("adjust:")) {
    const [, k, v] = a.split(":");
    const ranges = {
      budget: [1000, 100000000],
      remaining_minutes: [1, 180],
      people: [1, Infinity],
      distance_m: [0, 1000],
    };
    state[k] = Math.max(
      ranges[k][0],
      Math.min(ranges[k][1], state[k] + Number(v)),
    );
    if (state.people > 1) state.category = "전체";
    invalidate();
    render();
    return;
  }
  if (a === "prepare-group") {
    if (
      Array.from({ length: state.people }, (_, i) =>
        state.participant_menus[i]?.trim(),
      ).some((v) => !v)
    ) {
      $("#status").textContent = "참가자별 메뉴를 모두 입력해주세요.";
      return;
    }
    go("play");
    return;
  }
  run(async () => {
    if (a === "draw" || a === "recommend" || a === "chat") {
      if ((a === "recommend" || a === "chat") && $("#context"))
        state.context = $("#context").value;
      if (!demo && !state.origin) throw Error("위치 설정을 먼저 해주세요.");
      const result = demo
        ? { menu: "김치찌개" }
        : await request("/api/menu-decisions", {
            ...payload(),
            method: a === "draw" ? "game" : "ai",
          });
      if (!result.menu) throw Error("메뉴 응답 형식을 확인해주세요.");
      state.menu = result.menu;
      state.restaurants = [];
      state.selected = null;
      state.route = null;
      if (a !== "draw") {
        if (state.context.trim())
          state.chat.push({
            role: "user",
            name: window.LunchRunProfile.readName() || "게스트",
            text: state.context,
            time: new Date().toISOString(),
          });
        state.chat.push({
          role: "ai",
          text: `${state.menu} 메뉴를 추천해요.`,
          time: new Date().toISOString(),
        });
        state.context = "";
        saveSettings();
        if (a === "chat") {
          render();
          return;
        }
        sessionStorage.setItem(
          "lunchrun-ai-result",
          JSON.stringify({ name: state.menu }),
        );
        sessionStorage.setItem(
          "lunchrun-games-settings",
          JSON.stringify({
            budget: state.budget,
            time: remainingLunch(),
            distance: state.distance_m,
            people: state.people,
            categories: state.category === "전체" ? [] : [state.category],
            origin: state.origin,
          }),
        );
        location.assign("/games/#play");
        return;
      }
      go("result");
    }
    if (a === "find") {
      if (!state.menu) throw Error("메뉴를 먼저 결정해주세요.");
      const result = demo
        ? { restaurants: demoRestaurants }
        : await request("/api/restaurants/search", payload());
      if (!Array.isArray(result.restaurants))
        throw Error("식당 응답 형식 오류");
      state.restaurants = result.restaurants;
      state.selected = null;
      go("restaurants");
    }
    if (a === "random") {
      if (!state.restaurants.length) throw Error("후보가 없습니다.");
      state.selected =
        state.restaurants[Math.floor(Math.random() * state.restaurants.length)];
      render();
      $("#status").textContent = state.selected.name + " 선택됨";
    }
    if (a === "route") {
      if (!state.selected) throw Error("식당을 선택해주세요.");
      state.route = demo
        ? {
            distance_m: state.selected.distance_m,
            walk_minutes: state.selected.walk_minutes ?? 9,
          }
        : await request("/api/routes", {
            origin: state.origin,
            restaurant_id: state.selected.id,
          });
      go("route");
    }
  });
});
document.addEventListener("input", (e) => {
  if (e.target.dataset.key) {
    state[e.target.dataset.key] = Number(e.target.value);
    if (state.people > 1) state.category = "전체";
    invalidate();
    const val = $("#screen .value strong");
    if (val) {
      const k = e.target.dataset.key;
      val.textContent =
        k === "budget"
          ? state[k].toLocaleString() + "원"
          : state[k] +
            ({ people: "명", distance_m: "m", remaining_minutes: "분" }[k] ||
              "");
    }
  }
  if (e.target.dataset.participant !== undefined)
    state.participant_menus[Number(e.target.dataset.participant)] =
      e.target.value;
});
let selectedLocation = window.LunchRunLocation.read();
if (selectedLocation) {
  state.origin = {
    latitude: selectedLocation.latitude,
    longitude: selectedLocation.longitude,
  };
}
$("#location").onclick = () => {
  window.LunchRunLocation.open({
    current: selectedLocation,
    onChange(value) {
      selectedLocation = value;
      state.origin = { latitude: value.latitude, longitude: value.longitude };
      invalidate();
      render();
      $("#status").textContent = value.name + " 위치가 설정되었습니다.";
    },
  });
};
window.addEventListener("hashchange", render);
render();
configure()
  .then((v) => {
    demo = v;
    $("#mode").textContent = demo ? "" : "백엔드 연결 모드";
    render();
  })
  .catch((e) => {
    $("#mode").textContent = "설정 확인 전 · 시안 미리보기";
    $("#status").textContent = e.message;
  });

$("#account").onclick = () => {
  window.LunchRunProfile.open({
    onChange(name) {
      $("#status").textContent = name
        ? `${name}님, 오늘도 맛있는 점심 되세요!`
        : "게스트 모드로 전환했어요. 취향은 이 브라우저에 유지돼요.";
    },
  });
};

function fitCanvas() {
  document.documentElement.style.setProperty(
    "--scale",
    Math.min(1, window.innerWidth / 1516, window.innerHeight / 1038),
  );
}
window.addEventListener("resize", fitCanvas);
fitCanvas();

function remainingLunch() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (t) => Number(parts.find((p) => p.type === t).value);
  const [h, m] = state.end_time.split(":").map(Number);
  return Math.max(0, h * 60 + m - get("hour") * 60 - get("minute"));
}
function displayEndTime() {
  const [h, m] = state.end_time.split(":").map(Number);
  return (
    (h < 12 ? "AM" : "PM") +
    " " +
    String(h % 12 || 12).padStart(2, "0") +
    ":" +
    String(m).padStart(2, "0")
  );
}
function commitBudget() {
  const el = $("#budget-input");
  if (!el) return;
  const digits = el.value.replace(/[^0-9]/g, "");
  state.budget = Math.min(100000000, Math.max(1000, Number(digits) || 1000));
  el.value = state.budget.toLocaleString("ko-KR");
  fitBudgetWidth();
  invalidate();
}
function commitTime() {
  const h = $("#end-hour"),
    m = $("#end-minute");
  if (!h || !m) return false;
  const hh = Number(h.value),
    mm = Number(m.value);
  if (
    h.value === "" ||
    m.value === "" ||
    !Number.isInteger(hh) ||
    !Number.isInteger(mm) ||
    hh < 1 ||
    hh > 12 ||
    mm < 0 ||
    mm > 59
  ) {
    $("#status").textContent =
      "시는 1~12, 분은 0~59 사이의 정수로 입력해주세요.";
    return false;
  }
  state.end_time =
    String((hh % 12) + ($("#period").value === "PM" ? 12 : 0)).padStart(
      2,
      "0",
    ) +
    ":" +
    String(mm).padStart(2, "0");
  $("#status").textContent = "";
  return true;
}
document.addEventListener("input", (e) => {
  if (e.target.id === "budget-input") {
    const el = e.target,
      caret = el.selectionStart,
      leftDigits = el.value.slice(0, caret).replace(/[^0-9]/g, "").length;
    let raw = el.value.replace(/[^0-9]/g, "");
    if (Number(raw) > 100000000) raw = "100000000";
    el.value = raw ? Number(raw).toLocaleString("ko-KR") : "";
    let seen = 0,
      pos = 0;
    while (pos < el.value.length && seen < leftDigits) {
      if (/[0-9]/.test(el.value[pos])) seen++;
      pos++;
    }
    el.setSelectionRange(pos, pos);
    fitBudgetWidth();
  }
});
document.addEventListener("focusout", (e) => {
  if (e.target.id === "budget-input") commitBudget();
});

function fitBudgetWidth() {
  const el = document.querySelector("#budget-input");
  if (!el) return;
  const context = document.createElement("canvas").getContext("2d");
  if (!context) return;
  const style = getComputedStyle(el);
  context.font =
    style.fontWeight + " " + style.fontSize + " " + style.fontFamily;
  el.style.width =
    Math.ceil(context.measureText(el.value || "0").width + 4) + "px";
}
function refreshRemainingTime() {
  const button = document.querySelector(
    '.app[data-view="conditions"] [data-action="go:time"]',
  );
  if (button) button.textContent = remainingLunch() + "분";
  const summary = document.querySelector("#summary");
  if (summary && summary.textContent) {
    summary.textContent =
      state.budget.toLocaleString() +
      "원 / " +
      remainingLunch() +
      "분 남음 / " +
      state.distance_m +
      "m / " +
      state.people +
      "명" +
      (state.people === 1 ? " / " + state.category : "");
  }
}
setInterval(refreshRemainingTime, 15000);
window.addEventListener("focus", refreshRemainingTime);

function commitPeople() {
  const el = $("#people-input");
  if (!el) return true;
  const n = Number(el.value);
  if (!el.value || !Number.isSafeInteger(n) || n < 1) {
    $("#status").textContent = "인원 수는 1명 이상의 정수로 입력해주세요.";
    return false;
  }
  state.people = n;
  if (n > 1) state.category = "전체";
  invalidate();
  $("#status").textContent = "";
  return true;
}
document.addEventListener("input", (e) => {
  if (e.target.id !== "people-input") return;
  const n = Number(e.target.value);
  $("#people-warning").hidden = !(n > 12);
  if (Number.isSafeInteger(n) && n >= 1) {
    state.people = n;
    if (n > 1) state.category = "전체";
    invalidate();
  }
});
document.addEventListener("focusout", (e) => {
  if (e.target.id === "people-input") commitPeople();
});

// Enter sends a message; Shift+Enter keeps the textarea's native newline.
document.addEventListener("keydown", (event) => {
  if (
    event.target.id !== "context" ||
    event.key !== "Enter" ||
    event.shiftKey ||
    event.isComposing
  )
    return;
  event.preventDefault();
  if (!busy && event.target.value.trim())
    document.querySelector('[data-action="chat"]')?.click();
});
