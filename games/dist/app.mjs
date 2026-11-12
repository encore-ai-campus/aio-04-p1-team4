import {mountRoomFlow,closeRoomFlow} from './rooms.mjs';
import { randomIndex, pickMenu, buildLadder, createSpotlightPlan } from './engine.mjs';
import { FOOD_TYPES, gameRequest, gameMenu, backendRequest, matchEntry } from './backend.mjs';
let MENUS=[],poolVersion=0,poolController=null,poolTimer,searchController=null;
const shared=window.LunchRunState;
let displayedTime,lastDeadline;

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const won = (n) => Number.isFinite(n)?n.toLocaleString('ko-KR'):'미확인';
const delay = (n) => new Promise(r => setTimeout(r, matchMedia('(prefers-reduced-motion: reduce)').matches ? 60 : n));
const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
function takeLaunchSettings(){
  try{
    const raw=sessionStorage.getItem('lunchrun-games-settings');
    if(!raw)return {settings:{},warning:''};
    sessionStorage.removeItem('lunchrun-games-settings');
    const value=JSON.parse(raw);
    if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('invalid settings');
    const settings={},warnings=[];
    const number=(key,min,max)=>{
      if(value[key]===undefined)return;
      const n=Number(value[key]);
      if(!Number.isFinite(n)||n<min||n>max)warnings.push(key);
      else settings[key]=n;
    };
    number('budget',1000,100000);
    number('time',1,120);
    number('distance',50,500);
    number('people',1,12);
    if(Array.isArray(value.categories)&&value.categories.length<=1&&value.categories.every(c=>FOOD_TYPES.includes(c)))settings.categories=value.categories;
    else if(value.categories!==undefined)warnings.push('categories');
    if(value.origin!==null&&value.origin!==undefined){
      const {latitude,longitude}=value.origin;
      if(Number.isFinite(latitude)&&latitude>=-90&&latitude<=90&&Number.isFinite(longitude)&&longitude>=-180&&longitude<=180)settings.origin=[latitude,longitude];
      else warnings.push('origin');
    }
    if(settings.origin){
      const supplied=value.selectedLocation;
      settings.selectedLocation=supplied&&window.LunchRunLocation.validCoordinates(supplied.lat,supplied.lng)&&supplied.lat===settings.origin[0]&&supplied.lng===settings.origin[1]&&['geolocation','address','place'].includes(supplied.source)?supplied:{lat:settings.origin[0],lng:settings.origin[1],name:'현재 위치',address:'',source:'geolocation'};
    }
    return {settings,warning:warnings.length?'일부 전달된 조건을 사용할 수 없어 기본값으로 설정했어요.':''};
  }catch{
    return {settings:{},warning:'전달된 조건을 읽지 못해 게임 기본값으로 설정했어요.'};
  }
}
const prefs = read('lunchrun-demo2', {});
const launch = takeLaunchSettings();
const state = {
  view:'game', mode:'group', game:'intersection', budget:launch.settings.budget??12000, time:launch.settings.time??45, distance:launch.settings.distance??500, categories:launch.settings.categories??[], people:launch.settings.people??1,
  names:Array.from({length:12}, (_,i)=>i === 0 ? '나' : `팀원 ${i+1}`), favorites:Array.isArray(prefs.favorites)?prefs.favorites:[],
  blacklist:Array.isArray(prefs.blacklist)?prefs.blacklist:[], profile:typeof prefs.profile==='string'?prefs.profile:'', location:launch.settings.selectedLocation?.name||'위치 미설정', selectedLocation:launch.settings.selectedLocation??null, origin:launch.settings.origin??null, result:null,
  pending:null, previous:null, busy:false, ladder:null, ladderStart:0, selectedRestaurant:0, route:false, aiReady:false, aiPrompt:'', aiNotes:[], restaurantCandidates:null, restaurantDrawing:false, restaurantDrawDone:false, restaurantSpotlight:-1
};

function applySharedGame(){
 const saved=shared.read(),c=saved.conditions,g=saved.game||{};
 Object.assign(state,{budget:c.budget,distance:c.radius_m,categories:c.cuisine==='전체'?[]:[c.cuisine],people:c.people,lunchDeadline:c.deadline,time:shared.remainingMinutes(c.deadline),selectedLocation:saved.location,location:saved.location?.name||'위치 미설정',origin:saved.location?[saved.location.lat,saved.location.lng]:null,result:saved.menu?gameMenu(saved.menu):null,restaurantCandidates:saved.searchedAt?saved.restaurants.map(r=>({...r,distance:r.distance_m,menu:saved.menu?.name,emoji:saved.menu?.emoji||'🍽️'})):null,unverifiedRestaurants:saved.candidateRestaurants,route:false,pending:null});
 if(['solo','group','ai'].includes(g.mode))state.mode=g.mode;
 if(['draw','gacha','ticket','random','intersection','roulette','ladder'].includes(g.game))state.game=g.game;
 if(['game','restaurants','saved'].includes(g.view))state.view=g.view;
 state.selectedRestaurant=Math.max(0,saved.restaurants.findIndex(r=>r.id===saved.selectedRestaurantId));
 state.restaurantDrawDone=Boolean(g.restaurantDrawDone&&saved.selectedRestaurantId);
 displayedTime=state.time;lastDeadline=state.lunchDeadline;
}
function saveGame(){
 if(state.lunchDeadline===lastDeadline&&state.time!==displayedTime)state.lunchDeadline=Math.floor(Date.now()/60000)*60000+state.time*60000;
 state.time=shared.remainingMinutes(state.lunchDeadline);displayedTime=state.time;lastDeadline=state.lunchDeadline;
 shared.setContext({location:state.selectedLocation,conditions:{budget:state.budget,radius_m:state.distance,cuisine:state.categories[0]||'전체',people:state.people,deadline:state.lunchDeadline}});
 shared.setGame({mode:state.mode,game:state.game,view:state.view,restaurantDrawDone:state.restaurantDrawDone});
 const selected=state.restaurantCandidates?.[state.selectedRestaurant];
 if(selected)shared.setSelection(selected.id);
}
function cancelGameRequests(){++poolVersion;poolController?.abort();searchController?.abort();clearTimeout(poolTimer);}
if(!shared.hasSaved()&&launch.settings.origin){
 shared.setContext({location:launch.settings.selectedLocation,conditions:{budget:state.budget,radius_m:state.distance,cuisine:state.categories[0]||'전체',people:state.people,deadline:Math.floor(Date.now()/60000)*60000+state.time*60000}});
}
applySharedGame();

const games = {
  draw:{name:'제비뽑기',sub:'느낌 오는 카드 한 장',icon:'▱',badge:'PICK A CARD'},
  gacha:{name:'가챠',sub:'돌려서 만나는 점심',icon:'◒',badge:'CAPSULE PICK'},
  ticket:{name:'행운권 뽑기',sub:'오늘의 행운을 열어요',icon:'▤',badge:'LUCKY TICKET'},
  random:{name:'랜덤 게임',sub:'게임도 운명에 맡기기',icon:'⚄',badge:'SURPRISE ME'},
  intersection:{name:'우리의 교집합',sub:'각자 고르고, 함께 결정해요',icon:'◎',badge:'OUR INTERSECTION'},
  roulette:{name:'룰렛',sub:'함께 돌리는 오늘의 메뉴',icon:'◉',badge:'SPIN TOGETHER'},
  ladder:{name:'사다리 타기',sub:'어느 길로 가볼까요?',icon:'⋈',badge:'FOLLOW YOUR LUCK'}
};
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),3200); }
function persist(){try{localStorage.setItem('lunchrun-demo2', JSON.stringify({favorites:state.favorites,blacklist:state.blacklist,profile:state.profile}));}catch{toast('브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 유지돼요.');} updateProfile();}
function candidates(){return MENUS.filter(m=>!state.blacklist.includes(m.id));}
function validateGamePool(){saveGame();gameRequest(state);if(!candidates().length)throw Error('현재 조건에 맞는 메뉴 후보가 없습니다. 조건을 변경해주세요.');}
function roomContext(filters,people,menus){cancelGameRequests();Object.assign(state,filters);state.people=people;state.mode='group';state.game='intersection';state.result=null;state.pending=null;resetRestaurantDraw();MENUS=menus.map(gameMenu);shared.setMenu(null);saveGame();syncFilters();$('#candidate-count').textContent=menus.length+'개';}
async function refreshCandidates(){
 clearTimeout(poolTimer);const version=++poolVersion;poolController?.abort();poolController=new AbortController();
 MENUS=[];render();
 if(!state.origin){toast('먼저 출발 위치를 설정해주세요.');return;}
 try{
  const data=await backendRequest('/api/menus/candidates',gameRequest(state),{signal:poolController.signal});
  if(version!==poolVersion)return;
  if(!Array.isArray(data.menus))throw Error('메뉴 후보 응답을 확인해주세요.');
  MENUS=data.menus.map(gameMenu);gs.entries=[];gs.menus=[];
  render();if(!MENUS.length)toast('현재 조건에 맞는 메뉴가 없습니다.');
 }catch(error){if(version===poolVersion&&error.name!=='AbortError')toast(error.message);}
}
async function findRestaurants(){if(state.busy||!state.result)return;saveGame();gameRequest(state,state.result.id);location.assign('/map/?search=1');}

