import {
  MENUS,
  filterMenus,
  randomIndex,
  pickMenu,
  parsePrompt,
  buildLadder,
  createSpotlightPlan,
} from "./engine.mjs";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const won = (n) => n.toLocaleString("ko-KR");
const total = (m) => Math.ceil(m.distance / 70) * 2 + m.meal + m.wait;
const delay = (n) =>
  new Promise((r) =>
    setTimeout(
      r,
      matchMedia("(prefers-reduced-motion: reduce)").matches ? 60 : n,
    ),
  );
const read = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
};
function takeLaunchSettings() {
  try {
    const raw = sessionStorage.getItem("lunchrun-games-settings");
    if (!raw) return { settings: {}, warning: "" };
    sessionStorage.removeItem("lunchrun-games-settings");
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error("invalid settings");
    const settings = {},
      warnings = [];
    const number = (key, min, max) => {
      if (value[key] === undefined) return;
      const n = Number(value[key]);
      if (!Number.isFinite(n) || n < min || n > max) warnings.push(key);
      else settings[key] = n;
    };
    number("budget", 0, 100000000);
    number("time", 0, 180);
    number("distance", 0, 1000);
    number("people", 1, 12);
    if (
      Array.isArray(value.categories) &&
      value.categories.every((c) =>
        ["한식", "일식", "중식", "양식", "분식", "아시안", "샐러드"].includes(
          c,
        ),
      )
    )
      settings.categories = value.categories;
    else if (value.categories !== undefined) warnings.push("categories");
    if (value.origin !== null && value.origin !== undefined) {
      const { latitude, longitude } = value.origin;
      if (
        Number.isFinite(latitude) &&
        latitude >= -90 &&
        latitude <= 90 &&
        Number.isFinite(longitude) &&
        longitude >= -180 &&
        longitude <= 180
      )
        settings.origin = [latitude, longitude];
      else warnings.push("origin");
    }
    return {
      settings,
      warning: warnings.length
        ? "일부 전달된 조건을 사용할 수 없어 기본값으로 설정했어요."
        : "",
    };
  } catch {
    return {
      settings: {},
      warning: "전달된 조건을 읽지 못해 게임 기본값으로 설정했어요.",
    };
  }
}
const prefs = read("lunchrun-demo2", {});
const launch = takeLaunchSettings();
const state = {
  gameScreen: location.hash === "#play" ? "play" : "select",
  view: "game",
  mode: launch.settings.people > 1 ? "group" : "solo",
  game: launch.settings.people > 1 ? "roulette" : "gacha",
  budget: launch.settings.budget ?? 12000,
  time: launch.settings.time ?? 45,
  distance: launch.settings.distance ?? 500,
  categories: launch.settings.categories ?? [],
  people: launch.settings.people ?? 1,
  names: Array.from({ length: 12 }, (_, i) =>
    i === 0 ? "나" : `팀원 ${i + 1}`,
  ),
  favorites: Array.isArray(prefs.favorites) ? prefs.favorites : [],
  blacklist: Array.isArray(prefs.blacklist) ? prefs.blacklist : [],
  profile: typeof prefs.profile === "string" ? prefs.profile : "",
  location: launch.settings.origin ? "현재 위치" : "독산역",
  origin: launch.settings.origin ?? null,
  result: null,
  pending: null,
  previous: null,
  busy: false,
  ladder: null,
  ladderStart: 0,
  selectedRestaurant: 0,
  route: false,
  aiReady: false,
  aiPrompt: "",
  aiNotes: [],
  restaurantCandidates: null,
  restaurantDrawing: false,
  restaurantDrawDone: false,
  restaurantSpotlight: -1,
};
const games = {
  draw: {
    name: "제비뽑기",
    sub: "느낌 오는 카드 한 장",
    icon: "▱",
    badge: "PICK A CARD",
  },
  gacha: {
    name: "가챠",
    sub: "돌려서 만나는 점심",
    icon: "◒",
    badge: "CAPSULE PICK",
  },
  ticket: {
    name: "행운권 뽑기",
    sub: "오늘의 행운을 열어요",
    icon: "▤",
    badge: "LUCKY TICKET",
  },
  random: {
    name: "랜덤 게임",
    sub: "게임도 운명에 맡기기",
    icon: "⚄",
    badge: "SURPRISE ME",
  },
  roulette: {
    name: "룰렛",
    sub: "함께 돌리는 오늘의 메뉴",
    icon: "◉",
    badge: "SPIN TOGETHER",
  },
  ladder: {
    name: "사다리 타기",
    sub: "어느 길로 가볼까요?",
    icon: "⋈",
    badge: "FOLLOW YOUR LUCK",
  },
};
let toastTimer;
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 3200);
}
function persist() {
  try {
    localStorage.setItem(
      "lunchrun-demo2",
      JSON.stringify({
        favorites: state.favorites,
        blacklist: state.blacklist,
        profile: state.profile,
      }),
    );
  } catch {
    toast("브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 유지돼요.");
  }
  updateProfile();
}
function candidates() {
  return filterMenus(state);
}
function menuStats(m) {
  return /* HTML */ `<span>${won(m.price)}원</span><span>총 ${total(m)}분</span
    ><span>도보 ${Math.ceil(m.distance / 70)}분</span>`;
}
const busyControls = new Map();
function setBusy(value) {
  state.busy = value;
  if (value) {
    for (const e of $$(
      "button, .location-dialog select, .participant-inputs input",
    )) {
      if (!busyControls.has(e)) busyControls.set(e, e.disabled);
      e.disabled = true;
    }
  } else {
    for (const [e, disabled] of busyControls) {
      if (e.isConnected) e.disabled = disabled;
    }
    busyControls.clear();
  }
  $(".play-board").setAttribute("aria-busy", String(value));
  $("#board-status").innerHTML = value
    ? '<i class="live-dot"></i> PICKING YOUR LUNCH…'
    : state.result
      ? '<i class="live-dot"></i> LUNCH DECIDED!'
      : '<i class="live-dot"></i> READY TO PLAY';
}
function updateProfile() {
  // A locally saved nickname is not a signed-in member account.
  $("[data-member-only]").hidden = true;
  $("#profile-label").textContent = state.profile || "게스트";
  $(".avatar").textContent = state.profile ? state.profile.slice(0, 1) : "G";
  $("#saved-count").textContent = state.favorites.length;
}
function updateProgress() {
  updateShell();
  const step =
    state.view === "restaurants"
      ? state.result
        ? state.route
          ? 3
          : 2
        : 1
      : 1;
  $$(".progress-step").forEach((e) =>
    e.classList.toggle("active", Number(e.dataset.step) === step),
  );
  const decisionStep = state.route
    ? 5
    : state.view === "restaurants"
      ? state.restaurantDrawDone
        ? 4
        : 3
      : state.result
        ? 3
        : state.aiReady
          ? 2
          : 1;
  $$("#decision-steps > span").forEach((e, i) => {
    e.classList.toggle("is-current", i + 1 === decisionStep);
    e.classList.toggle("is-done", i + 1 < decisionStep);
  });
}
// Conditions come from the home screen; the header edits only location.

function openLocationSettings() {
  const point = state.origin || window.LunchRunLocation.places[state.location];
  window.LunchRunLocation.open({
    current: point
      ? { name: state.location, latitude: point[0], longitude: point[1] }
      : null,
    onChange(value) {
      state.location = value.name;
      state.origin = [value.latitude, value.longitude];
      conditionsChanged();
    },
  });
}

