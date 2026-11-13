let base='';
async function configure(){if(location.protocol==='file:')throw Error('FastAPI 서버에서 실행해주세요.');const r=await fetch('/config.json');if(!r.ok)throw Error('서버 설정을 읽지 못했습니다.');const config=await r.json();if(typeof config.apiBase!=='string')throw Error('API 주소 설정을 확인해주세요.');base=config.apiBase.replace(/\/$/,'');return false;}
async function request(path,body,{signal}={}){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),path==='/api/recommendations'?120000:30000);try{const r=await fetch(base+path,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:signal?AbortSignal.any([signal,controller.signal]):controller.signal});if(!r.ok){const error=await r.json().catch(()=>({}));throw Error(typeof error.detail==='string'?error.detail:r.status===422?'입력 조건과 서버 버전을 확인해주세요.':`서버 요청 실패 (${r.status})`);}return await r.json();}finally{clearTimeout(timer);}}
const demoRestaurants=[{id:'demo-a',name:'점심식당',menu:'김치찌개',price:9000,distance_m:450,walk_minutes:7},{id:'demo-b',name:'골목식당',menu:'김치찌개',price:10000,distance_m:620,walk_minutes:null}];

const $=s=>document.querySelector(s),state={budget:5000,remaining_minutes:50,distance_m:500,people:1,category:'전체',origin:null,end_time:'12:30',participant_menus:[],game:null,menu:null,restaurants:[],selected:null,route:null,context:''};
const shared=typeof window!=='undefined'?window.LunchRunState:null;
const HOME_PATHS={conditions:'/',ai:'/ai',budget:'/budget',time:'/time','end-time':'/time',distance:'/distance',people:'/people','group-input':'/group-input',play:'/play',result:'/result'};
function routeName(){const path=location.pathname.replace(/\/+$/,'')||'/';return Object.keys(HOME_PATHS).find(key=>HOME_PATHS[key]===path)||'conditions';}
function routePath(name){return HOME_PATHS[name]||'/';}
// 이전 북마크는 일반 주소로 정리하며 화면 판정에는 pathname만 사용한다.
function normalizeLegacyRoute(){
 const name=location.hash.slice(1);
 if(['games','restaurants','route'].includes(name)){location.replace((name==='games'?'/games/':'/map/')+location.search);return;}
 if(Object.hasOwn(HOME_PATHS,name))history.replaceState(null,'',routePath(name)+location.search);
}
let requestVersion=0,requestController=null;
let previewVersion=0,previewController=null,previewTimer=null;