function menuStats(m){return m.price_verified?`<span>확인 가격 ${won(m.verified_price)}원</span><span>영업・이동시간은 식당 검색 후 확인</span>`:`<span>기준가격 ${won(m.price_hint)}원 · 실제 가격 미확인</span>`;}
const busyControls=new Map();
function setBusy(value){
  state.busy=value;
  if(value){for(const e of $$('button, #filters-form input, #filters-form select, #location, .participant-inputs input')){if(!busyControls.has(e))busyControls.set(e,e.disabled);e.disabled=true;}}
  else{for(const [e,disabled] of busyControls){if(e.isConnected)e.disabled=disabled;}busyControls.clear();$('#people-minus').disabled=state.people<=1;$('#quick-pick').disabled=!candidates().length;}
  $('.play-board').setAttribute('aria-busy',String(value));
  $('#board-status').innerHTML=value?'<i class="live-dot"></i> PICKING YOUR LUNCH…':state.result?'<i class="live-dot"></i> LUNCH DECIDED!':'<i class="live-dot"></i> READY TO PLAY';
}
function updateProfile(){ $('#profile-label').textContent=state.profile||'게스트'; $('.avatar').textContent=state.profile?state.profile.slice(0,1):'G'; $('#saved-count').textContent=state.favorites.length; }
function updateProgress(){
  const step=state.view==='restaurants'?(state.result?(state.route?3:2):1):1;
  $$('.progress-step').forEach(e=>e.classList.toggle('active',Number(e.dataset.step)===step));
  const decisionStep=state.route?5:state.view==='restaurants'?(state.restaurantDrawDone?4:3):state.result?3:state.aiReady?2:1;
  $$('#decision-steps > span').forEach((e,i)=>{e.classList.toggle('is-current',i+1===decisionStep);e.classList.toggle('is-done',i+1<decisionStep);});
}
function syncFilters(){
  const budgetMin=1000,budgetMax=100000;$('#budget').min=budgetMin;$('#budget').max=budgetMax;$('#budget').step=state.budget%1000===0?1000:1;
  $('#budget').value=state.budget; $('#budget-value').textContent=won(state.budget); $('#distance').min=50;$('#distance').max=500;$('#distance').step=50;$('#lunch-time').min=1;$('#lunch-time').max=120;$('#distance').value=String(state.distance); $('#people-count').textContent=state.people;$('#lunch-time').value=state.time;$('#time-value').textContent=state.time;$('#distance-value').textContent=state.distance;$('#lunch-time').style.setProperty('background',`linear-gradient(to right,#FF641B ${state.time/120*100}%,#DDE4ED ${100-state.time/120*100}%)`);$('#distance').style.setProperty('background',`linear-gradient(to right,#FF641B ${state.distance/500*100}%,#DDE4ED ${100-state.distance/500*100}%)`);
  $('#location').textContent=state.selectedLocation?.name||'위치 설정';
  $('#location').title=state.selectedLocation?.address||'현재 위치 또는 주소·장소로 설정';
  $('.location-note').textContent=state.selectedLocation?.address||'현재 위치 또는 주소·장소 검색으로 출발점을 선택하세요.';
  $$('.range-ends span').forEach((e,i)=>e.textContent=won(i?budgetMax:budgetMin)+'원');
  $('#budget').style.setProperty('--range-progress',`${(state.budget-budgetMin)/(budgetMax-budgetMin)*100}%`);
  const timeOptions=$('#time-options'); const custom=timeOptions.querySelector('[data-custom]'); if(custom)custom.remove();
  if(![30,45,60,90].includes(state.time))timeOptions.insertAdjacentHTML('beforeend',`<button type="button" data-time="${state.time}" data-custom>${state.time}분</button>`);
  $$('#time-options button').forEach(e=>{e.classList.toggle('selected',Number(e.dataset.time)===state.time);e.setAttribute('aria-pressed',String(Number(e.dataset.time)===state.time));});
  $$('#category-options button').forEach(e=>{const active=e.dataset.category==='전체'?state.categories.length===0:state.categories.includes(e.dataset.category); e.classList.toggle('active',active);e.setAttribute('aria-pressed',String(active));});
  $('#people-hint').textContent=state.people===1?'혼자도 좋아요':`룰렛 최대 12명 · 사다리 최대 8명`;
  $('#people-minus').disabled=state.people===1;
}
function resetRestaurantDraw(){state.restaurantCandidates=null;state.unverifiedRestaurants=[];state.searchMessage='';state.restaurantDrawDone=false;state.restaurantSpotlight=-1;state.restaurantDrawing=false;}
function conditionsChanged(){if(state.busy)return;saveGame();shared.setMenu(null);poolController?.abort();++poolVersion;MENUS=[];clearTimeout(poolTimer);poolTimer=setTimeout(refreshCandidates,200);resetRound();state.result=null;state.pending=null;state.route=false;state.selectedRestaurant=0;state.ladder=null;state.aiReady=false;gs.entries=[];gs.menus=[];resetRestaurantDraw();syncFilters();render();}
function render(){
  saveGame();updateProgress();
  const pool=candidates(); $('#candidate-count').textContent=`${pool.length}개`; $('#pool-count').textContent=pool.length;
  $('#menu-pool').innerHTML=pool.length?pool.map(m=>`<button class="menu-chip" data-detail="${m.id}"><span>${m.emoji}</span><span>${esc(m.name)}</span><small>${esc(m.category)}</small></button>`).join(''):'<div class="empty-state"><span>⌕</span><h3>조건에 맞는 메뉴가 없어요</h3><p>예산·시간·거리를 조금 늘리거나<br>카테고리를 바꿔보세요.</p><button class="secondary" data-action="reset">조건 초기화</button></div>';
  $('#quick-pick').disabled=!pool.length;
  renderGame(pool);renderSuggestions(pool);if(state.view==='restaurants')renderRestaurants();if(state.view==='saved')renderSaved();
}
function renderGame(pool){
 saveGame();
 ensureGroup(pool);
  updateProgress();
  const types=state.mode==='group'?['roulette','ladder','intersection']:state.mode==='ai'?[]:['draw','gacha','ticket','random'];
  $$('.mode-tabs button').forEach(e=>{e.classList.toggle('active',e.dataset.mode===state.mode);e.setAttribute('aria-pressed',String(e.dataset.mode===state.mode));});
  $('#game-options').hidden=state.mode==='ai';
  $('#game-options').innerHTML=types.map(k=>`<button class="game-option ${state.game===k?'active':''}" data-game="${k}" aria-pressed="${state.game===k}"><span class="game-option-icon">${games[k].icon}</span><span><strong>${games[k].name}</strong><small>${games[k].sub}</small></span><span class="game-option-check">${state.game===k?'✓':'↗'}</span></button>`).join('');
  const group=$('#group-settings');group.hidden=state.mode!=='group';
  document.body.classList.toggle('intersection-mode',state.mode==='group'&&state.game==='intersection');
  if(state.mode==='group'&&state.game==='intersection'){
    group.hidden=true;$('#game-badge').textContent='OUR INTERSECTION · DEMO 3';$('#board-status').textContent='NICKNAME ONLY';$('#game-actions').innerHTML='';$('#game-footnote').textContent='방의 점심 조건은 생성 시 고정돼요. 각자 다른 휴대폰에서 메뉴를 선택해 보세요.';
    mountRoomFlow($('#game-stage'),{onContext:roomContext,getFilters:()=>({location:state.location,origin:state.origin,selectedLocation:state.selectedLocation,lunchDeadline:state.lunchDeadline,budget:state.budget,time:state.time,distance:state.distance,categories:[...state.categories]}),onChoose:async(id,filters,people)=>{Object.assign(state,filters);state.people=people||state.people;state.mode='solo';state.game='gacha';syncFilters();finish(gameMenu(id));await findRestaurants();}});return;
  }
  closeRoomFlow();

  if(state.mode==='group')group.innerHTML=`<div class="group-line"><label>${state.game==='roulette'?'룰렛 입력값':'참가자 이름'} · ${state.people}명</label></div><div class="participant-inputs">${Array.from({length:state.people},(_,i)=>`<input class="field" ${state.game==='roulette'?'data-entry':'data-name'}="${i}" aria-label="${state.game==='roulette'?'룰렛 입력값':'참가자 이름'} ${i+1}" maxlength="60" value="${esc(state.game==='roulette'?gs.entries[i]:state.names[i])}" ${gs.started&&state.game==='ladder'?'disabled':''}>`).join('')}</div>`;

  $('#game-badge').textContent=state.mode==='ai'?'SMART LUNCH ASSISTANT':games[state.game].badge;
  $('#game-footnote').textContent=pool.length===0?'조건에 맞는 메뉴가 없어요. 예산·음식 종류·반경을 확인해주세요.':pool.length===1?'조건에 맞는 메뉴가 1개예요. 이 메뉴로 결정해 볼까요?':'조건에 맞는 메뉴만 담았어요. 마음 편히 뽑아보세요!';
  if(state.mode==='group')$('#game-footnote').textContent='입력한 값으로 추첨해요. 현재 조건의 백엔드 후보 메뉴명과 일치하는 당첨값만 식당 탐색에 연결돼요.';
  if(state.result){renderResult();return;}
  if(state.mode==='ai'){renderAI();return;}window.LunchRunChat.close();
  const name=games[state.game].name;
  let html=`<div class="stage-heading"><h3>${state.game==='gacha'?'돌려볼까요, 맛있는 행운?':state.game==='draw'?'마음이 가는 한 장을 골라보세요':state.game==='ticket'?'오늘의 행운은 어느 티켓에?':state.game==='roulette'?'우리의 점심을 돌려봐요':state.game==='ladder'?'출발할 친구를 선택해 주세요':'오늘은 어떤 게임이 기다릴까요?'}</h3><p>${state.mode==='group'?'모두 함께 먹을 메뉴 하나를 정해요.':'작은 설렘 하나로, 점심 고민 끝.'}</p></div>`;
  if(state.game==='gacha') html+=state.pending?`<div class="capsule-reveal"><div class="capsule-glow"></div><button class="open-capsule" data-action="open-capsule" aria-label="뽑은 캡슐 열기"><span class="capsule-top"></span><span class="capsule-bottom">?</span></button><h3>두근두근, 캡슐이 나왔어요!</h3><p>캡슐을 눌러 오늘의 메뉴를 확인해 보세요</p></div>`:gachaArt();
  if(state.game==='draw')html+=`<div class="draw-grid">${Array.from({length:6},(_,i)=>`<button class="draw-card" data-draw="${i}" ${!pool.length?'disabled':''}><span>✳</span><strong>?</strong><small>LUNCH ${String(i+1).padStart(2,'0')}</small></button>`).join('')}</div>`;
  if(state.game==='ticket')html+=`<div class="ticket-stack">${['GOOD LUCK','YUMMY DAY','HAPPY LUNCH'].map((t,i)=>`<button class="lucky-ticket" data-ticket="${i}" ${!pool.length?'disabled':''}><span>★ LUNCH RUN LOTTERY ★</span><strong>${t}</strong><small>눌러서 행운 확인하기 <b>↗</b></small></button>`).join('')}</div>`;
  if(state.game==='random')html+=`<div class="random-scene"><span class="random-orbit"></span><div class="big-dice">⚄</div><span class="random-label">LET LUCK CHOOSE THE GAME</span></div>`;
  if(state.game==='roulette')html+=wheelArt(gs.entries.slice(0,state.people).map(name=>({name})));
  if(state.game==='ladder'){if(!state.ladder)state.ladder=buildLadder(state.people);html+=ladderArt(pool);}
  $('#game-stage').innerHTML=html;
  const action=state.game==='gacha'?(state.pending?'캡슐 열어보기':'캡슐 뽑기'):state.game==='roulette'?'룰렛 돌리기':state.game==='ladder'?'사다리 출발!':state.game==='random'?'랜덤 게임 시작':'위에서 하나를 골라주세요';
  if(state.game==='ladder'){$('#game-actions').innerHTML='<span>참가자를 누른 순서대로 진행해요</span><button class="secondary" data-action="reset-ladder">새 사다리</button>';return;}
  $('#game-actions').innerHTML=['draw','ticket'].includes(state.game)?`<span class="interaction-hint">↑ ${state.game==='draw'?'카드':'티켓'}를 직접 눌러보세요</span>`:`<button class="primary play-cta" data-action="${state.pending?'open-capsule':'play'}" ${!pool.length?'disabled':''}>${games[state.game].icon} ${action}<span>↗</span></button>`;
}
function gachaArt(){return `<div class="machine-scene"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><span class="float-food food-one">🍜</span><span class="float-food food-two">🍔</span><span class="float-food food-three">🍚</span><span class="machine-spark spark-one">✳</span><span class="machine-spark spark-two">+</span><svg class="gacha-machine" width="232" height="280" viewBox="0 0 232 280" role="img" aria-label="오렌지색 점심 캡슐 뽑기 기계"><defs><linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#9cb5d8" stop-opacity=".19"/><stop offset="1" stop-color="#547495" stop-opacity=".03"/></linearGradient><linearGradient id="orange" x2=".8" y2="1"><stop stop-color="#ff843d"/><stop offset="1" stop-color="#ff5713"/></linearGradient><clipPath id="bowl"><path d="M45 49 Q116 18 187 49 L187 130 Q181 164 116 164 Q51 164 45 130Z"/></clipPath></defs><ellipse cx="116" cy="268" rx="91" ry="10" fill="#000" opacity=".22"/><path d="M45 49 Q116 18 187 49 L187 130 Q181 164 116 164 Q51 164 45 130Z" fill="url(#glass)" stroke="#7391b7" stroke-width="2"/><g clip-path="url(#bowl)"><g transform="translate(80 125) rotate(-25)"><circle r="24" fill="#c5ff24"/><path d="M-24 0H24" stroke="#759913" stroke-width="2"/><path d="M-15 -13q7 -8 15 -7" fill="none" stroke="white" opacity=".65" stroke-width="4" stroke-linecap="round"/></g><g transform="translate(130 123) rotate(20)"><circle r="24" fill="#ff7128"/><path d="M-24 0H24" stroke="#ad3f0a" stroke-width="2"/></g><g transform="translate(167 102) rotate(-30)"><circle r="22" fill="#b6c9ff"/><path d="M-22 0H22" stroke="#788bc0" stroke-width="2"/></g><g transform="translate(111 82) rotate(30)"><circle r="22" fill="#d8e5f7"/><path d="M-22 0H22" stroke="#95a9c5" stroke-width="2"/><path d="M-13 -12q5 -6 12 -6" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"/></g><g transform="translate(58 91) rotate(50)"><circle r="21" fill="#ffb2cb"/><path d="M-21 0H21" stroke="#bf7596" stroke-width="2"/></g><g transform="translate(151 65) rotate(-10)"><circle r="20" fill="#c5ff24"/><path d="M-20 0H20" stroke="#7ea020" stroke-width="2"/></g></g><path d="M58 58v53" stroke="white" opacity=".25" stroke-width="5" stroke-linecap="round"/><path d="M39 48Q116 20 193 48L191 56Q116 32 41 56Z" fill="#ff752d"/><rect x="74" y="25" width="84" height="14" rx="7" fill="#ff7c32"/><path d="M45 153H187L201 245Q202 258 188 258H44Q30 258 31 245Z" fill="url(#orange)"/><path d="M47 160H185" stroke="#ffac75" stroke-width="3"/><rect x="58" y="172" width="116" height="22" rx="4" fill="#112039"/><text x="116" y="187" fill="#c5ff24" font-family="Arial,sans-serif" font-size="11" font-weight="900" text-anchor="middle" letter-spacing="2">LUNCH CAPSULE</text><circle cx="116" cy="215" r="19" fill="#d94912"/><circle cx="116" cy="214" r="15" fill="#dbe6f4" stroke="#19283b" stroke-width="2"/><rect x="98" y="210" width="36" height="8" rx="4" fill="#243754" transform="rotate(-28 116 214)"/><rect x="153" y="205" width="17" height="5" rx="2" fill="#9e360e"/><path d="M85 258v-13q31-14 62 0v13" fill="#182740"/><rect x="38" y="257" width="156" height="9" rx="4" fill="#df4b12"/></svg><span class="machine-caption">A CAPSULE FULL OF POSSIBILITIES</span></div>`;}
function wheelArt(pool){const n=pool.length||1,colors=['#FF641B','#233550','#C5FF24','#354863','#FF9A63','#466143'];const paths=pool.map((m,i)=>{const a=i/n*Math.PI*2-Math.PI/2,b=(i+1)/n*Math.PI*2-Math.PI/2,mid=(a+b)/2;const point=t=>`${160+145*Math.cos(t)},${160+145*Math.sin(t)}`;return `<path d="M160,160 L${point(a)} A145,145 0 ${n===1?1:0},1 ${point(b)} Z" fill="${colors[i%colors.length]}" stroke="#0C1426" stroke-width="2"/><text x="${160+102*Math.cos(mid)}" y="${160+102*Math.sin(mid)}" fill="${i%colors.length===2?'#142331':'#fff'}" font-size="${n>16?10:12}" font-weight="700" text-anchor="middle" dominant-baseline="central" transform="rotate(${mid*180/Math.PI+90},${160+102*Math.cos(mid)},${160+102*Math.sin(mid)})">${esc(m.name.slice(0,6))}</text>`;}).join('');return `<div class="wheel-scene"><span class="wheel-pointer">▼</span><svg class="roulette-wheel" viewBox="0 0 320 320" role="img" aria-label="${pool.length}개 메뉴가 담긴 룰렛"><circle cx="160" cy="160" r="155" fill="#17243B" stroke="#d0deee" stroke-width="3"/>${n===1&&pool.length?'<circle cx="160" cy="160" r="145" fill="#FF641B"/>':''}${paths}</svg><span class="wheel-center">LUNCH<br>RUN ↗</span></div>`;}
const gs={entries:[],menus:[],queue:[],played:[],started:false,running:false,winningEnd:null,current:null,log:[]};
function ensureGroup(pool){for(let i=0;i<state.people;i++){const menu=pool.length?pool[i%pool.length]:null;if(gs.entries[i]===undefined)gs.entries[i]=menu?.name||'';if(gs.menus[i]===undefined)gs.menus[i]=menu?.name||'';}}
function resetRound(){gs.queue=[];gs.played=[];gs.started=false;gs.running=false;gs.winningEnd=null;gs.current=null;gs.log=[];state.ladder=null;}
function entryResult(name){const menu=matchEntry(name,candidates());if(!menu)throw Error('현재 조건의 후보 메뉴명만 입력해주세요.');return menu;}
function validateEntries(entries){return entries.every(name=>Boolean(matchEntry(name,candidates())));}
function ladderArt(pool){const l=state.ladder,x=i=>45+i*510/(state.people-1),y=r=>25+r*175/(l.rows+1);return `<div class="ladder-wrap"><p>위쪽 메뉴를 설정하고 참가자를 클릭하세요. 한 도착점만 당첨, 나머지는 꽝입니다.</p><div class="ladder-menu-grid" style="--count:${state.people}">${Array.from({length:state.people},(_,i)=>`<label>메뉴 ${i+1}<input class="field" data-ladder-menu="${i}" aria-label="사다리 메뉴 ${i+1}" value="${esc(gs.menus[i])}" maxlength="60" ${gs.started?'disabled':''}></label>`).join('')}</div><div class="ladder-starts">${state.names.slice(0,state.people).map((n,i)=>`<button data-ladder-start="${i}" ${gs.played.includes(i)||gs.queue.includes(i)?'disabled':''}>${esc(n||`참가자 ${i+1}`)}${gs.played.includes(i)?' · 완료':gs.queue.includes(i)?' · 대기':''}</button>`).join('')}</div><svg class="ladder-svg" viewBox="0 0 600 240" role="img" aria-label="${state.people}명 사다리"><g stroke="#7890a8" stroke-width="3" fill="none">${Array.from({length:state.people},(_,i)=>`<path d="M${x(i)} ${y(0)}V${y(l.rows+1)}"/>`).join('')}${l.rungs.map(r=>`<path d="M${x(r.col)} ${y(r.row)}H${x(r.col+1)}"/>`).join('')}</g><path id="ladder-trace" stroke="#FF641B" stroke-width="5" fill="none"/>${Array.from({length:state.people},(_,i)=>`<text x="${x(i)}" y="228" text-anchor="middle" fill="#829947" font-size="12">${gs.started?(i===gs.winningEnd?'당첨':'꽝'):'?'}</text>`).join('')}</svg><div class="ladder-log" role="status">${gs.log.map(esc).join('<br>')||'아직 출발한 참가자가 없어요.'}</div></div>`;}
function queueButtons(){for(const e of $$('[data-ladder-start]')){let i=Number(e.dataset.ladderStart);e.disabled=gs.played.includes(i)||gs.queue.includes(i);e.textContent=(state.names[i]||`참가자 ${i+1}`)+(gs.current===i?' · 진행 중':gs.played.includes(i)?' · 완료':gs.queue.includes(i)?' · 대기':'');}}
async function queueLadder(start){
 const roundVersion=poolVersion;
 try{validateGamePool();}catch(error){toast(error.message);return;}
 if(state.game!=='ladder'||state.result||gs.played.includes(start)||gs.queue.includes(start))return;
 if(gs.menus.slice(0,state.people).some(v=>!v.trim())){toast('모든 메뉴를 입력해 주세요.');return;}
 if(!validateEntries(gs.menus.slice(0,state.people))){toast('모든 입력 메뉴가 현재 조건의 후보에 포함되어야 해요.');return;}
 gs.queue.push(start);queueButtons();if(gs.running)return;gs.running=true;
 try{if(!gs.started){gs.started=true;gs.winningEnd=randomIndex(state.people);}
 while(gs.queue.length&&!state.result){const next=gs.queue.shift();gs.played.push(next);gs.current=next;renderGame(candidates());setBusy(true);queueButtons();const t=state.ladder.trace(next),x=i=>45+i*510/(state.people-1),y=r=>25+r*175/(state.ladder.rows+1),path=$('#ladder-trace');path.setAttribute('d',t.points.map((v,i)=>`${i?'L':'M'}${x(v.x)},${y(v.y)}`).join(' '));let len=path.getTotalLength();path.style.strokeDasharray=len;path.style.strokeDashoffset=len;path.getBoundingClientRect();path.style.transition='stroke-dashoffset 1.5s linear';path.style.strokeDashoffset=0;await delay(1600);if(roundVersion!==poolVersion)return;setBusy(false);gs.current=null;let won=t.end===gs.winningEnd;gs.log.push(`${gs.played.length}번째 · ${state.names[next]} · ${gs.menus[next]} → ${won?'당첨!':'꽝'}`);if(won){gs.queue=[];finish(entryResult(gs.menus[next].trim()));$('#game-stage').insertAdjacentHTML('beforeend','<div class="ladder-log" role="status">'+gs.log.map(esc).join('<br>')+'</div>');break;}renderGame(candidates());}
 }finally{if(roundVersion===poolVersion){gs.running=false;if(state.busy)setBusy(false);}}
}
function renderResult(){const m=state.result;if(m.entryOnly){$('#board-status').textContent='입력값 당첨!';$('#game-stage').innerHTML=`<div class="result-scene"><span class="result-kicker">입력값 당첨</span><h3 class="result-title">${esc(m.name)}</h3><p>${esc(m.desc)}</p></div>`;$('#game-actions').innerHTML='<button class="secondary" data-action="again">한 번 더</button>';return;}$('#board-status').innerHTML='<i class="live-dot"></i> LUNCH DECIDED!';$('#game-stage').innerHTML=`<div class="result-scene"><div class="confetti">✳ <span>✦</span> ✳</div><span class="result-kicker">TODAY’S LUCKY LUNCH</span><div class="result-emoji">${m.emoji}</div><h3 class="result-title">${esc(m.name)}</h3><p class="result-desc">${esc(m.desc)}</p><div class="result-stats">${menuStats(m)}</div><p class="result-note">선택 조건의 메뉴 후보입니다. 실제 가격·영업 여부는 식당 검색 후 확인해요.${state.people>1?`<br>${state.people}명이 함께 먹을 오늘의 공통 메뉴!`:''}</p></div>`;$('#game-actions').innerHTML='<button class="secondary" data-action="again">↻ 한 번 더</button><button class="primary" data-action="find">이 메뉴로 식당 찾기 ↗</button>';$('#game-footnote').textContent='메뉴가 마음에 들면, 근처 식당을 골라보세요.';}
async function play(source){
  if(state.busy)return;validateGamePool();const roundVersion=poolVersion;if(state.mode==='group'&&state.game==='roulette'){const entries=gs.entries.slice(0,state.people).map(v=>v.trim());if(entries.some(v=>!v)){toast('입력값을 모두 채워주세요.');return;}if(!validateEntries(entries)){toast('현재 조건의 후보 메뉴명만 입력해주세요.');return;}const i=randomIndex(entries.length);setBusy(true);try{$('.roulette-wheel').style.transform=`rotate(${360*5+360-(i+.5)*360/entries.length}deg)`;await delay(2100);if(roundVersion!==poolVersion)return;finish(entryResult(entries[i]));}finally{if(roundVersion===poolVersion)setBusy(false);}return;}const pool=candidates();if(!pool.length){toast('먼저 추천 조건을 조금 넓혀주세요.');return;}
  if(state.game==='random'){state.game=['draw','gacha','ticket'][randomIndex(3)];renderGame(pool);toast(`${games[state.game].name} 당첨! 이 게임으로 골라볼까요?`);return;}
  const m=pickMenu(pool,state.previous);setBusy(true);
  try {
    if(state.game==='gacha'){ $('.gacha-machine')?.classList.add('spinning');await delay(1250);if(roundVersion!==poolVersion)return;state.pending=m;renderGame(pool);return; }
    if(state.game==='roulette'){const idx=pool.findIndex(x=>x.id===m.id);const angle=360*5+360-(idx+.5)*360/pool.length;$('.roulette-wheel').style.transform=`rotate(${angle}deg)`;await delay(2050);}
    else if(state.game==='ladder'){
      const l=state.ladder,t=l.trace(state.ladderStart),x=i=>45+i*510/(state.people-1),y=r=>25+r*175/(l.rows+1);
      const p=$('#ladder-trace');p.setAttribute('d',t.points.map((v,i)=>`${i?'L':'M'}${x(v.x)},${y(v.y)}`).join(' '));const len=p.getTotalLength();p.style.strokeDasharray=len;p.style.strokeDashoffset=len;p.getBoundingClientRect();p.style.transition='stroke-dashoffset 1.7s ease';p.style.strokeDashoffset=0;
      const labels=Array.from({length:state.people},(_,i)=>i===t.end?m:pool[randomIndex(pool.length)]);$$('.ladder-svg text').forEach((e,i)=>{e.textContent=labels[i].name;e.style.fill=i===t.end?'#C5FF24':'#a6b7ca';e.style.fontSize='11px';});await delay(2100);
    } else {source?.classList.add('flipping');await delay(650);}
    if(roundVersion!==poolVersion)return;finish(m);
  }finally{if(roundVersion===poolVersion)setBusy(false);}
}
function finish(m){saveGame();shared.setMenu(m);resetRestaurantDraw();state.result=m;state.pending=null;state.previous=m.id;state.selectedRestaurant=0;state.route=false;renderGame(candidates());}
function renderSuggestions(pool){$('#suggestion-grid').innerHTML=pool.slice(0,3).map((m,i)=>`<article class="suggestion-card"><button class="save-btn ${state.favorites.includes(m.id)?'saved':''}" data-save="${m.id}" aria-label="${esc(m.name)} ${state.favorites.includes(m.id)?'찜 해제':'찜하기'}">${state.favorites.includes(m.id)?'♥':'♡'}</button><button class="food-art art-${i}" data-detail="${m.id}" aria-label="${esc(m.name)} 자세히 보기"><span>${m.emoji}</span><small>${esc(m.category)} PICKS</small></button><div class="suggestion-content"><span class="menu-category">${esc(m.category)} <i>·</i> 오늘의 후보</span><h3><button data-detail="${m.id}">${esc(m.name)} <span>↗</span></button></h3><p>${esc(m.desc)}</p><div class="menu-meta">${menuStats(m)}</div></div></article>`).join('')||'<div class="empty-state"><p>조건을 바꾸면 새로운 메뉴가 나타나요.</p></div>';}
function renderAI(){
 const stage=$('#game-stage');
 if(!stage.querySelector('#game-chat')){window.LunchRunChat.close();stage.innerHTML='<div class="ai-panel"><span class="ai-symbol">✦</span><h3>지금 나에게 맞는 점심</h3><div id="game-chat"></div></div>';}
 window.LunchRunChat.mount($('#game-chat'),{onState:()=>{applySharedGame();syncFilters();}});
 $('#game-actions').innerHTML='';
 $('#game-footnote').textContent='메뉴 추천 → 요청 시 식당 검색 → 카카오 지도 확인';
}
function aiRecommend(){renderAI();}

