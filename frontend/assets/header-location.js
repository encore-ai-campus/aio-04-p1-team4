window.LunchRunHeaderLocation=(()=>{
 function update(){const location=window.LunchRunState?.read().location,name=location?.name||'위치설정';document.querySelectorAll('.site-header .location-label').forEach(label=>{
  let text=label.querySelector('.location-name');if(!text){text=document.createElement('span');text.className='location-name';label.replaceChildren(text);}if(text.textContent!==name)text.textContent=name;label.title=name;
  label.classList.remove('location-scrolling');const distance=Math.max(0,text.scrollWidth-label.clientWidth);label.style.setProperty('--location-travel',-distance+'px');label.style.setProperty('--location-duration',Math.max(8,distance/25)+'s');label.classList.toggle('location-scrolling',distance>1);
 });}
 function start(){update();window.LunchRunState?.subscribe(update);document.fonts?.ready.then(update);}
 document.addEventListener('DOMContentLoaded',start);window.addEventListener('pageshow',update);window.addEventListener('resize',update);return {update};
})();
