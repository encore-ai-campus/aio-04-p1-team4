// Shared guest/nickname popup. A nickname does not create a member account.
window.LunchRunProfile = (() => {
  const storageKey = "lunchrun-demo2";
  let temporaryProfile = null;

  function readPreferences() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey));
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
    } catch {
      return {};
    }
  }

  function readName() {
    const value = temporaryProfile ?? readPreferences().profile;
    return typeof value === "string" ? value : "";
  }

  function updateHeader(name = readName()) {
    document
      .querySelectorAll(".site-header .profile-label")
      .forEach((label) => {
        label.textContent = name || "게스트";
      });
    document.querySelectorAll(".site-header .avatar").forEach((avatar) => {
      avatar.textContent = name ? name.slice(0, 1) : "G";
    });
  }

  function open({ onChange } = {}) {
    if (document.querySelector(".profile-dialog[open]")) return;
    const name = readName();
    const dialog = document.createElement("dialog");
    dialog.className = "profile-dialog";
    dialog.setAttribute("aria-labelledby", "profile-dialog-title");
    dialog.innerHTML = `
      <form method="dialog" class="profile-dialog-form">
        <button type="button" class="profile-close" aria-label="창 닫기">×</button>
        <span class="profile-kicker">HELLO, LUNCH MATE</span>
        <h2 id="profile-dialog-title"></h2>
        <p>회원 흐름을 미리 보는 로컬 데모예요.<br>SNS 로그인과 실제 회원가입은 연결하지 않았어요.</p>
        <label for="profile-nickname">어떻게 불러드릴까요?</label>
        <input id="profile-nickname" maxlength="12" placeholder="닉네임 (최대 12자)" autocomplete="nickname">
        <p class="profile-storage-note">닉네임·찜·제외 메뉴는 이 브라우저에만 저장돼요.<br>게스트도 모든 게임을 이용할 수 있어요.</p>
        <p class="profile-error" role="status" aria-live="polite"></p>
        <div class="profile-actions">
          ${name ? '<button type="button" class="profile-guest">게스트로 사용</button>' : ""}
          <button type="submit" class="profile-save">닉네임 저장하고 시작하기 ↗</button>
        </div>
      </form>
    `;
    document.body.appendChild(dialog);
    dialog.querySelector("h2").textContent = name
      ? `반가워요, ${name}님!`
      : "나만의 점심 취향을 모아보세요";
    const input = dialog.querySelector("input");
    input.value = name;

    function save(value) {
      const preferences = readPreferences();
      preferences.profile = value;
      try {
        localStorage.setItem(storageKey, JSON.stringify(preferences));
        temporaryProfile = null;
      } catch {
        temporaryProfile = value;
      }
      updateHeader(value);
      window.dispatchEvent(new Event("lunchrun:profile-change"));
      onChange?.(value);
      dialog.close();
    }

    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        dialog.querySelector(".profile-error").textContent =
          "사용할 닉네임을 입력해 주세요.";
        input.focus();
        return;
      }
      save(value);
    });
    dialog
      .querySelector(".profile-guest")
      ?.addEventListener("click", () => save(""));
    dialog.querySelector(".profile-close").onclick = () => dialog.close();
    dialog.onclick = (event) => {
      if (event.target === dialog) dialog.close();
    };
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    dialog.showModal();
    input.focus();
  }

  document.addEventListener("DOMContentLoaded", () => updateHeader());
  window.addEventListener("pageshow", () => updateHeader());
  function showNoMenus() {
    if (document.querySelector('.no-menu-dialog[open]')) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'profile-dialog no-menu-dialog';
    dialog.setAttribute('aria-label', '메뉴 안내');
    dialog.innerHTML = `<form method="dialog" class="profile-dialog-form">
      <button type="submit" class="profile-close" aria-label="창 닫기">×</button>
      <h2>메뉴 안내</h2>
      <p class="no-menu-message">현재 위치, 예산, 영업 조건에 맞는<br>메뉴가 없습니다.</p>
      <div class="profile-actions"><button class="profile-save" type="submit">확인</button></div>
    </form>`;
    dialog.onclick = event => { if (event.target === dialog) dialog.close(); };
    dialog.addEventListener('close', () => dialog.remove(), {once:true});
    document.body.appendChild(dialog);
    dialog.showModal();
  }
  return { open, readName, updateHeader, showNoMenus };
})();