async function drawAiMenu(){
  const pool=Object.freeze(candidates().slice());if(state.busy||!state.aiReady||!pool.length)return;
  const chosen=pool[randomIndex(pool.length)];setBusy(true);
  try{await delay(900);finish(chosen);toast('메뉴 결정! 이제 이 메뉴를 파는 식당을 뽑아보세요.');}finally{setBusy(false);}
}

function switchView(view){if(state.busy)return;if(view==='restaurants'){saveGame();location.assign('/map/');return;}if(view!==state.view){window.LunchRunChat.close();cancelGameRequests();window.LunchRunLocationPicker.close();}state.view=view;saveGame();if(view!=='game')closeRoomFlow();state.view=view;$$('.view').forEach(e=>e.hidden=e.id!==`view-${view}`);$$('.nav-item').forEach(e=>e.classList.toggle('active',e.dataset.view===view));$$('.progress-step').forEach(e=>e.classList.toggle('active',Number(e.dataset.step)===(view==='restaurants'?(state.route?3:2):1)));if(view==='restaurants')renderRestaurants();if(view==='saved')renderSaved();if(view==='game'&&state.game==='intersection')renderGame(candidates());}
function restaurants(){return state.restaurantCandidates||[];}

function restaurantDrawPanel(rs){
  const selected=rs[state.selectedRestaurant],done=state.restaurantDrawDone;
  return `<section class="restaurant-draw-panel ${state.restaurantDrawing?'is-drawing':''}" aria-labelledby="restaurant-draw-title"><div class="restaurant-draw-heading"><span class="draw-step-label">STEP 02 · RESTAURANT DRAW</span><h2 id="restaurant-draw-title">메뉴는 그대로, 식당도 운명에게!</h2><p>${state.result.emoji} ${esc(state.result.name)}을 파는 검색 식당 ${rs.length}곳. A부터 차례로 불이 켜지고, 점점 느려지다 한 곳에 멈춰요.</p></div><div class="restaurant-draw-candidates">${rs.map((r,i)=>`<button class="draw-restaurant ${done&&i===state.selectedRestaurant?'is-winner':''}" data-restaurant="${i}" aria-label="${(i<26?String.fromCharCode(65+i):String(i+1))} 후보 ${esc(r.name)} 선택" aria-pressed="${done&&i===state.selectedRestaurant}"><span class="draw-letter">${(i<26?String.fromCharCode(65+i):String(i+1))}</span><strong class="draw-place-name">${esc(r.name)}</strong><span class="draw-place-meta">${won(r.price)}원 · 도보 ${(r.walk_minutes??'미확인')}분</span><span class="draw-winner-tag">${done&&i===state.selectedRestaurant?'당첨! 오늘의 목적지':'당첨 확률 1/'+rs.length}</span></button>`).join('')}</div><div class="restaurant-draw-footer"><p class="restaurant-draw-status" role="status" aria-live="polite">${state.restaurantDrawing?'후보 목록을 고정했어요. 불빛이 멈출 곳을 기다려주세요.':done&&selected?String.fromCharCode(65+state.selectedRestaurant)+' · '+esc(selected.name)+' 당첨! 메뉴는 '+esc(state.result.name)+' 그대로예요.':rs.length===1?'조건에 맞는 식당이 1곳이에요. 추첨으로 이 식당을 확정해요.':'모든 후보에 같은 당첨 기회를! 마음에 들 때까지 식당만 다시 뽑을 수 있어요.'}</p><button class="primary" data-action="random-restaurant" ${!rs.length||state.restaurantDrawing?'disabled':''}>${state.restaurantDrawing?'식당 추첨 중…':done?'↻ 한 번 더! 식당만 다시 뽑기':'⚄ 식당 랜덤 추첨'} <span>↗</span></button></div><p class="restaurant-draw-note micro">추첨 중 조건·후보 고정 · 재추첨도 모든 후보 1/${rs.length||1} · 직전 식당이 다시 나올 수 있어요.</p></section>`;
}
function renderRestaurants(){
 saveGame();
  updateProgress();const host=$('#view-restaurants');host.setAttribute('aria-busy',String(state.restaurantDrawing));
  if(!state.result){host.innerHTML='<div class="view-heading"><span class="section-index">02 / FIND YOUR PLACE</span><h1>맛있는 목적지를 찾아요</h1><p>메뉴를 먼저 고르면, 그 메뉴를 파는 식당을 보여드려요.</p></div><div class="empty-state large-empty"><span>⌖</span><h2>오늘의 메뉴부터 정해볼까요?</h2><p>AI 후보에서 메뉴를 뽑거나, 게임으로 직접 결정해 보세요.</p><button class="primary" data-action="back-game">메뉴 고르러 가기 ↗</button></div>';return;}
  const m=state.result,rs=restaurants();if(state.selectedRestaurant>=rs.length)state.selectedRestaurant=0;const selected=rs[state.selectedRestaurant];
  host.innerHTML=`<div class="view-heading"><span class="section-index">TWO PICKS, ONE LUNCH · 02</span><h1>메뉴는 <span>${esc(m.name)}</span>, 식당도 뽑아볼까요?</h1><p>메뉴 추첨 완료 → 주변 검색 식당 확인 → 식당 추첨 → 동선 확인</p></div><div class="restaurant-toolbar"><span class="result-pill">${m.emoji} ${esc(m.name)}</span><span>예산 ${won(state.budget)}원 · ${state.time}분 · ${state.people}명</span><button class="secondary" data-action="back-game">메뉴 다시 고르기 ↻</button></div><div class="demo-notice">${esc(state.searchMessage||'식당 찾기를 누르면 실제 검색 결과를 표시합니다.')} 확인 필요 후보 ${state.unverifiedRestaurants?.length||0}곳은 추첨에서 제외합니다.</div>${rs.length?restaurantDrawPanel(rs):'<div class="empty-state"><h2>조건에 맞는 식당이 없어요</h2><p>메뉴를 바꾸거나 추천 조건을 넓혀주세요.</p></div>'}<div class="restaurant-layout"><div class="restaurant-list"><div class="restaurant-list-title"><h3>주변 식당 <span>${rs.length}</span></h3><span class="micro">목록과 지도에서 직접 선택도 가능해요</span></div>${rs.map((r,i)=>`<button class="restaurant-card ${!state.restaurantDrawing&&i===state.selectedRestaurant?'active':''}" data-restaurant="${i}"><span class="restaurant-emoji">${r.emoji}</span><div class="restaurant-info"><small>${(i<26?String.fromCharCode(65+i):String(i+1))} · 검색 식당 · ${esc(m.category)}</small><h3>${esc(r.name)}</h3><p>대표 메뉴 ${esc(r.menu)}</p><div class="restaurant-meta"><span>${won(r.price)}원</span><span>${r.distance}m · 도보 ${(r.walk_minutes??'미확인')}분</span></div></div><span class="restaurant-check">${!state.restaurantDrawing&&i===state.selectedRestaurant?'✓':'↗'}</span></button>`).join('')}</div><div class="map-panel">${mapArt(rs)}<span class="map-label">⌖ ${esc(state.location)} 주변 · 예시 지도</span><div class="map-legend"><span>● 출발 위치</span><span>● 선택한 식당</span></div></div></div>${selected?routePanel(selected):''}`;
}
const restaurantMarkers=[[425,167],[225,135],[455,315],[145,325],[535,95]];
function mapArt(rs){const markers=rs.map((r,i)=>restaurantMarkers[i]||[80+(i%6)*95,80+Math.floor(i/6)%3*115]);return `<svg class="demo-map" viewBox="0 0 650 430" role="group" aria-label="검색 식당 ${rs.length}곳과 출발점이 표시된 지도"><defs><pattern id="map-grid" width="110" height="95" patternUnits="userSpaceOnUse"><rect x="10" y="10" width="86" height="71" rx="10" fill="#20334a" stroke="#2b4059"/></pattern></defs><rect width="650" height="430" fill="#142138"/><rect width="650" height="430" fill="url(#map-grid)"/><path d="M-20 330L680 110" stroke="#3a5166" stroke-width="37"/><path d="M-20 330L680 110" stroke="#a0aa75" stroke-width="1.5" stroke-dasharray="8 9" opacity=".5"/><path d="M320 -10V440M-10 225H660" stroke="#3a5166" stroke-width="20"/><rect x="32" y="29" width="142" height="90" rx="25" fill="#233e3d"/><text x="103" y="79" fill="#69978c" text-anchor="middle" font-size="13">작은 공원</text><text x="337" y="75" fill="#7b91aa" font-size="13">${esc(state.location)} · 예시</text><text x="65" y="249" fill="#7b91aa" font-size="13">점심 산책길</text>${state.route?`<path d="M320 280V225H${markers[state.selectedRestaurant][0]}V${markers[state.selectedRestaurant][1]}" stroke="#C5FF24" stroke-width="5" stroke-linejoin="round" fill="none" stroke-dasharray="8 4"/>`:''}<circle cx="320" cy="280" r="22" fill="#6c9dff" opacity=".15"/><circle cx="320" cy="280" r="8" fill="#6c9dff" stroke="#e7f0ff" stroke-width="3"/><rect x="277" y="300" width="86" height="27" rx="13" fill="#0c1426"/><text x="320" y="318" text-anchor="middle" fill="#d5e4f8" font-size="12">출발 위치</text>${rs.map((r,i)=>`<g data-map-marker="${i}" class="map-marker" role="button" tabindex="${state.restaurantDrawing?'-1':'0'}" aria-disabled="${state.restaurantDrawing}" aria-label="${(i<26?String.fromCharCode(65+i):String(i+1))} ${esc(r.name)} 선택"><circle cx="${markers[i][0]}" cy="${markers[i][1]}" r="${!state.restaurantDrawing&&state.selectedRestaurant===i?26:21}" fill="${!state.restaurantDrawing&&state.selectedRestaurant===i?'#C5FF24':'#FF641B'}" stroke="#0c1426" stroke-width="4"/><text x="${markers[i][0]}" y="${markers[i][1]+6}" text-anchor="middle" fill="#142138" font-size="17" font-weight="800">${(i<26?String.fromCharCode(65+i):String(i+1))}</text></g>`).join('')}</svg>`;}
function routePanel(r){return `<section class="route-panel"><div class="route-summary"><span class="section-index">YOUR NEXT LUNCH STOP</span><h2>${esc(r.name)}</h2><p>실제 경로·도보시간은 지도 연결 단계에서 확인합니다.</p></div><div class="route-actions"><button class="secondary" data-save="${state.result.id}">♡ 이 메뉴 찜하기</button>${r.place_url?`<a class="primary" href="${esc(r.place_url)}" target="_blank" rel="noopener noreferrer">카카오맵 상세보기 ↗</a>`:''}</div></section>`;}
function lightRestaurant(index){
  state.restaurantSpotlight=index;
  $$('[data-restaurant]').forEach(e=>e.classList.toggle('is-lit',Number(e.dataset.restaurant)===index));
  $$('[data-map-marker]').forEach(e=>e.classList.toggle('is-lit',Number(e.dataset.mapMarker)===index));
}
async function drawRestaurant(){
  if(state.busy)return;
  const pool=restaurants();if(!pool.length){toast('먼저 메뉴를 고르거나 조건을 넓혀주세요.');return;}
  const chosen=randomIndex(pool.length),plan=createSpotlightPlan(pool.length,chosen);
  state.restaurantDrawing=true;state.restaurantDrawDone=false;state.route=false;state.restaurantSpotlight=-1;
  renderRestaurants();setBusy(true);
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  try{
    if(matchMedia('(prefers-reduced-motion: reduce)').matches){$('.restaurant-draw-status').textContent='후보를 고정했어요. 움직임 없이 5초 뒤 결과를 보여드려요.';await wait(5000);}
    else{for(const step of plan){lightRestaurant(step.index);await wait(step.delayMs);}}
    state.selectedRestaurant=chosen;state.restaurantDrawDone=true;state.restaurantSpotlight=chosen;
  }finally{state.restaurantDrawing=false;setBusy(false);renderRestaurants();}
}