function refreshHomeCandidates(){
 clearTimeout(previewTimer);previewController?.abort();const version=++previewVersion;
 const panel=document.querySelector('#db-menu-preview');if(!panel)return;
 let body;try{body=payload();body.menu_id=null;}catch(e){panel.textContent=e.message;return;}
 panel.textContent='DB에서 메뉴·표시 가격·식당 수 확인 중…';
 const revision=shared?.read().contextRevision;
 previewTimer=setTimeout(async()=>{
  const controller=new AbortController();previewController=controller;
  try{
   const data=await request('/api/menus/candidates',body,{signal:controller.signal});
   if(version!==previewVersion||revision!==shared?.read().contextRevision||!panel.isConnected)return;
   // 1단계: 가격 미확인 메뉴도 후보이므로 NULL에 숫자 함수를 호출하지 않는다.
   panel.textContent=data.menus.length?data.menus.map(m=>`${m.name} ${m.verified_price==null?'가격 확인 필요':m.verified_price.toLocaleString()+'~'+m.verified_price_max.toLocaleString()+'원'} · ${m.nearby_restaurant_count}곳${m.serving_unverified?' · 인분 미확인':''}`).join(' / '):'현재 위치·예산·영업 조건에 맞는 DB 메뉴가 없습니다.';
  }catch(e){if(version===previewVersion&&panel.isConnected&&!controller.signal.aborted)panel.textContent=e.message;}
 },180);
}
function cancelRequests(){clearTimeout(previewTimer);previewController?.abort();previewVersion++;requestVersion++;requestController?.abort();requestController=null;busy=false;}
function clockFromDeadline(deadline){return new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(deadline));}
function clockDeadline(){const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date()).split(':').map(Number);const [h,m]=state.end_time.split(':').map(Number);return Math.floor(Date.now()/60000)*60000+(h*60+m-parts[0]*60-parts[1])*60000;}
function saveHome(){
 if(!shared)return;
 if(!Number.isFinite(state.deadline)||clockFromDeadline(state.deadline)!==state.end_time)state.deadline=clockDeadline();
 shared.setContext({location:state.selectedLocation||null,conditions:{budget:state.budget,radius_m:state.distance_m,cuisine:state.category,people:state.people,deadline:state.deadline}});
 shared.setSelection(state.selected?.id||null);
}
function restoreHome(){
 if(!shared)return;
 const saved=shared.read(),c=saved.conditions;
 Object.assign(state,{selectedLocation:saved.location,origin:saved.location?{latitude:saved.location.lat,longitude:saved.location.lng}:null,budget:c.budget,distance_m:c.radius_m,category:c.cuisine,people:c.people,deadline:c.deadline,end_time:clockFromDeadline(c.deadline),menu:saved.menu?.name||null,menuId:saved.menu?.id||null,restaurants:saved.restaurants,candidateRestaurants:saved.candidateRestaurants,selected:saved.restaurants.find(r=>r.id===saved.selectedRestaurantId)||null,route:saved.route});
 $('#location span').textContent=saved.location?.name||'위치';$('#location').title=saved.location?.address||'출발 위치 설정';
}
let demo=false,busy=false;const stages=['조건 설정','메뉴 결정','식당 선택','경로 확인'],routes=['conditions','games','restaurants','route'];
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(label,action,cls='')=>`<button class="${cls}" data-action="${action}">${label}</button>`;
const foodTypes=['전체','한식','중식','일식/회','양식','분식','패스트푸드','치킨','도시락/구내식당','뷔페식','냉면','고기','카페/빵','술집','기타'];
function payload(){
 if(!state.origin)throw Error('위치 설정을 먼저 해주세요.');
 const minutes=remainingLunch();
 if(minutes<1||minutes>120)throw Error('점심 종료 시간을 현재부터 1~120분 이내로 설정해주세요.');
 return {conditions:{budget:state.budget,minutes,cuisine:state.category},location:state.selectedLocation||{lat:state.origin.latitude,lng:state.origin.longitude,name:'현재 위치',source:'geolocation'},radius_m:state.distance_m,menu_id:state.menuId??null};
}
function invalidate(){cancelRequests();state.menu=null;state.menuId=null;state.candidateRestaurants=[];state.restaurants=[];state.selected=null;state.route=null;saveHome();shared?.setMenu(null);}
function go(r,gameSource=null){
 if(r==='restaurants'||r==='route'){saveHome();location.assign('/games/');return;}
 if(r==='backend-games'||r==='games'){
  try{
   payload();
   saveHome();
  }catch(error){
   $('#status').textContent=error.message||'게임에 조건을 전달하지 못했습니다.';
   return;
  }
  location.assign('/games/');return;
 }
 if(["games","group-input","play"].includes(r)&&state.people>12){$("#status").textContent="12명 초과시 게임추천 서비스는 사용 할 수 없습니다.";return;}
 const current=routeName();
 const expands=current==='conditions'&&['budget','time','distance','people'].includes(r);
 const source=gameSource||(expands?document.querySelector('[data-action="go:'+r+'"]'):null);
 const transitionName=gameSource?'game-expand':'condition-expand';
 const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 if(source&&!reduce){
  const from=source.getBoundingClientRect();
  const commit=()=>{history.pushState(null,'',routePath(r));render();window.scrollTo(0,0);};
  if(document.startViewTransition){source.style.viewTransitionName=transitionName;const t=document.startViewTransition(commit);t.finished.catch(()=>{});}
  else {commit();const target=document.querySelector(gameSource?'.result':'.setting .value');if(target){const to=target.getBoundingClientRect();target.animate([{transformOrigin:'top left',transform:'translate('+(from.left-to.left)+'px,'+(from.top-to.top)+'px) scale('+from.width/to.width+','+from.height/to.height+')'},{transformOrigin:'top left',transform:'none'}],{duration:420,easing:'cubic-bezier(.2,.75,.25,1)'});}}
  return;
 }
 history.pushState(null,'',routePath(r));render();window.scrollTo(0,0);
}

