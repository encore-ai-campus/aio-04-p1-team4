// One location-only dialog, shared by the main app and standalone games.
window.LunchRunLocation = (() => {
  const storageKey = "lunchrun-location";
  const places = {
    독산역: [37.4666, 126.8895],
    금천구청: [37.4569, 126.8955],
    금천구청역: [37.4556, 126.8939],
    가산디지털단지역: [37.4811, 126.8826],
  };

  function valid(value) {
    return (
      value &&
      typeof value.name === "string" &&
      Number.isFinite(value.latitude) &&
      Math.abs(value.latitude) <= 90 &&
      Number.isFinite(value.longitude) &&
      Math.abs(value.longitude) <= 180
    );
  }

  function read() {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey));
      return valid(value) ? value : null;
    } catch {
      return null;
    }
  }

  function open({ current, onChange }) {
    if (document.querySelector(".location-dialog[open]")) return;
    const dialog = document.createElement("dialog");
    dialog.className = "location-dialog";
    dialog.setAttribute("aria-labelledby", "location-dialog-title");
    dialog.innerHTML = `
      <form method="dialog" class="location-dialog-form">
        <button type="button" class="location-dialog-close" aria-label="위치 설정 닫기">×</button>
        <h2 id="location-dialog-title">위치 설정</h2>
        <p>어디에서 출발하나요?</p>
        <label for="location-choice">출발 위치</label>
        <select id="location-choice">
          ${Object.keys(places)
            .map((name) => `<option>${name}</option>`)
            .join("")}
        </select>
        <p class="location-dialog-hint">역·구청 좌표는 대략적인 기준점입니다.</p>
        <button type="button" class="location-current">현재 위치 사용</button>
        <p class="location-dialog-status" role="status" aria-live="polite"></p>
        <button type="submit" class="location-apply">적용</button>
      </form>
    `;
    document.body.appendChild(dialog);
    const choice = dialog.querySelector("select");
    const status = dialog.querySelector(".location-dialog-status");
    let selected = valid(current) ? current : read();
    if (selected && !places[selected.name]) {
      choice.add(new Option(selected.name, selected.name));
    }
    choice.value = selected?.name || "독산역";
    choice.addEventListener("change", () => {
      status.textContent = "";
    });
    dialog.querySelector(".location-dialog-close").onclick = () =>
      dialog.close();
    dialog.onclick = (event) => {
      if (event.target === dialog) dialog.close();
    };
    dialog.querySelector(".location-current").onclick = () => {
      if (!navigator.geolocation) {
        status.textContent = "현재 위치 기능을 사용할 수 없습니다.";
        return;
      }
      status.textContent = "현재 위치를 확인하고 있어요…";
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (!dialog.open) return;
          selected = {
            name: "현재 위치",
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          };
          if (
            ![...choice.options].some((option) => option.value === "현재 위치")
          ) {
            choice.add(new Option("현재 위치", "현재 위치"));
          }
          choice.value = "현재 위치";
          status.textContent = "현재 위치를 확인했습니다. 적용을 눌러주세요.";
        },
        () => {
          if (dialog.open)
            status.textContent =
              "위치 권한을 확인하거나 출발 위치를 선택해주세요.";
        },
        { timeout: 10000 },
      );
    };
    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const point = places[choice.value];
      const value = point
        ? { name: choice.value, latitude: point[0], longitude: point[1] }
        : selected;
      if (!valid(value)) return;
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(value));
      } catch {}
      onChange(value);
      dialog.close();
    });
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    dialog.showModal();
  }

  return { open, read, places };
})();