function renderSaved(){const saved=MENUS.filter(m=>state.favorites.includes(m.id)),blocked=MENUS.filter(m=>state.blacklist.includes(m.id));$('#view-saved').innerHTML=`<div class="view-heading"><span class="section-index">MY LUNCH TASTE</span><h1>취향을 알면, 점심이 쉬워져요.</h1><p>이 브라우저에 저장한 찜과 제외 메뉴예요. 실제 계정과 동기화되지 않아요.</p></div><div class="saved-section"><h2>♡ 찜한 메뉴 <span>${saved.length}</span></h2><div class="saved-grid">${saved.map(m=>savedCard(m,false)).join('')||'<div class="empty-state"><h3>아직 찜한 메뉴가 없어요</h3><p>메뉴 카드의 하트를 눌러 취향을 모아보세요.</p><button class="secondary" data-action="back-game">메뉴 둘러보기 ↗</button></div>'}</div></div><div class="saved-section"><h2>⊘ 추천에서 제외 <span>${blocked.length}</span></h2><p class="micro">개인 추첨과 빠른 추천에서 제외됩니다. 교집합 모임방은 공동 후보를 사용합니다.</p><div class="saved-grid">${blocked.map(m=>savedCard(m,true)).join('')||'<div class="empty-state"><p>제외한 메뉴가 없어요. 메뉴 상세에서 설정할 수 있어요.</p></div>'}</div></div>`;}
function savedCard(m,blocked){return `<article class="saved-card"><span>${m.emoji}</span><div><small>${esc(m.category)}</small><h3>${esc(m.name)}</h3><p>${menuStats(m)}</p></div><button class="secondary" ${blocked?'data-block':'data-save'}="${m.id}">${blocked?'제외 해제':'찜 해제'}</button></article>`;}
function toggleSaved(id){state.favorites=state.favorites.includes(id)?state.favorites.filter(x=>x!==id):[...state.favorites,id];persist();render();toast(state.favorites.includes(id)?'나의 취향에 저장했어요.':'찜한 메뉴에서 해제했어요.');}
function detail(id){const m=candidates().find(x=>String(x.id)===String(id))||MENUS.find(x=>String(x.id)===String(id));if(!m)return;const eligible=candidates().some(x=>x.id===m.id);openDialog(`<div class="dialog-body menu-detail"><span class="detail-emoji">${m.emoji}</span><span class="section-index">${esc(m.category)} · MENU DETAIL</span><h2 id="dialog-title">${esc(m.name)}</h2><p>${esc(m.desc)}</p><div class="result-stats">${menuStats(m)}</div><p class="micro">실제 식당 가격과 영업 여부는 식당 검색 후 확인합니다. 이동·대기·식사시간은 아직 검증하지 않습니다.</p><div class="dialog-actions"><button class="secondary" data-save="${m.id}">${state.favorites.includes(m.id)?'♥ 찜 해제':'♡ 찜하기'}</button><button class="secondary" data-block="${m.id}">${state.blacklist.includes(m.id)?'제외 해제':'⊘ 추천에서 제외'}</button><button class="primary" data-choose="${m.id}" ${!eligible?'disabled':''}>${eligible?'이 메뉴로 선택 ↗':'현재 추천 조건 밖이에요'}</button></div></div>`);}
function openDialog(html){$('#dialog-content').innerHTML=html;if(!$('#app-dialog').open)$('#app-dialog').showModal();}
function profileDialog(){openDialog(`<div class="dialog-body"><span class="section-index">HELLO, LUNCH MATE</span><h2 id="dialog-title">${state.profile?'반가워요, '+esc(state.profile)+'님!':'나만의 점심 취향을 모아보세요'}</h2><p>회원 흐름을 미리 보는 로컬 데모예요.<br>SNS 로그인과 실제 회원가입은 연결하지 않았어요.</p><label for="nickname">어떻게 불러드릴까요?</label><input id="nickname" class="field" maxlength="12" placeholder="닉네임 (최대 12자)" value="${esc(state.profile)}"><p class="profile-note">닉네임·찜·제외 메뉴는 이 브라우저에만 저장돼요.<br>게스트도 모든 게임을 이용할 수 있어요.</p><div class="dialog-actions">${state.profile?'<button class="secondary" data-action="logout">게스트로 사용</button>':''}<button class="primary" data-action="login">닉네임 저장하고 시작하기 ↗</button></div></div>`);}