function resetRestaurantDraw() {
  state.restaurantCandidates = null;
  state.restaurantDrawDone = false;
  state.restaurantSpotlight = -1;
  state.restaurantDrawing = false;
}
function conditionsChanged() {
  if (state.busy) return;
  resetRound();
  state.result = null;
  state.pending = null;
  state.route = false;
  state.selectedRestaurant = 0;
  state.ladder = null;
  state.aiReady = false;
  resetRestaurantDraw();
  render();
}
function render() {
  updateProgress();
  const pool = candidates();
  $("#pool-count").textContent = pool.length;
  // The candidate panel is hidden in this layout. Avoid building hundreds of
  // offscreen buttons during the initial route change.
  if (!$("#menu-pool").closest("[hidden]")) {
    $("#menu-pool").innerHTML = pool.length
      ? pool
          .map(
            (m) =>
              /* HTML */ `<button class="menu-chip" data-detail="${m.id}">
                <span>${m.emoji}</span><span>${esc(m.name)}</span
                ><small>${esc(m.category)}</small>
              </button>`,
          )
          .join("")
      : '<div class="empty-state"><span>⌕</span><h3>조건에 맞는 메뉴가 없어요</h3><p>예산·시간·거리를 조금 늘리거나<br>카테고리를 바꿔보세요.</p><button class="secondary" data-action="reset">조건 초기화</button></div>';
  }
  renderGame(pool);
  renderSuggestions(pool);
  if (state.view === "restaurants") renderRestaurants();
  if (state.view === "saved") renderSaved();
}
function renderGame(pool) {
  ensureGroup(pool);
  updateProgress();
  const types =
    state.mode === "group"
      ? ["roulette", "ladder"]
      : state.mode === "ai"
        ? []
        : ["draw", "gacha", "ticket", "random"];
  $$(".mode-tabs button").forEach((e) => {
    e.classList.toggle("active", e.dataset.mode === state.mode);
    e.setAttribute("aria-pressed", String(e.dataset.mode === state.mode));
  });
  $("#game-options").hidden = state.mode === "ai";
  $("#game-options").innerHTML = types
    .map(
      (k) =>
        /* HTML */ `<button
          class="game-option ${state.game === k ? "active" : ""}"
          data-game="${k}"
          aria-pressed="${state.game === k}"
        >
          <img
            class="game-option-art"
            src="./assets/option-${k}.png"
            alt=""
            width="150"
            height="125"
          /><span
            ><strong>${games[k].name}</strong
            ><small>${games[k].sub}</small></span
          ><span class="game-option-check"
            >${state.game === k ? "✓" : "↗"}</span
          >
        </button>`,
    )
    .join("");
  const group = $("#group-settings");
  group.hidden = state.mode !== "group";
  if (state.mode === "group")
    group.innerHTML = /* HTML */ `<div class="group-line">
        <label
          >${state.game === "roulette" ? "룰렛 입력값" : "참가자 이름"} ·
          ${state.people}명</label
        >
      </div>
      <div class="participant-inputs">
        ${Array.from({ length: state.people }, (_, i) => /* HTML */ `<input class="field" ${state.game === "roulette" ? "data-entry" : "data-name"}="${i}" aria-label="${state.game === "roulette" ? "룰렛 입력값" : "참가자 이름"} ${i + 1}" maxlength="60" value="${esc(state.game === "roulette" ? gs.entries[i] : state.names[i])}" ${gs.started && state.game === "ladder" ? "disabled" : ""} />`).join("")}
      </div>`;

  $("#game-badge").textContent =
    state.mode === "ai" ? "SMART LUNCH ASSISTANT" : games[state.game].badge;
  $("#game-footnote").textContent =
    pool.length === 0
      ? "조건에 맞는 메뉴가 없어요. 시간·예산·거리를 늘려주세요."
      : pool.length === 1
        ? "조건에 맞는 메뉴가 1개예요. 이 메뉴로 결정해 볼까요?"
        : "조건에 맞는 메뉴만 담았어요. 마음 편히 뽑아보세요!";
  if (state.mode === "group")
    $("#game-footnote").textContent =
      "입력한 값으로 추첨해요. 현재 조건의 CSV 메뉴명과 일치하는 당첨값만 식당 탐색에 연결돼요.";
  if (state.result) {
    renderResult();
    return;
  }
  if (state.mode === "ai") {
    renderAI();
    return;
  }
  const name = games[state.game].name;
  let html = /* HTML */ `<div class="stage-heading">
    <h3>
      ${state.game === "gacha" ? "돌려볼까요, 맛있는 행운?" : state.game === "draw" ? "마음이 가는 한 장을 골라보세요" : state.game === "ticket" ? "오늘의 행운은 어느 티켓에?" : state.game === "roulette" ? "우리의 점심을 돌려봐요" : state.game === "ladder" ? "출발할 친구를 선택해 주세요" : "오늘은 어떤 게임이 기다릴까요?"}
    </h3>
    <p>
      ${state.mode === "group" ? "모두 함께 먹을 메뉴 하나를 정해요." : "작은 설렘 하나로, 점심 고민 끝."}
    </p>
  </div>`;
  if (state.game === "gacha")
    html += state.pending
      ? /* HTML */ `<div class="capsule-reveal">
          <div class="capsule-glow"></div>
          <button
            class="open-capsule"
            data-action="open-capsule"
            aria-label="뽑은 캡슐 열기"
          >
            <span class="capsule-top"></span
            ><span class="capsule-bottom">?</span>
          </button>
          <h3>두근두근, 캡슐이 나왔어요!</h3>
          <p>캡슐을 눌러 오늘의 메뉴를 확인해 보세요</p>
        </div>`
      : gachaArt();
  if (state.game === "draw")
    html += /* HTML */ `<div class="draw-grid">
      ${Array.from({ length: 6 }, (_, i) => /* HTML */ `<button class="draw-card" data-draw="${i}" ${!pool.length ? "disabled" : ""}><span>✳</span><strong>?</strong><small>LUNCH ${String(i + 1).padStart(2, "0")}</small></button>`).join("")}
    </div>`;
  if (state.game === "ticket")
    html += /* HTML */ `<div class="ticket-stack">
      ${["GOOD LUCK", "YUMMY DAY", "HAPPY LUNCH"]
        .map(
          (t, i) =>
            /* HTML */ `<button
              class="lucky-ticket"
              data-ticket="${i}"
              ${!pool.length ? "disabled" : ""}
            >
              <span>★ LUNCH RUN LOTTERY ★</span><strong>${t}</strong
              ><small>눌러서 행운 확인하기 <b>↗</b></small>
            </button>`,
        )
        .join("")}
    </div>`;
  if (state.game === "random")
    html += /* HTML */ `<div class="random-scene">
      <span class="random-orbit"></span>
      <div class="big-dice">⚄</div>
      <span class="random-label">LET LUCK CHOOSE THE GAME</span>
    </div>`;
  if (state.game === "roulette")
    html += wheelArt(
      gs.entries.slice(0, state.people).map((name) => ({ name })),
    );
  if (state.game === "ladder") {
    if (!state.ladder) state.ladder = buildLadder(state.people);
    html += ladderArt(pool);
  }
  $("#game-stage").innerHTML = html;
  const action =
    state.game === "gacha"
      ? state.pending
        ? "캡슐 열어보기"
        : "캡슐 뽑기"
      : state.game === "roulette"
        ? "룰렛 돌리기"
        : state.game === "ladder"
          ? "사다리 출발!"
          : state.game === "random"
            ? "랜덤 게임 시작"
            : "위에서 하나를 골라주세요";
  if (state.game === "ladder") {
    $("#game-actions").innerHTML =
      '<span>참가자를 누른 순서대로 진행해요</span><button class="secondary" data-action="reset-ladder">새 사다리</button>';
    return;
  }
  $("#game-actions").innerHTML = ["draw", "ticket"].includes(state.game)
    ? /* HTML */ `<span class="interaction-hint"
        >↑ ${state.game === "draw" ? "카드" : "티켓"}를 직접 눌러보세요</span
      >`
    : /* HTML */ `<button
        class="primary play-cta"
        data-action="${state.pending ? "open-capsule" : "play"}"
        ${!pool.length && state.mode !== "group" ? "disabled" : ""}
      >
        ${games[state.game].icon} ${action}<span>↗</span>
      </button>`;
}
function gachaArt() {
  return /* HTML */ `
    <div class="machine-scene">
      <img
        class="gacha-machine"
        src="./assets/gacha-machine.png"
        alt="오렌지색 점심 캡슐 뽑기 기계"
        width="232"
        height="240"
      />
    </div>
  `;
}