async function run(fn){if(busy)return;busy=true;const version=++requestVersion;requestController=new AbortController();$('#status').textContent='처리 중…';try{await fn(version,requestController.signal);if(version===requestVersion)$('#status').textContent='';}catch(e){if(version===requestVersion)$('#status').textContent=e.name==='AbortError'?'요청 시간이 초과되었습니다. 다시 시도해주세요.':e.message;}finally{if(version===requestVersion)busy=false;}}
function renderNavigation(route,stage){
 const items=[['조건 설정','conditions',stage===0],['AI 추천','ai',route==='ai'],['게임 선택','backend-games',stage===1&&route!=='ai'],['식당 선택','restaurants',stage===2],['경로 확인','route',stage===3]];
 $('#dock').innerHTML=items.map(([label,target,active])=>button(label,'go:'+target,active?'active':'')).join('');
}
function render(){saveHome();const r=routeName();const app=document.querySelector('.app'),previous=app.dataset.view;app.dataset.view=r;if(r!=='games')$('#dock').classList.remove('dock-enter');else if(previous!=='games')$('#dock').classList.add('dock-enter');let stage=['conditions','budget','time','end-time','people','distance'].includes(r)?0:r==='restaurants'?2:r==='route'?3:1;renderNavigation(r,stage);$('#summary').textContent=stage?`${state.budget.toLocaleString()}원 / ${remainingLunch()}분 남음 / ${state.distance_m}m / ${state.people}명${' / '+state.category}`:'';let title='오늘 점심, 어떻게 고를까요?',html='';
if(r==='conditions'){html='<div class="grid">'+[['예산설정','budget',state.budget.toLocaleString()+'원'],['남은시간','time',remainingLunch()+'분'],['거리설정','distance',state.distance_m+'m'],['인원 수 설정','people',state.people+'명']].map(([l,p,v])=>`<div class="field">${l}${button(v,'go:'+p,'card')}</div>`).join('')+'</div><p class="category-label">음식 카테고리</p><div class="chips">'+foodTypes.map(c=>`<button data-category="${c}" class="${c===state.category?'active':''}">${c}</button>`).join('')+'</div><p class="notice db-menu-preview" id="db-menu-preview" role="status">DB 메뉴와 표시 가격을 확인합니다.</p><div class="actions">'+(state.people>12?'<button class="primary" disabled>게임으로 메뉴 고르기</button>':button('게임으로 메뉴 고르기','go:backend-games','primary'))+button('AI에게 추천받기','go:ai')+'</div>';}
else if(r==='budget'){html='<div class="setting"><p>예산설정</p><div class="value">'+button('−','money:-1000')+'<label class="money-field"><input id="budget-input" aria-label="예산 금액" inputmode="numeric" type="text" value="'+state.budget.toLocaleString('ko-KR')+'" autocomplete="off"><span>원</span></label>'+button('+','money:1000')+'</div></div><div class="actions">'+button('적용','apply-budget','primary')+'</div>';}
else if(r==='time'||r==='end-time'){const [hour,minute]=state.end_time.split(':').map(Number);html='<div class="setting"><p>점심 종료 시간</p><div class="value time-value">'+button('−','clock:-10')+'<div class="time-fields"><select id="period" aria-label="오전 오후"><option value="AM" '+(hour<12?'selected':'')+'>AM</option><option value="PM" '+(hour>=12?'selected':'')+'>PM</option></select><label><input id="end-hour" aria-label="종료 시" type="number" min="1" max="12" value="'+(hour%12||12)+'"><span>시</span></label><label><input id="end-minute" aria-label="종료 분" type="number" min="0" max="59" value="'+String(minute).padStart(2,'0')+'"><span>분</span></label></div>'+button('+','clock:10')+'</div><p class="input-hint">− / + 버튼으로 10분씩 조정합니다.</p></div><div class="actions">'+button('적용','apply-time','primary')+'</div>';}
else if(r==='people'){html='<div class="setting"><p>인원 수 설정</p><div class="value">'+button('−','people-step:-1')+'<label class="people-field"><input id="people-input" aria-label="인원 수" aria-describedby="people-warning" type="number" min="1" step="1" value="'+state.people+'"><span>명</span></label>'+button('+','people-step:1')+'</div><p id="people-warning" class="people-warning" role="status" '+(state.people>12?'':'hidden')+'>12명 초과시 게임추천 서비스는 사용 할 수 없습니다.</p></div><div class="actions">'+button('적용','apply-people','primary')+'</div>';}
else if(r==='distance'){html='<div class="setting"><p>거리설정</p><div class="value">'+button('−','adjust:distance_m:-50')+'<strong>'+state.distance_m+'m</strong>'+button('+','adjust:distance_m:50')+'</div><input aria-label="거리설정" type="range" data-key="distance_m" min="50" max="500" step="50" value="'+state.distance_m+'"><div class="ends"><span>50m</span><span>500m</span></div></div><div class="actions">'+button('적용','go:conditions','primary')+'</div>';}
else if(r==='games'){title=state.people===1?'혼자서 가볍게 골라요':'함께 먹을 메뉴를 골라요';html='<div class="grid">'+(state.people===1?['제비뽑기','가챠','행운권 뽑기','랜덤게임']:['룰렛','사다리']).map(g=>'<button class="card game-card" data-game="'+g+'" '+(g==='사다리'&&state.people>8?'disabled':'')+'><strong>'+g+'</strong><small>'+(g==='랜덤게임'?'혼자 게임 중 하나를 자동 선택':'선택 후 게임 진행')+'</small></button>').join('')+'</div><div class="actions">'+button('조건 변경','go:conditions')+button('AI 추천','go:ai')+'</div>';}
else if(r==='group-input'){title='각자의 메뉴를 입력해주세요';html=Array.from({length:state.people},(_,i)=>`<label class="field">사용자 ${i+1}<input data-participant="${i}" maxlength="50" value="${escape(state.participant_menus[i]||'')}" placeholder="메뉴 입력"></label>`).join('')+button('메뉴 결정','prepare-group','primary');}
else if(r==='play'){title='점심 메뉴를 뽑고 있어요';html=`<div class="card result">${escape(state.game)}</div>`+button('메뉴 뽑기','draw','primary');}
else if(r==='ai'){title='지금 나에게 맞는 메뉴';html='<div id="home-chat"></div>';}
else if(r==='result'){title='오늘의 점심 메뉴';html=`<div class="card result">${escape(state.menu||'아직 결정된 메뉴가 없습니다.')}</div><p>식당은 다음 단계에서 선택합니다.</p><div class="actions">${button('한번더',state.game?'draw':'recommend')}${button('OK · 식당 탐색','find','primary')}</div>`;}
else if(r==='restaurants'){if(demo&&!state.restaurants.length){state.menu||='김치찌개';state.restaurants=demoRestaurants;}title='이 메뉴를 먹을 수 있는 곳';html='<div class="restaurant-layout"><div class="restaurant-list">'+state.restaurants.map(x=>'<button class="card restaurant-card '+(state.selected?.id===x.id?'selected':'')+'" data-restaurant="'+escape(x.id)+'"><strong>'+escape(x.name)+'</strong>'+escape(state.menu)+' '+(typeof x.price==='number'?escape(x.price):'미확인')+'원<span>'+escape(x.distance_m)+'m · '+(x.walk_minutes==null?'도보 시간 미확인':'도보 '+escape(x.walk_minutes)+'분')+'</span></button>').join('')+'</div><figure class="map-preview"><img src="assets/restaurants.png" alt="예시 식당 지도"><figcaption>예시 지도 · 실제 위치와 무관</figcaption></figure></div><div class="actions">'+button('식당 랜덤','random')+button('OK · 경로 확인','route','primary')+'</div>';if(!state.restaurants.length)html='<p>후보가 없습니다. 조건을 변경해주세요.</p>'+button('식당 검색','find');}
else if(r==='route'){if(demo&&!state.route){state.selected=demoRestaurants[0];state.route={distance_m:450,walk_minutes:7};}title='선택한 식당으로 출발';html=state.route?'<div class="map"><div class="card route-summary"><strong>총소요예상 '+escape(state.route.walk_minutes)+'분　│　총거리 '+escape(state.route.distance_m)+'m</strong><p>현재 위치 → '+escape(state.selected?.name)+' / 편도 도보 예상 · 예시</p></div><img src="assets/route.png" alt="도보 경로 예시"><button class="route-back" data-action="go:restaurants">다른 식당 선택</button></div><p class="route-note">대기·식사·왕복 시간 포함 여부는 미확정입니다.</p>':'<p>식당을 먼저 선택해주세요.</p>'+button('식당 선택','go:restaurants');}
else{html=button('조건 설정으로','go:conditions');}$('#title').textContent=title;$('#screen').innerHTML=html;refreshHomeCandidates();if(r==='ai')window.LunchRunChat.mount($('#home-chat'),{onState:()=>{restoreHome();$('#summary').textContent=state.budget.toLocaleString()+'원 / '+remainingLunch()+'분 남음 / '+state.distance_m+'m / '+state.people+'명 / '+state.category;}});else window.LunchRunChat.close();window.LunchRunMotion?.enter($('#screen'),r);fitBudgetWidth();const expanded=document.querySelector('.setting .value');if(expanded)expanded.style.viewTransitionName='condition-expand';
const icons={'전체':'M3 17h26M5 16a11 11 0 0 1 22 0M14 3h4M16 3v3','한식':'M4 14h24c0 8-5 13-12 13S4 22 4 14M8 10l2-4m6 4V5m6 5 2-4','일식':'M4 20c0-9 24-13 24-3v6H4ZM10 15l3 7m4-10 3 9','중식':'M4 16h24c0 8-5 12-12 12S4 24 4 16M9 11c-5-5 5-5 0-10m7 10c-5-5 5-5 0-10m7 10c-5-5 5-5 0-10','양식':'M8 3v12m-4-12v8c0 5 8 5 8 0V3M8 15v14M24 3c-8 5-8 13 0 13V3v26','샐러드':'M4 17h24c-1 7-5 11-12 11S5 24 4 17M16 16C4 16 6 3 10 6c4 2 6 6 6 10Zm0 0c0-12 9-13 10-10-1 5-4 8-10 10Z'};
document.querySelectorAll('[data-category]').forEach(b=>b.insertAdjacentHTML('afterbegin','<svg class="food-icon" width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="'+(icons[b.dataset.category==='일식/회'?'일식':b.dataset.category]||icons['전체'])+'"/></svg>'));

const img=(name,alt)=>'<img class="visual-asset" src="assets/'+name+'.png" alt="'+alt+'">';
if(r==='play'){document.querySelector('.result').style.viewTransitionName='game-expand';const names={'제비뽑기':'draw','가챠':'gacha','행운권 뽑기':'ticket','랜덤게임':'random','룰렛':'roulette','사다리':'ladder'};$('#screen .result').innerHTML=img(names[state.game]||'gacha',state.game||'게임 예시');$('#screen .result').insertAdjacentHTML('afterend','<p class="play-note">설정 조건 안에서 음식 메뉴만 추첨합니다.</p>');}
if(r==='games'){const names={'제비뽑기':'draw','가챠':'gacha','행운권 뽑기':'ticket','랜덤게임':'random','룰렛':'roulette','사다리':'ladder'};document.querySelectorAll('[data-game]').forEach(b=>b.insertAdjacentHTML('beforeend',img('option-'+names[b.dataset.game],b.dataset.game+' 예시')));}
if(r==='result'){const result=$('#screen .result');result.className='card menu-result';result.innerHTML=img('result','선택 메뉴 예시')+'<div><small>선택된 음식 메뉴</small><strong>'+escape(state.menu||'아직 미결정')+'</strong><p>식당은 다음 단계에서 선택합니다.</p></div>';result.nextElementSibling.remove();}
if(false)$('#screen').insertAdjacentHTML('afterbegin','<figure class="map-preview">'+img('restaurants','식당 위치 예시 지도')+'<figcaption>예시 지도 · 실제 위치와 무관</figcaption></figure>');
if(false)$('#screen .map').innerHTML=img('route','선택 식당까지 도보 경로 예시')+'<p>예시 경로 · 실제 길찾기 연동 전</p>';
}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.category){state.category=b.dataset.category;invalidate();render();}if(b.dataset.game){state.game=b.dataset.game;state.participant_menus=[];go(state.people>1?'group-input':'play',state.people===1?b:null);}if(b.dataset.restaurant){state.selected=state.restaurants.find(x=>x.id===b.dataset.restaurant);render();$('#status').textContent=state.selected.name+' 선택됨';}const a=b.dataset.action;if(!a)return;if(a.startsWith('money:')){commitBudget();state.budget=Math.max(1000,Math.min(100000,state.budget+Number(a.split(':')[1])));invalidate();render();return;}if(a==='recommend'){go('ai');return;}if(a==='apply-people'){if(commitPeople())go('conditions');return;}if(a.startsWith('people-step:')){if(!commitPeople())return;state.people=Math.max(1,state.people+Number(a.split(':')[1]));invalidate();render();return;}if(a==='apply-budget'){commitBudget();go('conditions');return;}if(a.startsWith('clock:')){if(!commitTime())return;const [h,m]=state.end_time.split(':').map(Number);const total=(h*60+m+Number(a.split(':')[1])+1440)%1440;state.end_time=String(Math.floor(total/60)).padStart(2,'0')+':'+String(total%60).padStart(2,'0');invalidate();render();return;}if(a==='apply-time'){if(commitTime()){invalidate();go('conditions');}return;}if(a.startsWith('go:')){cancelRequests();return go(a.slice(3));}if(a.startsWith('adjust:')){const[,k,v]=a.split(':');const ranges={budget:[1000,100000],remaining_minutes:[1,120],people:[1,Infinity],distance_m:[50,500]};state[k]=Math.max(ranges[k][0],Math.min(ranges[k][1],state[k]+Number(v)));invalidate();render();return;}if(a==='prepare-group'){if(Array.from({length:state.people},(_,i)=>state.participant_menus[i]?.trim()).some(v=>!v)){ $('#status').textContent='참가자별 메뉴를 모두 입력해주세요.';return;}go('play');return;}run(async(version,signal)=>{if(a==='draw'){const body=payload();body.menu_id=null;const result=await request('/api/menus/draw',body,{signal});if(version!==requestVersion)return;if(!result.menu)throw Error(result.message||'현재 조건에 맞는 메뉴가 없습니다.');if(typeof result.menu.id!=='string'||typeof result.menu.name!=='string')throw Error('메뉴 응답 형식을 확인해주세요.');shared?.setMenu(result.menu);state.menu=result.menu.name;state.menuId=result.menu.id;state.restaurants=[];state.selected=null;state.route=null;go('result');}if(a==='find'){if(!state.menu)throw Error('메뉴를 먼저 결정해주세요.');saveHome();payload();location.assign('/games/');return;}if(a==='random'){if(!state.restaurants.length)throw Error('후보가 없습니다.');state.selected=state.restaurants[Math.floor(Math.random()*state.restaurants.length)];render();$('#status').textContent=state.selected.name+' 선택됨';}if(a==='route'){if(!state.selected)throw Error('식당을 선택해주세요.');state.route=demo?{distance_m:state.selected.distance_m,walk_minutes:state.selected.walk_minutes??9}:await request('/api/routes',{origin:state.origin,restaurant_id:state.selected.id},{signal});if(version!==requestVersion)return;go('route');}});});
document.addEventListener('input',e=>{if(e.target.dataset.key){state[e.target.dataset.key]=Number(e.target.value);invalidate();const val=$('#screen .value strong');if(val){const k=e.target.dataset.key;val.textContent=k==='budget'?state[k].toLocaleString()+'원':state[k]+({people:'명',distance_m:'m',remaining_minutes:'분'}[k]||'');}}if(e.target.dataset.participant!==undefined)state.participant_menus[Number(e.target.dataset.participant)]=e.target.value;});
$('#location').onclick=()=>window.LunchRunLocationPicker.open(item=>{
 state.selectedLocation={...item};state.origin={latitude:item.lat,longitude:item.lng};
 invalidate();$('#location span').textContent=item.name;$('#location').title=item.address;
 $('#status').textContent='출발 위치를 설정했어요: '+(item.address||item.name);
},state.selectedLocation);
window.addEventListener('hashchange',()=>{normalizeLegacyRoute();cancelRequests();window.LunchRunLocationPicker.close();restoreHome();render();});