$('#lunch-time').addEventListener('input',e=>{if(state.busy)return;state.time=Number(e.target.value);conditionsChanged();});
$('#filters-form').addEventListener('submit',e=>e.preventDefault());
$('#budget').addEventListener('input',e=>{if(state.busy)return;state.budget=Number(e.target.value);conditionsChanged();});
$('#distance').addEventListener('input',e=>{if(state.busy)return;state.distance=Number(e.target.value);conditionsChanged();});
$('#location').addEventListener('click',()=>{
 if(state.busy)return;
 window.LunchRunLocationPicker.open(item=>{
  if(state.busy)return;
  state.selectedLocation={...item};state.location=item.name;state.origin=[item.lat,item.lng];
  state.view='game';conditionsChanged();switchView('game');
 },state.selectedLocation);
});
$('#profile-btn').addEventListener('click',profileDialog);
$('#close-dialog').addEventListener('click',()=>$('#app-dialog').close());
$('#app-dialog').addEventListener('click',e=>{if(e.target===$('#app-dialog'))$('#app-dialog').close();});
document.addEventListener('input',e=>{if(e.target.dataset.entry!==undefined){gs.entries[Number(e.target.dataset.entry)]=e.target.value;const wheel=$('.wheel-scene');if(wheel)wheel.outerHTML=wheelArt(gs.entries.slice(0,state.people).map(name=>({name})));}if(e.target.dataset.ladderMenu!==undefined&&!gs.started)gs.menus[Number(e.target.dataset.ladderMenu)]=e.target.value;if(e.target.dataset.name!==undefined)state.names[Number(e.target.dataset.name)]=e.target.value;});
document.addEventListener('keydown',e=>{if(state.busy)return;const marker=e.target.closest('[data-map-marker]');if(marker&&['Enter',' '].includes(e.key)){e.preventDefault();state.selectedRestaurant=Number(marker.dataset.mapMarker);state.restaurantDrawDone=false;state.route=false;renderRestaurants();}});
document.addEventListener('click', async e=>{
  const b=e.target.closest('button,[data-map-marker]');if(!b||b.disabled)return;if(b.dataset.ladderStart!==undefined){queueLadder(Number(b.dataset.ladderStart)).catch(error=>toast(error.message));return;}if(state.busy)return;
  const d=b.dataset;
  try{
  if(d.view){window.LunchRunLocationPicker.close();switchView(d.view);return;}
  if(d.time){state.time=Number(d.time);conditionsChanged();return;}
  if(d.category){const c=d.category;state.categories=c==='전체'||state.categories.includes(c)?[]:[c];conditionsChanged();return;}
  if(d.mode==='ai'){resetRound();state.mode='ai';saveGame();render();return;}if(d.mode){window.LunchRunChat.close();resetRound();state.mode=d.mode;state.game=d.mode==='group'?'roulette':'gacha';if(d.mode==='group'&&state.people<2)state.people=2;if(d.mode==='solo')state.people=1;state.ladderStart=0;conditionsChanged();return;}
  if(d.game){shared.setMenu(null);resetRestaurantDraw();resetRound();state.game=d.game;if(d.game==='ladder'&&state.people>8){state.people=8;toast('사다리는 최대 8명이 함께할 수 있어요.');}state.result=null;state.pending=null;state.ladder=null;state.ladderStart=0;syncFilters();renderGame(candidates());return;}
  if(b.id==='people-plus'||b.id==='people-minus'){const max=state.game==='ladder'&&state.mode==='group'?8:12;const next=state.people+(b.id==='people-plus'?1:-1);if(next>max){toast(`이 게임은 최대 ${max}명까지 참여할 수 있어요.`);return;}resetRound();state.people=Math.max(1,Math.min(max,next));if(state.people>1&&state.mode==='solo'){state.mode='group';state.game='roulette';}if(state.people===1&&state.mode==='group'){state.mode='solo';state.game='gacha';}state.ladderStart=0;conditionsChanged();return;}
  if(d.ladderStart!==undefined){state.ladderStart=Number(d.ladderStart);renderGame(candidates());return;}
  if(d.draw!==undefined||d.ticket!==undefined){await play(b);return;}
  if(d.prompt){$('#ai-prompt').value=d.prompt;return;}
  if(d.save!==undefined){const m=MENUS.find(x=>String(x.id)===d.save);if(m)toggleSaved(m.id);if($('#app-dialog').open)$('#app-dialog').close();return;}
  if(d.block!==undefined){const m=MENUS.find(x=>String(x.id)===d.block);if(!m)return;state.blacklist=state.blacklist.includes(m.id)?state.blacklist.filter(x=>x!==m.id):[...state.blacklist,m.id];persist();$('#app-dialog').close();conditionsChanged();toast('추천 제외 설정을 반영했어요.');return;}
  if(d.detail!==undefined){detail(d.detail);return;}
  if(d.choose!==undefined){const m=candidates().find(x=>String(x.id)===d.choose);if(m){finish(m);$('#app-dialog').close();switchView('game');}return;}
  if(d.restaurant!==undefined||d.mapMarker!==undefined){state.selectedRestaurant=Number(d.restaurant??d.mapMarker);state.restaurantDrawDone=false;state.route=false;renderRestaurants();return;}
  const action=d.action;
  if(b.id==='reset-filters'||action==='reset'){Object.assign(state,{budget:12000,time:45,distance:500,categories:[]});conditionsChanged();toast('추천 조건을 초기화했어요.');}
  if(b.id==='quick-pick'){validateGamePool();const m=pickMenu(candidates(),state.previous);if(m){finish(m);switchView('game');toast('조건에 맞는 메뉴를 빠르게 골랐어요.');}}
  if(b.id==='all-menus'){openDialog(`<div class="dialog-body"><span class="section-index">TODAY’S MENU POOL</span><h2 id="dialog-title">조건에 맞는 모든 메뉴</h2><div class="all-menu-grid">${candidates().map(m=>`<button class="menu-chip" data-detail="${m.id}"><span>${m.emoji}</span><span>${esc(m.name)}</span><small>${won(m.price)}원</small></button>`).join('')||'<p>조건에 맞는 메뉴가 없어요.</p>'}</div></div>`);}
  if(action==='play')await play(b);
  if(action==='open-capsule'&&state.pending){validateGamePool();const menu=candidates().find(m=>m.id===state.pending.id);if(!menu)throw Error('후보가 변경됐습니다. 다시 추첨해주세요.');finish(menu);}
  if(action==='reset-ladder'){resetRound();renderGame(candidates());}
  if(action==='again'){shared.setMenu(null);resetRestaurantDraw();resetRound();state.result=null;state.pending=null;state.ladder=null;renderGame(candidates());}
  if(action==='find')await findRestaurants();
  if(action==='back-game')switchView('game');
  if(action==='ai')aiRecommend();
  if(action==='edit-ai'){state.aiReady=false;renderGame(candidates());}
  if(action==='draw-ai-menu')await drawAiMenu();
  if(action==='route'){state.route=true;renderRestaurants();$$('.progress-step').forEach(x=>x.classList.toggle('active',x.dataset.step==='3'));}
  if(action==='random-restaurant')await drawRestaurant();
  if(action==='login'){const name=$('#nickname').value.trim();if(!name){toast('사용할 닉네임을 입력해 주세요.');return;}state.profile=name;state.names[0]=name;persist();$('#app-dialog').close();render();toast(`${name}님, 오늘도 맛있는 점심 되세요!`);}
  if(action==='logout'){state.profile='';state.names[0]='나';persist();$('#app-dialog').close();render();toast('게스트 모드로 전환했어요. 취향은 이 브라우저에 유지돼요.');}
  }catch(error){toast(error.message);}
});
$('#category-options').innerHTML=FOOD_TYPES.map(c=>`<button type="button" class="category" data-category="${c}"><span>🍽️</span> ${c}</button>`).join('');
updateProfile();syncFilters();render();if(launch.warning)toast(launch.warning);refreshCandidates();

window.addEventListener('pagehide',()=>{saveGame();cancelGameRequests();closeRoomFlow();window.LunchRunLocationPicker.close();});
window.addEventListener('pageshow',event=>{
 if(event.persisted){cancelGameRequests();setBusy(false);resetRound();state.restaurantDrawing=false;applySharedGame();syncFilters();render();switchView(state.view);refreshCandidates();}
});
switchView(state.view);
