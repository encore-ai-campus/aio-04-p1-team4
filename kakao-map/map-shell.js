// Shared chrome only; restaurant and route logic stay in integration.js.
document.getElementById('header-location').onclick=()=>document.getElementById('change-location').click();
document.getElementById('account').onclick=()=>window.LunchRunProfile?.open();
document.getElementById('dock-route').onclick=()=>{
 const card=document.getElementById('selected-card');
 if(card.hidden){document.getElementById('search-status').textContent='목록이나 지도에서 식당을 먼저 선택해주세요.';document.getElementById('restaurant-list').scrollIntoView({block:'center',behavior:'smooth'});return;}
 card.scrollIntoView({block:'center',behavior:'smooth'});
 const route=card.querySelector('.walking-route-button');route?.focus({preventScroll:true});
};