normalizeLegacyRoute();restoreHome();render();configure().then(v=>{demo=v;$('#mode').textContent=demo?'':'백엔드 연결 모드';render();}).catch(e=>{$('#mode').textContent='설정 확인 전 · 시안 미리보기';$('#status').textContent=e.message;});

$('#account').onclick=()=>window.LunchRunProfile.open();

function fitCanvas(){document.documentElement.style.setProperty('--scale',Math.min(1,window.innerWidth/1516,window.innerHeight/1038));}window.addEventListener('resize',fitCanvas);fitCanvas();

function remainingLunch(){return Math.max(0,Math.ceil(((state.deadline??clockDeadline())-Date.now())/60000));}
function displayEndTime(){const [h,m]=state.end_time.split(':').map(Number);return(h<12?'AM':'PM')+' '+String(h%12||12).padStart(2,'0')+':'+String(m).padStart(2,'0');}
function commitBudget(){const el=$('#budget-input');if(!el)return;const digits=el.value.replace(/[^0-9]/g,'');state.budget=Math.min(100000,Math.max(1000,Number(digits)||1000));el.value=state.budget.toLocaleString('ko-KR');fitBudgetWidth();invalidate();}
function commitTime(){const h=$('#end-hour'),m=$('#end-minute');if(!h||!m)return false;const hh=Number(h.value),mm=Number(m.value);if(h.value===''||m.value===''||!Number.isInteger(hh)||!Number.isInteger(mm)||hh<1||hh>12||mm<0||mm>59){$('#status').textContent='시는 1~12, 분은 0~59 사이의 정수로 입력해주세요.';return false;}state.end_time=String(hh%12+($('#period').value==='PM'?12:0)).padStart(2,'0')+':'+String(mm).padStart(2,'0');$('#status').textContent='';return true;}
document.addEventListener('input',e=>{if(e.target.id==='budget-input'){const el=e.target,caret=el.selectionStart,leftDigits=el.value.slice(0,caret).replace(/[^0-9]/g,'').length;let raw=el.value.replace(/[^0-9]/g,'');if(Number(raw)>100000)raw='100000';el.value=raw?Number(raw).toLocaleString('ko-KR'):'';let seen=0,pos=0;while(pos<el.value.length&&seen<leftDigits){if(/[0-9]/.test(el.value[pos]))seen++;pos++;}el.setSelectionRange(pos,pos);fitBudgetWidth();}});
document.addEventListener('focusout',e=>{if(e.target.id==='budget-input')commitBudget();});

