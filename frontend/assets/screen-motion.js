// Animate actual screen changes without replaying on condition input or rerender.
window.LunchRunMotion = (() => {
  let activeElement = null;
  let activeScreen = null;

  function enter(element, screenKey) {
    if (!element || (activeElement === element && activeScreen === screenKey))
      return;
    activeElement = element;
    activeScreen = screenKey;
    element.classList.remove("screen-enter");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    void element.offsetWidth;
    element.classList.add("screen-enter");
  }

  return { enter };
})();