function wheelArt(pool) {
  const n = pool.length || 1,
    colors = ["#FF641B", "#233550", "#C5FF24", "#354863", "#FF9A63", "#466143"];
  const paths = pool
    .map((m, i) => {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2,
        b = ((i + 1) / n) * Math.PI * 2 - Math.PI / 2,
        mid = (a + b) / 2;
      const point = (t) =>
        `${160 + 145 * Math.cos(t)},${160 + 145 * Math.sin(t)}`;
      return /* HTML */ `<path
          d="M160,160 L${point(a)} A145,145 0 ${n === 1 ? 1 : 0},1 ${point(b)} Z"
          fill="${colors[i % colors.length]}"
          stroke="#0C1426"
          stroke-width="2"
        /><text
          x="${160 + 102 * Math.cos(mid)}"
          y="${160 + 102 * Math.sin(mid)}"
          fill="${i % colors.length === 2 ? "#142331" : "#fff"}"
          font-size="${n > 16 ? 10 : 12}"
          font-weight="700"
          text-anchor="middle"
          dominant-baseline="central"
          transform="rotate(${(mid * 180) / Math.PI + 90},${160 + 102 * Math.cos(mid)},${160 + 102 * Math.sin(mid)})"
          >${esc(m.name.slice(0, 6))}</text
        >`;
    })
    .join("");
  return /* HTML */ `<div class="wheel-scene">
    <span class="wheel-pointer">▼</span
    ><svg
      class="roulette-wheel"
      viewBox="0 0 320 320"
      role="img"
      aria-label="${pool.length}개 메뉴가 담긴 룰렛"
    >
      <circle
        cx="160"
        cy="160"
        r="155"
        fill="#17243B"
        stroke="#d0deee"
        stroke-width="3"
      />
      ${n === 1 && pool.length ? '<circle cx="160" cy="160" r="145" fill="#FF641B"/>' : ""}${paths}</svg
    ><span class="wheel-center">LUNCH<br />RUN ↗</span>
  </div>`;
}
const gs = {
  entries: [],
  menus: [],
  queue: [],
  played: [],
  started: false,
  running: false,
  winningEnd: null,
  current: null,
  log: [],
};
function ensureGroup(pool) {
  for (let i = 0; i < state.people; i++) {
    if (gs.entries[i] === undefined)
      gs.entries[i] = pool[i]?.name || `입력값 ${i + 1}`;
    if (gs.menus[i] === undefined) gs.menus[i] = pool[i]?.name || "";
  }
}
function resetRound() {
  gs.queue = [];
  gs.played = [];
  gs.started = false;
  gs.running = false;
  gs.winningEnd = null;
  gs.current = null;
  gs.log = [];
  state.ladder = null;
}
function entryResult(name) {
  return (
    candidates().find((m) => m.name === name) || {
      id: "custom-" + name,
      name,
      emoji: "🎯",
      entryOnly: true,
      offers: [],
      price: 0,
      distance: 0,
      meal: 0,
      wait: 0,
      desc: "입력한 값이 당첨됐어요. 현재 필터에 맞는 CSV 메뉴명과 일치해야 식당을 찾을 수 있어요.",
    }
  );
}
function ladderArt(pool) {
  const l = state.ladder,
    x = (i) => 45 + (i * 510) / (state.people - 1),
    y = (r) => 25 + (r * 175) / (l.rows + 1);
  return /* HTML */ `<div class="ladder-wrap">
    <p>
      위쪽 메뉴를 설정하고 참가자를 클릭하세요. 한 도착점만 당첨, 나머지는
      꽝입니다.
    </p>
    <div class="ladder-menu-grid" style="--count:${state.people}">
      ${Array.from({ length: state.people }, (_, i) => /* HTML */ `<label>메뉴 ${i + 1}<input class="field" data-ladder-menu="${i}" aria-label="사다리 메뉴 ${i + 1}" value="${esc(gs.menus[i])}" maxlength="60" ${gs.started ? "disabled" : ""} /></label>`).join("")}
    </div>
    <div class="ladder-starts">
      ${state.names
        .slice(0, state.people)
        .map(
          (n, i) =>
            /* HTML */ `<button
              data-ladder-start="${i}"
              ${gs.played.includes(i) || gs.queue.includes(i) ? "disabled" : ""}
            >
              ${esc(n || `참가자 ${i + 1}`)}${gs.played.includes(i) ? " · 완료" : gs.queue.includes(i) ? " · 대기" : ""}
            </button>`,
        )
        .join("")}
    </div>
    <svg
      class="ladder-svg"
      viewBox="0 0 600 240"
      role="img"
      aria-label="${state.people}명 사다리"
    >
      <g stroke="#7890a8" stroke-width="3" fill="none">
        ${Array.from({ length: state.people }, (_, i) => /* HTML */ `<path d="M${x(i)} ${y(0)}V${y(l.rows + 1)}" />`).join("")}${l.rungs.map((r) => /* HTML */ `<path d="M${x(r.col)} ${y(r.row)}H${x(r.col + 1)}" />`).join("")}
      </g>
      <path id="ladder-trace" stroke="#FF641B" stroke-width="5" fill="none" />
      ${Array.from({ length: state.people }, (_, i) => /* HTML */ `<text x="${x(i)}" y="228" text-anchor="middle" fill="#829947" font-size="12">${gs.started ? (i === gs.winningEnd ? "당첨" : "꽝") : "?"}</text>`).join("")}
    </svg>
    <div class="ladder-log" role="status">
      ${gs.log.map(esc).join("<br>") || "아직 출발한 참가자가 없어요."}
    </div>
  </div>`;
}
function queueButtons() {
  for (const e of $$("[data-ladder-start]")) {
    let i = Number(e.dataset.ladderStart);
    e.disabled = gs.played.includes(i) || gs.queue.includes(i);
    e.textContent =
      (state.names[i] || `참가자 ${i + 1}`) +
      (gs.current === i
        ? " · 진행 중"
        : gs.played.includes(i)
          ? " · 완료"
          : gs.queue.includes(i)
            ? " · 대기"
            : "");
  }
}
async function queueLadder(start) {
  if (
    state.game !== "ladder" ||
    state.result ||
    gs.played.includes(start) ||
    gs.queue.includes(start)
  )
    return;
  if (gs.menus.slice(0, state.people).some((v) => !v.trim())) {
    toast("모든 메뉴를 입력해 주세요.");
    return;
  }
  gs.queue.push(start);
  queueButtons();
  if (gs.running) return;
  gs.running = true;
  try {
    if (!gs.started) {
      gs.started = true;
      gs.winningEnd = randomIndex(state.people);
    }
    while (gs.queue.length && !state.result) {
      const next = gs.queue.shift();
      gs.played.push(next);
      gs.current = next;
      renderGame(candidates());
      setBusy(true);
      queueButtons();
      const t = state.ladder.trace(next),
        x = (i) => 45 + (i * 510) / (state.people - 1),
        y = (r) => 25 + (r * 175) / (state.ladder.rows + 1),
        path = $("#ladder-trace");
      path.setAttribute(
        "d",
        t.points.map((v, i) => `${i ? "L" : "M"}${x(v.x)},${y(v.y)}`).join(" "),
      );
      let len = path.getTotalLength();
      path.style.strokeDasharray = len;
      path.style.strokeDashoffset = len;
      path.getBoundingClientRect();
      path.style.transition = "stroke-dashoffset 1.5s linear";
      path.style.strokeDashoffset = 0;
      await delay(1600);
      setBusy(false);
      gs.current = null;
      let won = t.end === gs.winningEnd;
      gs.log.push(
        `${gs.played.length}번째 · ${state.names[next]} · ${gs.menus[next]} → ${won ? "당첨!" : "꽝"}`,
      );
      if (won) {
        gs.queue = [];
        finish(entryResult(gs.menus[next].trim()));
        $("#game-stage").insertAdjacentHTML(
          "beforeend",
          '<div class="ladder-log" role="status">' +
            gs.log.map(esc).join("<br>") +
            "</div>",
        );
        break;
      }
      renderGame(candidates());
    }
  } finally {
    gs.running = false;
    if (state.busy) setBusy(false);
  }
}
function renderResult() {
  const m = state.result;
  if (m.entryOnly) {
    $("#board-status").textContent = "입력값 당첨!";
    $("#game-stage").innerHTML = /* HTML */ `<div class="result-scene">
      <span class="result-kicker">입력값 당첨</span>
      <h3 class="result-title">${esc(m.name)}</h3>
      <p>${esc(m.desc)}</p>
    </div>`;
    $("#game-actions").innerHTML =
      '<button class="secondary" data-action="again">한 번 더</button>';
    return;
  }
  $("#board-status").innerHTML = '<i class="live-dot"></i> LUNCH DECIDED!';
  $("#game-stage").innerHTML = /* HTML */ `<div class="result-scene">
    <div class="confetti">✳ <span>✦</span> ✳</div>
    <span class="result-kicker">TODAY’S LUCKY LUNCH</span>
    <div class="result-emoji">${m.emoji}</div>
    <h3 class="result-title">${esc(m.name)}</h3>
    <p class="result-desc">${esc(m.desc)}</p>
    <div class="result-stats">${menuStats(m)}</div>
    <p class="result-note">
      ✓ 예산 · 시간 · 거리 조건을 모두
      만족해요${state.people > 1 ? /* HTML */ `<br />${state.people}명이 함께 먹을 오늘의 공통 메뉴!` : ""}
    </p>
  </div>`;
  $("#game-actions").innerHTML =
    '<button class="secondary" data-action="again">↻ 한 번 더</button><button class="primary" data-action="find">이 메뉴로 식당 찾기 ↗</button>';
  $("#game-footnote").textContent =
    "메뉴가 마음에 들면, 근처 식당을 골라보세요.";
}
async function play(source) {
  if (state.busy) return;
  if (state.mode === "group" && state.game === "roulette") {
    const entries = gs.entries.slice(0, state.people).map((v) => v.trim());
    if (entries.some((v) => !v)) {
      toast("입력값을 모두 채워주세요.");
      return;
    }
    const i = randomIndex(entries.length);
    setBusy(true);
    try {
      $(".roulette-wheel").style.transform =
        `rotate(${360 * 5 + 360 - ((i + 0.5) * 360) / entries.length}deg)`;
      await delay(2100);
      finish(entryResult(entries[i]));
    } finally {
      setBusy(false);
    }
    return;
  }
  const pool = candidates();
  if (!pool.length) {
    toast("먼저 추천 조건을 조금 넓혀주세요.");
    return;
  }
  if (state.game === "random") {
    state.game = ["draw", "gacha", "ticket"][randomIndex(3)];
    renderGame(pool);
    toast(`${games[state.game].name} 당첨! 이 게임으로 골라볼까요?`);
    return;
  }
  const m = pickMenu(pool, state.previous);
  setBusy(true);
  try {
    if (state.game === "gacha") {
      $(".gacha-machine")?.classList.add("spinning");
      await delay(1250);
      state.pending = m;
      renderGame(pool);
      return;
    }
    if (state.game === "roulette") {
      const idx = pool.findIndex((x) => x.id === m.id);
      const angle = 360 * 5 + 360 - ((idx + 0.5) * 360) / pool.length;
      $(".roulette-wheel").style.transform = `rotate(${angle}deg)`;
      await delay(2050);
    } else if (state.game === "ladder") {
      const l = state.ladder,
        t = l.trace(state.ladderStart),
        x = (i) => 45 + (i * 510) / (state.people - 1),
        y = (r) => 25 + (r * 175) / (l.rows + 1);
      const p = $("#ladder-trace");
      p.setAttribute(
        "d",
        t.points.map((v, i) => `${i ? "L" : "M"}${x(v.x)},${y(v.y)}`).join(" "),
      );
      const len = p.getTotalLength();
      p.style.strokeDasharray = len;
      p.style.strokeDashoffset = len;
      p.getBoundingClientRect();
      p.style.transition = "stroke-dashoffset 1.7s ease";
      p.style.strokeDashoffset = 0;
      const labels = Array.from({ length: state.people }, (_, i) =>
        i === t.end ? m : pool[randomIndex(pool.length)],
      );
      $$(".ladder-svg text").forEach((e, i) => {
        e.textContent = labels[i].name;
        e.style.fill = i === t.end ? "#C5FF24" : "#a6b7ca";
        e.style.fontSize = "11px";
      });
      await delay(2100);
    } else {
      source?.classList.add("flipping");
      await delay(650);
    }
    finish(m);
  } finally {
    setBusy(false);
  }
}
function finish(m) {
  resetRestaurantDraw();
  state.result = m;
  state.pending = null;
  state.previous = m.id;
  state.selectedRestaurant = 0;
  state.route = false;
  renderGame(candidates());
}
function renderSuggestions(pool) {
  $("#suggestion-grid").innerHTML =
    pool
      .slice(0, 3)
      .map(
        (m, i) =>
          /* HTML */ `<article class="suggestion-card">
            <button
              class="save-btn ${state.favorites.includes(m.id) ? "saved" : ""}"
              data-save="${m.id}"
              aria-label="${esc(m.name)} ${state.favorites.includes(m.id) ? "찜 해제" : "찜하기"}"
            >
              ${state.favorites.includes(m.id) ? "♥" : "♡"}</button
            ><button
              class="food-art art-${i}"
              data-detail="${m.id}"
              aria-label="${esc(m.name)} 자세히 보기"
            >
              <span>${m.emoji}</span><small>${esc(m.category)} PICKS</small>
            </button>
            <div class="suggestion-content">
              <span class="menu-category"
                >${esc(m.category)} <i>·</i> 오늘의 후보</span
              >
              <h3>
                <button data-detail="${m.id}">
                  ${esc(m.name)} <span>↗</span>
                </button>
              </h3>
              <p>${esc(m.desc)}</p>
              <div class="menu-meta">${menuStats(m)}</div>
            </div>
          </article>`,
      )
      .join("") ||
    '<div class="empty-state"><p>조건을 바꾸면 새로운 메뉴가 나타나요.</p></div>';
}
function renderAI() {
  const pool = candidates();
  if (state.aiReady) {
    $("#game-stage").innerHTML = /* HTML */ `<div class="ai-draw-ready">
      <span class="ai-symbol">✦</span
      ><span class="result-kicker">STEP 01 · CANDIDATES READY</span>
      <h3>후보는 모았어요. 최종 선택은 운명에게!</h3>
      <p>
        AI 조건 해석 데모가 취향에 맞는 메뉴 ${pool.length}개를 모았어요.<br />이
        중 한 메뉴를 같은 확률로 뽑아요.
      </p>
      <div class="ai-ready-pool">
        ${pool.map((m) => /* HTML */ `<span class="ai-ready-menu">${m.emoji} ${esc(m.name)}</span>`).join("")}
      </div>
      <div class="ai-candidate-summary">
        <span class="ai-candidate-count"
          >각 메뉴 당첨 확률 1/${pool.length}</span
        >
        <p>
          ${esc(state.aiNotes.join(" · ") || "현재 설정한 조건을 사용했어요.")}
        </p>
      </div>
      <p class="ai-note">
        생성형 AI 미연결 · 문장의 조건을 규칙으로 해석한 시연이에요.
      </p>
    </div>`;
    $("#game-actions").innerHTML =
      '<button class="secondary" data-action="edit-ai">조건 다시 적기</button><button class="primary play-cta" data-action="draw-ai-menu">⚄ 메뉴 랜덤 추첨 ↗</button>';
    $("#game-footnote").textContent =
      "메뉴를 뽑은 다음, 그 메뉴를 파는 CSV 식당도 한 번 더 뽑아요.";
    return;
  }
  $("#game-stage").innerHTML = /* HTML */ `<div class="ai-panel">
    <span class="ai-symbol">✦</span>
    <h3>취향에 맞는 후보부터 모아볼까요?</h3>
    <p>AI는 후보를 모으고, 랜덤 게임은 최종 결정을 도와요.</p>
    <label class="sr-only" for="ai-prompt">원하는 점심 조건</label
    ><textarea
      id="ai-prompt"
      class="field"
      rows="3"
      maxlength="300"
      placeholder="예: 1만원 이하 한식, 40분 안에 다녀올 수 있는 곳"
    >
${esc(state.aiPrompt)}</textarea>
    <div class="prompt-chips">
      <button data-prompt="1만원 이하 한식, 40분 안에">
        🍚 가성비 좋은 한식</button
      ><button data-prompt="30분 안에 12000원 이하 분식">
        ⚡ 빠르고 간편하게</button
      ><button data-prompt="15000원 이하 양식, 60분 안에">
        🍝 여유로운 점심
      </button>
    </div>
    <p class="ai-note">
      DEMO · 문장의 예산·시간·거리·카테고리를 규칙으로 해석해요.<br />생성형
      AI·날씨·컨디션 분석은 아직 연결하지 않았어요.
    </p>
  </div>`;
  $("#game-actions").innerHTML =
    '<button class="primary play-cta" data-action="ai">✦ AI 메뉴 후보 모으기 <span>↗</span></button>';
  $("#game-footnote").textContent =
    "후보 확인 → 메뉴 추첨 → CSV 식당 추첨 → 동선 확인";
}
function aiRecommend() {
  const text = $("#ai-prompt").value.trim();
  if (!text) {
    toast("원하는 점심을 한 문장으로 적어주세요.");
    $("#ai-prompt").focus();
    return;
  }
  const { filters, notes } = parsePrompt(text, state);
  Object.assign(state, filters);
  persist();
  state.time = Math.max(10, Math.min(90, Math.round(state.time / 5) * 5));
  state.distance = Math.max(
    100,
    Math.min(1000, Math.round(state.distance / 100) * 100),
  );
  conditionsChanged();
  state.aiPrompt = text;
  state.aiNotes = notes;
  state.aiReady = candidates().length > 0;
  renderGame(candidates());
  toast(
    state.aiReady
      ? "조건에 맞는 후보를 모았어요. 이제 메뉴를 뽑아보세요!"
      : "이 조건에 맞는 메뉴가 없어요. 조건을 넓혀주세요.",
  );
}
async function drawAiMenu() {
  const pool = Object.freeze(candidates().slice());
  if (state.busy || !state.aiReady || !pool.length) return;
  const chosen = pool[randomIndex(pool.length)];
  setBusy(true);
  try {
    await delay(900);
    finish(chosen);
    toast("메뉴 결정! 이제 이 메뉴를 파는 식당을 뽑아보세요.");
  } finally {
    setBusy(false);
  }
}