function fitBudgetWidth(){const el=document.querySelector('#budget-input');if(!el)return;const context=document.createElement('canvas').getContext('2d');if(!context)return;const style=getComputedStyle(el);context.font=style.fontWeight+" "+style.fontSize+" "+style.fontFamily;el.style.width=Math.ceil(context.measureText(el.value||'0').width+4)+'px';}
function refreshRemainingTime(){const button=document.querySelector('.app[data-view="conditions"] [data-action="go:time"]');if(button)button.textContent=remainingLunch()+'분';const summary=document.querySelector('#summary');if(summary&&summary.textContent){summary.textContent=state.budget.toLocaleString()+'원 / '+remainingLunch()+'분 남음 / '+state.distance_m+'m / '+state.people+'명'+(' / '+state.category);}}
setInterval(refreshRemainingTime,15000);window.addEventListener('focus',refreshRemainingTime);

function commitPeople(){const el=$('#people-input');if(!el)return true;const n=Number(el.value);if(!el.value||!Number.isSafeInteger(n)||n<1){$('#status').textContent='인원 수는 1명 이상의 정수로 입력해주세요.';return false;}state.people=n;invalidate();$('#status').textContent='';return true;}
document.addEventListener('input',e=>{if(e.target.id!=='people-input')return;const n=Number(e.target.value);$('#people-warning').hidden=!(n>12);if(Number.isSafeInteger(n)&&n>=1){state.people=n;invalidate();}});
document.addEventListener('focusout',e=>{if(e.target.id==='people-input')commitPeople();});

window.addEventListener('pagehide',()=>{saveHome();cancelRequests();window.LunchRunLocationPicker.close();});
window.addEventListener('pageshow',event=>{if(event.persisted){cancelRequests();restoreHome();render();}});
window.addEventListener('popstate',()=>{normalizeLegacyRoute();cancelRequests();window.LunchRunLocationPicker.close();restoreHome();render();});
