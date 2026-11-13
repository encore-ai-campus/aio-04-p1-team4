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

// Cross-page transitions can be canceled by back/forward or non-participating pages.
for(const type of ['pageswap','pagereveal'])window.addEventListener(type,event=>{const transition=event.viewTransition;if(transition){transition.ready.catch(()=>{});transition.finished.catch(()=>{});transition.updateCallbackDone?.catch(()=>{});}});