function switchView(view) {
  if (state.busy) return;
  state.view = view;
  $$(".view").forEach((e) => (e.hidden = e.id !== `view-${view}`));
  $$(".nav-item").forEach((e) =>
    e.classList.toggle("active", e.dataset.view === view),
  );
  $$(".progress-step").forEach((e) =>
    e.classList.toggle(
      "active",
      Number(e.dataset.step) ===
        (view === "restaurants" ? (state.route ? 3 : 2) : 1),
    ),
  );
  if (view === "restaurants") renderRestaurants();
  if (view === "saved") renderSaved();
  updateShell();
}
function restaurants() {
  if (!state.result) return [];
  if (state.restaurantCandidates) return state.restaurantCandidates;
  state.restaurantCandidates = Object.freeze([
    ...new Map(
      state.result.offers
        .slice()
        .sort((a, b) => a.price - b.price)
        .map((o) => [
          o.id,
          Object.freeze({
            ...o,
            meal: state.result.meal,
            wait: state.result.wait,
            menu: state.result.name,
            emoji: state.result.emoji,
          }),
        ]),
    ).values(),
  ]);
  return state.restaurantCandidates;
}
function restaurantDrawPanel(rs) {
  const selected = rs[state.selectedRestaurant],
    done = state.restaurantDrawDone;
  return /* HTML */ `<section
    class="restaurant-draw-panel ${state.restaurantDrawing ? "is-drawing" : ""}"
    aria-labelledby="restaurant-draw-title"
  >
    <div class="restaurant-draw-heading">
      <span class="draw-step-label">STEP 02 · RESTAURANT DRAW</span>
      <h2 id="restaurant-draw-title">메뉴는 그대로, 식당도 운명에게!</h2>
      <p>
        ${state.result.emoji} ${esc(state.result.name)}을 파는 CSV 식당
        ${rs.length}곳. A부터 차례로 불이 켜지고, 점점 느려지다 한 곳에 멈춰요.
      </p>
    </div>
    <div class="restaurant-draw-candidates">
      ${rs.map((r, i) => /* HTML */ `<button class="draw-restaurant ${done && i === state.selectedRestaurant ? "is-winner" : ""}" data-restaurant="${i}" aria-label="${i < 26 ? String.fromCharCode(65 + i) : String(i + 1)} 후보 ${esc(r.name)} 선택" aria-pressed="${done && i === state.selectedRestaurant}"><span class="draw-letter">${i < 26 ? String.fromCharCode(65 + i) : String(i + 1)}</span><strong class="draw-place-name">${esc(r.name)}</strong><span class="draw-place-meta">${won(r.price)}원 · 도보 ${Math.ceil(r.distance / 70)}분</span><span class="draw-winner-tag">${done && i === state.selectedRestaurant ? "당첨! 오늘의 목적지" : "당첨 확률 1/" + rs.length}</span></button>`).join("")}
    </div>
    <div class="restaurant-draw-footer">
      <p class="restaurant-draw-status" role="status" aria-live="polite">
        ${state.restaurantDrawing ? "후보 목록을 고정했어요. 불빛이 멈출 곳을 기다려주세요." : done && selected ? String.fromCharCode(65 + state.selectedRestaurant) + " · " + esc(selected.name) + " 당첨! 메뉴는 " + esc(state.result.name) + " 그대로예요." : rs.length === 1 ? "조건에 맞는 식당이 1곳이에요. 추첨으로 이 식당을 확정해요." : "모든 후보에 같은 당첨 기회를! 마음에 들 때까지 식당만 다시 뽑을 수 있어요."}
      </p>
      <button
        class="primary"
        data-action="random-restaurant"
        ${!rs.length || state.restaurantDrawing ? "disabled" : ""}
      >
        ${state.restaurantDrawing ? "식당 추첨 중…" : done ? "↻ 한 번 더! 식당만 다시 뽑기" : "⚄ 식당 랜덤 추첨"}
        <span>↗</span>
      </button>
    </div>
    <p class="restaurant-draw-note micro">
      추첨 중 조건·후보 고정 · 재추첨도 모든 후보 1/${rs.length || 1} · 직전
      식당이 다시 나올 수 있어요.
    </p>
  </section>`;
}
function renderRestaurants() {
  updateProgress();
  const host = $("#view-restaurants");
  host.setAttribute("aria-busy", String(state.restaurantDrawing));
  if (!state.result) {
    host.innerHTML =
      '<div class="view-heading"><span class="section-index">02 / FIND YOUR PLACE</span><h1>맛있는 목적지를 찾아요</h1><p>메뉴를 먼저 고르면, 그 메뉴를 파는 식당을 보여드려요.</p></div><div class="empty-state large-empty"><span>⌖</span><h2>오늘의 메뉴부터 정해볼까요?</h2><p>AI 후보에서 메뉴를 뽑거나, 게임으로 직접 결정해 보세요.</p><button class="primary" data-action="back-game">메뉴 고르러 가기 ↗</button></div>';
    return;
  }
  const m = state.result,
    rs = restaurants();
  if (state.selectedRestaurant >= rs.length) state.selectedRestaurant = 0;
  const selected = rs[state.selectedRestaurant];
  host.innerHTML = /* HTML */ `<div class="view-heading">
      <span class="section-index">TWO PICKS, ONE LUNCH · 02</span>
      <h1>메뉴는 <span>${esc(m.name)}</span>, 식당도 뽑아볼까요?</h1>
      <p>메뉴 추첨 완료 → 주변 CSV 식당 확인 → 식당 추첨 → 동선 확인</p>
    </div>
    <div class="restaurant-toolbar">
      <span class="result-pill">${m.emoji} ${esc(m.name)}</span
      ><span
        >예산 ${won(state.budget)}원 · ${state.time}분 · ${state.people}명</span
      ><button class="secondary" data-action="back-game">
        메뉴 다시 고르기 ↻
      </button>
    </div>
    <div class="demo-notice">
      ⓘ 식당·메뉴·가격은 업로드 CSV 기준입니다. 거리는 직선거리이며
      지도·소요시간은 추정입니다.
    </div>
    ${rs.length ? restaurantDrawPanel(rs) : '<div class="empty-state"><h2>조건에 맞는 식당이 없어요</h2><p>메뉴를 바꾸거나 추천 조건을 넓혀주세요.</p></div>'}
    <div class="restaurant-layout">
      <div class="restaurant-list">
        <div class="restaurant-list-title">
          <h3>주변 식당 <span>${rs.length}</span></h3>
          <span class="micro">목록과 지도에서 직접 선택도 가능해요</span>
        </div>
        ${rs
          .map(
            (r, i) =>
              /* HTML */ `<button
                class="restaurant-card ${!state.restaurantDrawing && i === state.selectedRestaurant ? "active" : ""}"
                data-restaurant="${i}"
              >
                <span class="restaurant-emoji">${r.emoji}</span>
                <div class="restaurant-info">
                  <small
                    >${i < 26 ? String.fromCharCode(65 + i) : String(i + 1)} ·
                    CSV 식당 · ${esc(m.category)}</small
                  >
                  <h3>${esc(r.name)}</h3>
                  <p>대표 메뉴 ${esc(r.menu)}</p>
                  <div class="restaurant-meta">
                    <span>${won(r.price)}원</span
                    ><span
                      >${r.distance}m · 도보
                      ${Math.ceil(r.distance / 70)}분</span
                    >
                  </div>
                </div>
                <span class="restaurant-check"
                  >${!state.restaurantDrawing && i === state.selectedRestaurant ? "✓" : "↗"}</span
                >
              </button>`,
          )
          .join("")}
      </div>
      <div class="map-panel">
        ${mapArt(rs)}<span class="map-label"
          >⌖ ${esc(state.location)} 주변 · 예시 지도</span
        >
        <div class="map-legend">
          <span>● 출발 위치</span><span>● 선택한 식당</span>
        </div>
      </div>
    </div>
    ${selected ? routePanel(selected) : ""}`;
}
const restaurantMarkers = [
  [425, 167],
  [225, 135],
  [455, 315],
  [145, 325],
  [535, 95],
];
function mapArt(rs) {
  const markers = rs.map(
    (r, i) =>
      restaurantMarkers[i] || [
        80 + (i % 6) * 95,
        80 + (Math.floor(i / 6) % 3) * 115,
      ],
  );
  return /* HTML */ `<svg
    class="demo-map"
    viewBox="0 0 650 430"
    role="group"
    aria-label="CSV 식당 ${rs.length}곳과 출발점이 표시된 지도"
  >
    <defs>
      <pattern
        id="map-grid"
        width="110"
        height="95"
        patternUnits="userSpaceOnUse"
      >
        <rect
          x="10"
          y="10"
          width="86"
          height="71"
          rx="10"
          fill="#20334a"
          stroke="#2b4059"
        />
      </pattern>
    </defs>
    <rect width="650" height="430" fill="#142138" />
    <rect width="650" height="430" fill="url(#map-grid)" />
    <path d="M-20 330L680 110" stroke="#3a5166" stroke-width="37" />
    <path
      d="M-20 330L680 110"
      stroke="#a0aa75"
      stroke-width="1.5"
      stroke-dasharray="8 9"
      opacity=".5"
    />
    <path d="M320 -10V440M-10 225H660" stroke="#3a5166" stroke-width="20" />
    <rect x="32" y="29" width="142" height="90" rx="25" fill="#233e3d" />
    <text x="103" y="79" fill="#69978c" text-anchor="middle" font-size="13">
      작은 공원
    </text>
    <text x="337" y="75" fill="#7b91aa" font-size="13">
      ${esc(state.location)} · 예시
    </text>
    <text x="65" y="249" fill="#7b91aa" font-size="13">점심 산책길</text>
    ${state.route ? /* HTML */ `<path d="M320 280V225H${markers[state.selectedRestaurant][0]}V${markers[state.selectedRestaurant][1]}" stroke="#C5FF24" stroke-width="5" stroke-linejoin="round" fill="none" stroke-dasharray="8 4" />` : ""}
    <circle cx="320" cy="280" r="22" fill="#6c9dff" opacity=".15" />
    <circle
      cx="320"
      cy="280"
      r="8"
      fill="#6c9dff"
      stroke="#e7f0ff"
      stroke-width="3"
    />
    <rect x="277" y="300" width="86" height="27" rx="13" fill="#0c1426" />
    <text x="320" y="318" text-anchor="middle" fill="#d5e4f8" font-size="12">
      출발 위치
    </text>
    ${rs.map((r, i) => /* HTML */ `<g data-map-marker="${i}" class="map-marker" role="button" tabindex="${state.restaurantDrawing ? "-1" : "0"}" aria-disabled="${state.restaurantDrawing}" aria-label="${i < 26 ? String.fromCharCode(65 + i) : String(i + 1)} ${esc(r.name)} 선택"><circle cx="${markers[i][0]}" cy="${markers[i][1]}" r="${!state.restaurantDrawing && state.selectedRestaurant === i ? 26 : 21}" fill="${!state.restaurantDrawing && state.selectedRestaurant === i ? "#C5FF24" : "#FF641B"}" stroke="#0c1426" stroke-width="4" /><text x="${markers[i][0]}" y="${markers[i][1] + 6}" text-anchor="middle" fill="#142138" font-size="17" font-weight="800">${i < 26 ? String.fromCharCode(65 + i) : String(i + 1)}</text></g>`).join("")}
  </svg>`;
}
function routePanel(r) {
  const walk = Math.ceil(r.distance / 70),
    sum = walk * 2 + r.wait + r.meal;
  return /* HTML */ `<section class="route-panel">
    <div class="route-summary">
      <span class="section-index"
        >${state.route ? "03 / READY, SET, LUNCH!" : "YOUR NEXT LUNCH STOP"}</span
      >
      <h2>
        ${esc(r.name)}${state.route ? "으로 출발해요!" : "이 마음에 드나요?"}
      </h2>
      <p>
        ${state.route ? "도보 왕복과 대기·식사를 포함한 시연용 예상 일정이에요." : "식당을 뽑거나 직접 골랐다면 예상 점심 동선을 확인해 보세요."}
      </p>
    </div>
    <div class="route-stats">
      <div>
        <small>편도 거리</small><strong>${r.distance}<em>m</em></strong>
      </div>
      <div>
        <small>편도 도보</small><strong>${walk}<em>분</em></strong>
      </div>
      <div>
        <small>총 예상 시간</small><strong>${sum}<em>분</em></strong>
      </div>
      <div>
        <small>남는 휴식</small><strong>${state.time - sum}<em>분</em></strong>
      </div>
    </div>
    ${
      state.route
        ? /* HTML */ `<div class="route-steps">
            <span>출발<br /><b>${esc(state.location)}</b></span
            ><i>도보 ${walk}분 →</i
            ><span>점심<br /><b>대기 ${r.wait} + 식사 ${r.meal}분</b></span
            ><i>도보 ${walk}분 →</i
            ><span>복귀<br /><b>여유 ${state.time - sum}분</b></span>
          </div>`
        : ""
    }
    <div class="route-actions">
      <button class="secondary" data-save="${state.result.id}">
        ${state.favorites.includes(state.result.id) ? "♥ 찜한 메뉴" : "♡ 이 메뉴 찜하기"}</button
      >${state.route ? /* HTML */ `<a class="primary" href="https://map.kakao.com/?q=${encodeURIComponent(r.name + " " + (r.address || state.location))}" target="_blank" rel="noopener noreferrer">카카오맵에서 실제 식당 찾기 ↗</a>` : '<button class="primary" data-action="route">이 식당으로 결정 · 동선 보기 ↗</button>'}
    </div>
  </section>`;
}
function lightRestaurant(index) {
  state.restaurantSpotlight = index;
  $$("[data-restaurant]").forEach((e) =>
    e.classList.toggle("is-lit", Number(e.dataset.restaurant) === index),
  );
  $$("[data-map-marker]").forEach((e) =>
    e.classList.toggle("is-lit", Number(e.dataset.mapMarker) === index),
  );
}
async function drawRestaurant() {
  if (state.busy) return;
  const pool = restaurants();
  if (!pool.length) {
    toast("먼저 메뉴를 고르거나 조건을 넓혀주세요.");
    return;
  }
  const chosen = randomIndex(pool.length),
    plan = createSpotlightPlan(pool.length, chosen);
  state.restaurantDrawing = true;
  state.restaurantDrawDone = false;
  state.route = false;
  state.restaurantSpotlight = -1;
  renderRestaurants();
  setBusy(true);
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  try {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      $(".restaurant-draw-status").textContent =
        "후보를 고정했어요. 움직임 없이 5초 뒤 결과를 보여드려요.";
      await wait(5000);
    } else {
      for (const step of plan) {
        lightRestaurant(step.index);
        await wait(step.delayMs);
      }
    }
    state.selectedRestaurant = chosen;
    state.restaurantDrawDone = true;
    state.restaurantSpotlight = chosen;
  } finally {
    state.restaurantDrawing = false;
    setBusy(false);
    renderRestaurants();
  }
}

function renderSaved() {
  const saved = MENUS.filter((m) => state.favorites.includes(m.id)),
    blocked = MENUS.filter((m) => state.blacklist.includes(m.id));
  $("#view-saved").innerHTML = /* HTML */ `<div class="view-heading">
      <span class="section-index">MY LUNCH TASTE</span>
      <h1>취향을 알면, 점심이 쉬워져요.</h1>
      <p>
        이 브라우저에 저장한 찜과 제외 메뉴예요. 실제 계정과 동기화되지 않아요.
      </p>
    </div>
    <div class="saved-section">
      <h2>♡ 찜한 메뉴 <span>${saved.length}</span></h2>
      <div class="saved-grid">
        ${saved.map((m) => savedCard(m, false)).join("") || '<div class="empty-state"><h3>아직 찜한 메뉴가 없어요</h3><p>메뉴 카드의 하트를 눌러 취향을 모아보세요.</p><button class="secondary" data-action="back-game">메뉴 둘러보기 ↗</button></div>'}
      </div>
    </div>
    <div class="saved-section">
      <h2>⊘ 추천에서 제외 <span>${blocked.length}</span></h2>
      <p class="micro">여기에 있는 메뉴는 모든 게임과 빠른 추천에서 빠져요.</p>
      <div class="saved-grid">
        ${blocked.map((m) => savedCard(m, true)).join("") || '<div class="empty-state"><p>제외한 메뉴가 없어요. 메뉴 상세에서 설정할 수 있어요.</p></div>'}
      </div>
    </div>`;
}
function savedCard(m, blocked) {
  return /* HTML */ `<article class="saved-card">
    <span>${m.emoji}</span>
    <div>
      <small>${esc(m.category)}</small>
      <h3>${esc(m.name)}</h3>
      <p>${won(m.price)}원 · 총 ${total(m)}분</p>
    </div>
    <button class="secondary" ${blocked ? "data-block" : "data-save"}="${m.id}">
      ${blocked ? "제외 해제" : "찜 해제"}
    </button>
  </article>`;
}
function toggleSaved(id) {
  state.favorites = state.favorites.includes(id)
    ? state.favorites.filter((x) => x !== id)
    : [...state.favorites, id];
  persist();
  render();
  toast(
    state.favorites.includes(id)
      ? "나의 취향에 저장했어요."
      : "찜한 메뉴에서 해제했어요.",
  );
}
function detail(id) {
  const m =
    candidates().find((x) => String(x.id) === String(id)) ||
    MENUS.find((x) => String(x.id) === String(id));
  if (!m) return;
  const eligible = candidates().some((x) => x.id === m.id);
  openDialog(
    /* HTML */ `<div class="dialog-body menu-detail">
      <span class="detail-emoji">${m.emoji}</span
      ><span class="section-index">${esc(m.category)} · MENU DETAIL</span>
      <h2 id="dialog-title">${esc(m.name)}</h2>
      <p>${esc(m.desc)}</p>
      <div class="result-stats">${menuStats(m)}</div>
      <p class="micro">
        식사 ${m.meal}분 + 대기 ${m.wait}분 + 왕복 도보
        ${Math.ceil(m.distance / 70) * 2}분<br />예시 가격·시간이며, 재료와 영업
        정보는 실제 식당에 확인해 주세요.
      </p>
      <div class="dialog-actions">
        <button class="secondary" data-save="${m.id}">
          ${state.favorites.includes(m.id) ? "♥ 찜 해제" : "♡ 찜하기"}</button
        ><button class="secondary" data-block="${m.id}">
          ${state.blacklist.includes(m.id) ? "제외 해제" : "⊘ 추천에서 제외"}</button
        ><button
          class="primary"
          data-choose="${m.id}"
          ${!eligible ? "disabled" : ""}
        >
          ${eligible ? "이 메뉴로 선택 ↗" : "현재 추천 조건 밖이에요"}
        </button>
      </div>
    </div>`,
  );
}
function openDialog(html) {
  $("#dialog-content").innerHTML = html;
  if (!$("#app-dialog").open) $("#app-dialog").showModal();
}
function profileDialog() {
  window.LunchRunProfile.open({
    onChange(name) {
      state.profile = name;
      state.names[0] = name || "나";
      persist();
      render();
      toast(
        name
          ? `${name}님, 오늘도 맛있는 점심 되세요!`
          : "게스트 모드로 전환했어요. 취향은 이 브라우저에 유지돼요.",
      );
    },
  });
}

$("#profile-btn").addEventListener("click", profileDialog);
$("#close-dialog").addEventListener("click", () => $("#app-dialog").close());
$("#app-dialog").addEventListener("click", (e) => {
  if (e.target === $("#app-dialog")) $("#app-dialog").close();
});
document.addEventListener("input", (e) => {
  if (e.target.dataset.entry !== undefined) {
    gs.entries[Number(e.target.dataset.entry)] = e.target.value;
    const wheel = $(".wheel-scene");
    if (wheel)
      wheel.outerHTML = wheelArt(
        gs.entries.slice(0, state.people).map((name) => ({ name })),
      );
  }
  if (e.target.dataset.ladderMenu !== undefined && !gs.started)
    gs.menus[Number(e.target.dataset.ladderMenu)] = e.target.value;
  if (e.target.dataset.name !== undefined)
    state.names[Number(e.target.dataset.name)] = e.target.value;
});
document.addEventListener("keydown", (e) => {
  if (state.busy) return;
  const marker = e.target.closest("[data-map-marker]");
  if (marker && ["Enter", " "].includes(e.key)) {
    e.preventDefault();
    state.selectedRestaurant = Number(marker.dataset.mapMarker);
    state.restaurantDrawDone = false;
    state.route = false;
    renderRestaurants();
  }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button,[data-map-marker]");
  if (!b || b.disabled) return;
  if (b.dataset.ladderStart !== undefined) {
    queueLadder(Number(b.dataset.ladderStart));
    return;
  }
  if (state.busy) return;
  const d = b.dataset;
  if (d.view) {
    switchView(d.view);
    updateShell();
    return;
  }
  if (d.time) {
    state.time = Number(d.time);
    conditionsChanged();
    return;
  }
  if (d.category) {
    const c = d.category;
    state.categories =
      c === "전체"
        ? []
        : state.categories.includes(c)
          ? state.categories.filter((x) => x !== c)
          : [...state.categories, c];
    conditionsChanged();
    return;
  }
  if (d.mode) {
    resetRound();
    state.mode = d.mode;
    state.game = d.mode === "group" ? "roulette" : "gacha";
    if (d.mode === "group" && state.people < 2) state.people = 2;
    if (d.mode === "solo") state.people = 1;
    state.ladderStart = 0;
    conditionsChanged();
    navigateGameScreen(d.mode === "ai" ? "play" : "select");
    return;
  }
  if (d.game) {
    resetRound();
    state.game = d.game;
    if (d.game === "ladder" && state.people > 8) {
      state.people = 8;
      toast("사다리는 최대 8명이 함께할 수 있어요.");
    }
    state.result = null;
    state.pending = null;
    state.ladder = null;
    state.ladderStart = 0;
    renderGame(candidates());
    navigateGameScreen("play");
    return;
  }
  if (b.id === "people-plus" || b.id === "people-minus") {
    const max = state.game === "ladder" && state.mode === "group" ? 8 : 12;
    const next = state.people + (b.id === "people-plus" ? 1 : -1);
    if (next > max) {
      toast(`이 게임은 최대 ${max}명까지 참여할 수 있어요.`);
      return;
    }
    resetRound();
    state.people = Math.max(1, Math.min(max, next));
    if (state.people > 1 && state.mode !== "group") {
      state.mode = "group";
      state.game = "roulette";
    }
    if (state.people === 1 && state.mode !== "solo") {
      state.mode = "solo";
      state.game = "gacha";
    }
    state.ladderStart = 0;
    conditionsChanged();
    navigateGameScreen("select");
    return;
  }
  if (d.ladderStart !== undefined) {
    state.ladderStart = Number(d.ladderStart);
    renderGame(candidates());
    return;
  }
  if (d.draw !== undefined || d.ticket !== undefined) {
    await play(b);
    return;
  }
  if (d.prompt) {
    $("#ai-prompt").value = d.prompt;
    return;
  }
  if (d.save !== undefined) {
    const m = MENUS.find((x) => String(x.id) === d.save);
    if (m) toggleSaved(m.id);
    if ($("#app-dialog").open) $("#app-dialog").close();
    return;
  }
  if (d.block !== undefined) {
    const m = MENUS.find((x) => String(x.id) === d.block);
    if (!m) return;
    state.blacklist = state.blacklist.includes(m.id)
      ? state.blacklist.filter((x) => x !== m.id)
      : [...state.blacklist, m.id];
    persist();
    $("#app-dialog").close();
    conditionsChanged();
    toast("추천 제외 설정을 반영했어요.");
    return;
  }
  if (d.detail !== undefined) {
    detail(d.detail);
    return;
  }
  if (d.choose !== undefined) {
    const m = candidates().find((x) => String(x.id) === d.choose);
    if (m) {
      finish(m);
      $("#app-dialog").close();
      switchView("restaurants");
    }
    return;
  }
  if (d.restaurant !== undefined || d.mapMarker !== undefined) {
    state.selectedRestaurant = Number(d.restaurant ?? d.mapMarker);
    state.restaurantDrawDone = false;
    state.route = false;
    renderRestaurants();
    return;
  }
  const action = d.action;
  if (b.id === "reset-filters" || action === "reset") {
    Object.assign(state, {
      budget: 12000,
      time: 45,
      distance: 500,
      categories: [],
    });
    conditionsChanged();
    toast("추천 조건을 초기화했어요.");
  }
  if (b.id === "all-menus") {
    openDialog(
      /* HTML */ `<div class="dialog-body">
        <span class="section-index">TODAY’S MENU POOL</span>
        <h2 id="dialog-title">조건에 맞는 모든 메뉴</h2>
        <div class="all-menu-grid">
          ${
            candidates()
              .map(
                (m) =>
                  /* HTML */ `<button class="menu-chip" data-detail="${m.id}">
                    <span>${m.emoji}</span><span>${esc(m.name)}</span
                    ><small>${won(m.price)}원</small>
                  </button>`,
              )
              .join("") || "<p>조건에 맞는 메뉴가 없어요.</p>"
          }
        </div>
      </div>`,
    );
  }
  if (action === "play") await play(b);
  if (action === "open-capsule" && state.pending) finish(state.pending);
  if (action === "reset-ladder") {
    resetRound();
    renderGame(candidates());
  }
  if (action === "again") {
    resetRound();
    state.result = null;
    state.pending = null;
    state.ladder = null;
    renderGame(candidates());
  }
  if (action === "find") {
    switchView("restaurants");
    updateShell();
  }
  if (action === "back-game") {
    switchView("game");
    updateShell();
  }
  if (action === "ai") aiRecommend();
  if (action === "edit-ai") {
    state.aiReady = false;
    renderGame(candidates());
  }
  if (action === "draw-ai-menu") await drawAiMenu();
  if (action === "route") {
    state.route = true;
    renderRestaurants();
    $$(".progress-step").forEach((x) =>
      x.classList.toggle("active", x.dataset.step === "3"),
    );
  }
  if (action === "random-restaurant") await drawRestaurant();
});

// Game selection and play have separate screens, with browser Back support.
function navigateGameScreen(screen) {
  if (screen === "select" && state.mode === "ai") {
    state.mode = state.people > 1 ? "group" : "solo";
    state.game = state.people > 1 ? "roulette" : "gacha";
    conditionsChanged();
  }
  state.gameScreen = screen;
  if (state.view !== "game") switchView("game");
  const hash = screen === "play" ? "#play" : "#games";
  if (location.hash !== hash) history.pushState(null, "", hash);
  updateShell();
  window.scrollTo({ top: 0, behavior: "instant" });
  $("#game-page-title").focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => {
  if (!["", "#games", "#play"].includes(location.hash)) return;
  state.gameScreen = location.hash === "#play" ? "play" : "select";
  if (state.view !== "game") switchView("game");
  updateShell();
});

// Page shell: shared condition summary and navigation around the game engine.
function updateShell() {
  document.body.dataset.gameScreen = state.gameScreen;
  const screenKey = [
    state.view,
    state.gameScreen,
    state.mode,
    state.game,
    state.route,
    state.result?.id ?? "unselected",
  ].join(":");
  window.LunchRunMotion?.enter($("#view-" + state.view), screenKey);
  const title =
    state.mode === "group"
      ? "함께 먹을 메뉴를 골라요"
      : state.mode === "ai"
        ? "지금 나에게 맞는 메뉴"
        : "혼자서 가볍게 골라요";
  $("#game-page-title").textContent =
    state.gameScreen === "play" && state.mode !== "ai"
      ? games[state.game].name
      : title;
  $("#conditions-summary").textContent = [
    `${won(state.budget)}원`,
    `${state.time}분 남음`,
    `${state.distance}m`,
    `${state.people}명`,
    state.categories.join(" · ") || "전체",
  ].join(" / ");
  const stage =
    state.view === "restaurants"
      ? state.route
        ? "route"
        : "restaurants"
      : state.mode === "ai"
        ? "ai"
        : "game";
  $$(".stage-dock button").forEach((button) => {
    const active = button.dataset.shell === stage;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-shell]");
  if (!button || state.busy) return;
  const action = button.dataset.shell;
  if (action === "home") {
    location.assign("/");
    return;
  }
  if (action === "ai") {
    location.assign("/#ai");
    return;
  }
  if (action === "conditions") {
    openLocationSettings();
    return;
  }
  if (action === "game" || action === "game-selection") {
    navigateGameScreen("select");
    return;
  }
  if (action === "restaurants" || action === "route") {
    if (!state.result || state.result.entryOnly) {
      toast("게임에서 메뉴를 먼저 결정해주세요.");
      return;
    }
    if (action === "route" && !state.restaurantDrawDone) {
      toast(
        "식당 선택 화면에서 식당을 추첨하거나 경로 확인 버튼을 눌러주세요.",
      );
      return;
    }
    state.route = action === "route";
    switchView("restaurants");
  }
  updateShell();
});

const savedLocation = window.LunchRunLocation.read();
if (
  savedLocation &&
  (!launch.settings.origin ||
    (state.origin?.[0] === savedLocation.latitude &&
      state.origin?.[1] === savedLocation.longitude))
) {
  state.location = savedLocation.name;
  state.origin = [savedLocation.latitude, savedLocation.longitude];
}
updateProfile();
render();
if (launch.warning) toast(launch.warning);
