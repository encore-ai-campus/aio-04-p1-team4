// Shared chrome only; restaurant and route logic stay in integration.js.
document.getElementById('header-location').onclick=()=>document.getElementById('change-location').click();
document.getElementById('account').onclick=()=>window.LunchRunProfile?.open();
function fitMapPage(){document.documentElement.style.setProperty('--map-scale',Math.min(1,innerWidth/1516,innerHeight/1038));}
fitMapPage();window.addEventListener('resize',fitMapPage);

// Match the whole list (including its heading) to the rendered map's top edge.
function alignRestaurantList(){
 const list=document.querySelector('.restaurant-page aside'),map=document.getElementById('map'),page=document.querySelector('.restaurant-page');
 if(!list||!map||!page)return;
 if(innerWidth<=760){list.style.removeProperty('top');return;}
 const top=map.getBoundingClientRect().top-page.getBoundingClientRect().top;
 list.style.top=top+'px';
}
window.addEventListener('resize',alignRestaurantList);
window.addEventListener('load',alignRestaurantList);
document.fonts?.ready.then(alignRestaurantList);
const listAlignmentObserver=new ResizeObserver(alignRestaurantList);
for(const node of document.querySelectorAll('.restaurant-page,.page-heading,#map'))listAlignmentObserver.observe(node);
requestAnimationFrame(alignRestaurantList);
