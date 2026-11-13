// /map uses only the shared context and backend-validated restaurant response.
(()=>{
 const store=window.LunchRunState,$=s=>document.querySelector(s);
 let geoJob=null,geoVersion=0;
 let overlapBadges=[];
 let routeLines=[],routePins=[],routeController,routeVersion=0,drawVersion=0;
 const routeCache=new Map();
 let routeFocus=false;
 let map,sdk,pins=[],circle,version=0,controller,selected=null,busy=false,sdkPromise;
 const status=text=>$('#search-status').textContent=text;
 const point=r=>r&&Number.isFinite(r.lat)&&Number.isFinite(r.lng)&&Math.abs(r.lat)<=90&&Math.abs(r.lng)<=180;
 const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
 function originIcon(){const marker=el('span',null,'origin-core');marker.setAttribute('aria-hidden','true');return marker;}
 function restaurantPin(number,name){const node=el('span',null,'backend-map-pin restaurant-pin');node.setAttribute('aria-label',name);return node;}
 function collapseDetails(){document.querySelectorAll('.restaurant-details').forEach(node=>node.remove());document.querySelectorAll('[data-restaurant]').forEach(node=>node.setAttribute('aria-expanded','false'));}
 function restoreList(){document.querySelectorAll('.restaurant-entry').forEach(row=>row.hidden=false);const saved=store.read();$('#count').textContent=`추천 ${saved.restaurants.length} · 확인 필요 ${saved.candidateRestaurants.length}`;routeFocus=false;clearRoute();$('#route-focus-summary')?.remove();$('.map-actions').classList.remove('route-mode');$('#random').textContent='식당 랜덤';paintMap();}
 const all=()=>{const s=store.read();return [...s.restaurants.map(r=>({...r,verified:true})),...s.candidateRestaurants.map(r=>({...r,verified:false}))];};
 function cancel(){$('.map-actions').classList.remove('route-mode');$('#random').textContent='식당 랜덤';routeFocus=false;$('#route-focus-summary')?.remove();geoVersion++;geoJob?.cancel();drawVersion++;clearRoute();version++;controller?.abort();busy=false;$('#random').disabled=false;}
 async function post(path,body,signal){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.any([signal,AbortSignal.timeout(120000)])});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'검색에 실패했습니다. 조건과 연결을 확인해주세요.');return data;}
 function body(s){const minutes=store.remainingMinutes(s.conditions.deadline);if(!s.location)throw Error('먼저 출발 위치를 설정해주세요.');if(minutes<1||minutes>120)throw Error('점심 종료 시각을 1~120분 이내로 설정해주세요.');return {location:s.location,conditions:{budget:s.conditions.budget,minutes,cuisine:s.conditions.cuisine},radius_m:s.conditions.radius_m,menu_id:s.menu?.id??null};}

 function select(id,pan=true,fromDraw=false,showDetails=!fromDraw){
  if(routeFocus)restoreList();
  if(!fromDraw)drawVersion++;clearRoute();
  const r=all().find(r=>r.id===id);if(!r)return;selected=id;if(r.verified)store.setSelection(id);else store.setSelection(null);
  document.querySelectorAll('[data-restaurant]').forEach(n=>{n.classList.toggle('active',n.dataset.restaurant===id);n.setAttribute('aria-pressed',String(n.dataset.restaurant===id));});
  $('#selected-card').hidden=true;
  document.querySelectorAll('.restaurant-details').forEach(node=>node.remove());
  document.querySelectorAll('[data-restaurant]').forEach(node=>node.setAttribute('aria-expanded',String(showDetails&&node.dataset.restaurant===id)));
  const row=[...document.querySelectorAll('[data-restaurant]')].find(node=>node.dataset.restaurant===id);
  if(row&&showDetails){const details=el('div',null,'restaurant-details');details.onclick=collapseDetails;row.closest('.restaurant-entry').append(details);details.append(el('p',r.address||'상세주소 미확인'));const hours=el('div', '영업시간 확인 중…','restaurant-hours');details.append(hours);loadHours(r,hours);}
  pins.forEach(p=>p.overlay.setZIndex(p.id===id?10:2));if(pan&&map&&point(r))map.panTo(new sdk.LatLng(r.lat,r.lng));
 }
 function redrawOverlap(){
  overlapBadges.forEach(o=>o.setMap(null));overlapBadges=[];pins.forEach(p=>p.node.hidden=false);
  if(routeFocus||!map?.getProjection||!window.LunchRunPinOverlaps)return;const projection=map.getProjection();
  const positions=all().filter(point).map(r=>{const p=projection.containerPointFromCoords(new sdk.LatLng(r.lat,r.lng));return {...r,x:p.x,y:p.y};});
  for(const group of window.LunchRunPinOverlaps.groups(positions)){if(group.members.length<2)continue;group.members.forEach(r=>{const pin=pins.find(p=>p.id===r.id);if(pin)pin.node.hidden=true;});const button=el('button',String(group.members.length),'backend-map-pin overlap-count');button.style.background='#ff641a';button.setAttribute('aria-label','겹친 식당 '+group.members.length+'곳');button.onclick=()=>clickPin(group.anchor.id);overlapBadges.push(new sdk.CustomOverlay({map,position:new sdk.LatLng(group.anchor.lat,group.anchor.lng),content:button,zIndex:15,yAnchor:1.2}));}
 }
 function paintMap(){
  if(!map)return;pins.forEach(p=>p.overlay.setMap(null));pins=[];circle?.setMap(null);
  const s=store.read();if(!s.location)return;const origin=new sdk.LatLng(s.location.lat,s.location.lng);
  circle=new sdk.Circle({map,center:origin,radius:s.conditions.radius_m,strokeWeight:2,strokeColor:'#ef642d',fillColor:'#ef642d',fillOpacity:.06});
  const add=(r,label,source=false)=>{if(!point(r))return;const node=source?el('button',null,'backend-map-pin'):restaurantPin(label,r.name);if(source)node.type='button';if(source){node.textContent='';node.classList.add('origin-icon');node.append(originIcon());}node.style.background=source?'#267955':r.verified?'#ef642d':'#687487';node.setAttribute('aria-label',source?'출발 위치':r.name);if(!source)node.onclick=()=>clickPin(r.id);const overlay=new sdk.CustomOverlay({map,position:new sdk.LatLng(r.lat,r.lng),content:node,yAnchor:source ? 0.5 : 1,zIndex:source?3:2,clickable:true});pins.push({id:r.id,overlay,node});};
  add({...s.location,id:'origin'},'⌖ 출발',true);all().forEach((r,i)=>add(r,String(i+1)));map.setBounds(circle.getBounds(),40,40,100,40);setTimeout(redrawOverlap,0);
 }
 function render(restored=false){
  const s=store.read();window.LunchRunHeaderLocation?.update();$('#map-summary').textContent=store.summary();$('#search-radius').value=s.conditions.radius_m;$('#radius-value').textContent=s.conditions.radius_m+'m';$('#cuisine-filter').value=s.conditions.cuisine;$('#map-budget').value=s.conditions.budget.toLocaleString('ko-KR')+'원';
  $('#list-title').textContent=s.menu?`${s.menu.name} 관련 식당`:'메뉴를 먼저 선택해주세요';$('#count').textContent=`추천 ${s.restaurants.length} · 확인 필요 ${s.candidateRestaurants.length}`;
  const list=$('#restaurant-list');list.replaceChildren();all().forEach((r,i)=>{const button=el('button',null,'restaurant-item');button.type='button';button.dataset.restaurant=r.id;button.append(el('span',String(i+1),'number'));const info=el('div');info.append(el('strong',r.name),el('small',typeof r.price==='number'?r.price.toLocaleString()+'원':'가격 미확인'));const distance=Number.isFinite(r.walk_distance_m)?`도보 ${Math.round(r.walk_distance_m)}m`:Number.isFinite(r.distance_m)?`직선 ${Math.round(r.distance_m)}m`:'거리 미확인';const minutes=Number.isFinite(r.walk_minutes)?`도보 ${r.walk_minutes}분`:'도보 시간 미확인';info.append(el('small',distance+' · '+minutes,'travel-info'));button.append(info);button.onclick=()=>{if(button.getAttribute('aria-expanded')==='true')collapseDetails();else select(r.id);};const entry=el('div',null,'restaurant-entry');entry.append(button);button.setAttribute('aria-expanded','false');list.append(entry);});
  if(!all().length)list.append(el('p',busy?'식당을 검색하고 있어요.':'표시할 식당이 없습니다. 조건을 확인하거나 메뉴를 다시 골라주세요.'));
  $('#random').disabled=busy||!s.restaurants.length;
  $('#selected-card').hidden=true;paintMap();const id=selected||s.selectedRestaurantId;if(id)select(id,false,false,false);
  if(restored&&s.searchedAt)status('이전 조회 결과입니다. 현재 가격·영업 여부는 다시 검색해 확인해주세요.');
 }
 async function search(){
  cancel();const token=version;controller=new AbortController();const s=store.read();
  try{const request=body(s);busy=true;render();status('DB에서 메뉴·가격·영업 조건에 맞는 식당 조회 중…');const result=await post(s.menu?'/api/recommendations':'/map/api/nearby',request,controller.signal);if(token!==version)return;if(!store.setRestaurants(result,s.contextRevision,s.menu?.id??null))return;selected=null;busy=false;render();status(result.message||'검색을 완료했습니다.');}
  catch(error){if(token===version){busy=false;render();status(error.name==='AbortError'?'검색이 취소되었거나 시간이 초과됐습니다. 다시 검색해주세요.':error.message);}}
 }
 async function change(patch){
  cancel();const old=store.read().menu;store.setContext(patch);selected=null;render();if(!map)loadMap();if(!old){await search();return;}
  const token=version;controller=new AbortController();
  try{const s=store.read();const request=body({...s,menu:old});status('변경한 조건에서 메뉴를 다시 확인하고 있어요.');const data=await post('/api/menus/candidates',request,controller.signal);if(token!==version)return;const menu=data.menus?.find(m=>m.id===old.id);if(!menu){status('변경한 조건에 맞는 메뉴를 게임에서 다시 골라주세요.');return;}store.setMenu(menu);await search();}catch(error){if(token===version)status(error.message);}
 }
 async function loadMap(){
  if(!store.read().location){$('#map-hint').textContent='먼저 출발 위치를 설정해주세요.';return;}
  try{
   if(!sdkPromise)sdkPromise=(async()=>{const response=await fetch('/map/config.json');if(!response.ok)throw Error('지도 설정을 읽지 못했습니다.');const config=await response.json();if(!config.javascriptKey)throw Error('카카오 JavaScript 키를 설정해주세요.');await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey='+encodeURIComponent(config.javascriptKey);const timer=setTimeout(()=>reject(Error('지도 연결 시간이 초과됐습니다. 등록 도메인과 네트워크를 확인해주세요.')),15000);script.onload=()=>{clearTimeout(timer);resolve();};script.onerror=()=>{clearTimeout(timer);reject(Error('카카오 지도 SDK를 불러오지 못했습니다.'));};document.head.append(script);});await new Promise(resolve=>window.kakao.maps.load(resolve));return window.kakao.maps;})();
   sdk=await sdkPromise;if(!map){const s=store.read();map=new sdk.Map($('#kakao-map'),{center:new sdk.LatLng(s.location.lat,s.location.lng),level:3});sdk.event?.addListener(map,'idle',redrawOverlap);}$('#map-hint').hidden=true;paintMap();
  }catch(error){sdkPromise=null;$('#map-hint').hidden=false;$('#map-hint').textContent=error.message+' · 지도 다시 연결 버튼을 눌러주세요.';}
 }

 async function focusSelectedRoute(){
  const s=store.read(),r=all().find(item=>item.id===(selected||s.selectedRestaurantId)),origin=s.location;
  const notice=text=>{status(text);$('#map-hint').textContent=text;$('#map-hint').hidden=false;};
  if(!r){notice('목록이나 지도에서 식당을 먼저 선택해주세요.');return;}
  if(!point(origin)||!point(r)){notice('출발 위치와 식당 좌표를 확인해주세요.');return;}
  const context=s.contextRevision,restaurantId=r.id;
  try{
   if(!map)await loadMap();
   if(!map)return;
   if(store.read().contextRevision!==context||(selected||store.read().selectedRestaurantId)!==restaurantId)return;
   clearRoute();routeFocus=true;collapseDetails();document.querySelectorAll('.restaurant-entry').forEach(row=>row.hidden=row.querySelector('[data-restaurant]').dataset.restaurant!==r.id);$('#count').textContent='선택한 식당 1곳';
   pins.forEach(pin=>pin.overlay.setMap(null));overlapBadges.forEach(pin=>pin.setMap(null));overlapBadges=[];circle?.setMap(null);
   $('#selected-card').hidden=true;$('#map-hint').hidden=true;
   $('#route-focus-summary')?.remove();
   const summary=el('div',null,'route-focus-summary');summary.id='route-focus-summary';
   summary.hidden=true;$('#map').append(summary);
   for(const [p,label,kind] of [[origin,'출발: '+(origin.name||'설정 위치'),'origin'],[r,'도착: '+r.name,'destination']]){
    const node=kind==='origin'?el('span',null,'backend-map-pin origin-icon'):restaurantPin(all().findIndex(item=>item.id===r.id)+1,r.name);node.classList.add('route-endpoint',kind);if(kind==='origin'){node.classList.add('origin-icon');node.setAttribute('aria-label','출발 위치');node.append(originIcon());}
    routePins.push(new sdk.CustomOverlay({map,position:new sdk.LatLng(p.lat,p.lng),content:node,zIndex:35,yAnchor:kind==='origin' ? 0.5 : 1}));
   }
   const fit=()=>{if(!routeFocus)return;const bounds=new sdk.LatLngBounds();bounds.extend(new sdk.LatLng(origin.lat,origin.lng));bounds.extend(new sdk.LatLng(r.lat,r.lng));map.relayout?.();map.setBounds(bounds,70,45,40,45);if(origin.lat===r.lat&&origin.lng===r.lng)map.setLevel?.(2);};
   fit();
   $('#map').scrollIntoView({block:'nearest',behavior:'smooth'});
   const token=routeVersion;routeController=new AbortController();
   notice('도보 경로를 확인하고 있어요…');
   try{
    const data=await walkingData(origin,r,routeController.signal);
    if(!routeFocus||token!==routeVersion||store.read().contextRevision!==context)return;
    const bounds=new sdk.LatLngBounds();bounds.extend(new sdk.LatLng(origin.lat,origin.lng));bounds.extend(new sdk.LatLng(r.lat,r.lng));
    const lines=[...data.paths,...window.LunchRunRoutes.walkingConnections(data.paths,origin,r)];
    lines.forEach((line,index)=>{const path=line.map(([lng,lat])=>new sdk.LatLng(lat,lng));path.forEach(p=>bounds.extend(p));routeLines.push(new sdk.Polyline({map,path,strokeWeight:5,strokeColor:'#ff641a',strokeStyle:index<data.paths.length?'solid':'shortdash',zIndex:20}));});
    map.setBounds(bounds,70,45,40,45);
    if(r.verified)store.setRoute({origin,destination:{id:r.id,lat:r.lat,lng:r.lng},distance:data.distance,duration:data.duration},context,r.id);
    const text=el('div',null,'route-summary-lines'),time=el('span','총 소요 예상 '),distance=el('span','거리 ');time.append(el('strong',window.LunchRunRoutes.formatDuration(data.duration),'route-value'));distance.append(el('strong',window.LunchRunRoutes.formatDistance(data.distance),'route-value'));text.append(time,distance);summary.replaceChildren(text);summary.hidden=false;
    $('.map-actions').classList.add('route-mode');$('#random').textContent='다른 식당 선택';$('#random').disabled=false;
    $('#map-hint').hidden=true;
    status('도보 약 '+window.LunchRunRoutes.formatDuration(data.duration)+' · '+window.LunchRunRoutes.formatDistance(data.distance));
   }catch(error){if(routeFocus&&token===routeVersion)notice(error.name==='AbortError'?'경로 조회가 취소되었거나 시간이 초과됐습니다.':'도보 경로를 표시하지 못했습니다. '+error.message);}

  }catch(error){notice('지도 확대에 실패했습니다. '+error.message);}
 }
 $('#confirm-route').onclick=focusSelectedRoute;
 async function draw(){
  const rows=store.read().restaurants;if(busy||!rows.length)return;const token=++drawVersion;
  const candidates=rows.filter(r=>r.id!==selected),pool=candidates.length?candidates:rows;
  const target=pool[Math.floor(Math.random()*pool.length)];
  const visual=rows.length>15?[...rows.filter(r=>r.id!==target.id).slice(0,14),target]:rows;
  $('#random').disabled=true;status('식당 마커를 순서대로 확인하고 있어요…');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const duration=2000,steps=reduced?1:20,started=performance.now();
  try{for(let i=0;i<steps;i++){if(token!==drawVersion)return;select(visual[i%visual.length].id,true,true);const due=started+duration*Math.pow((i+1)/steps,1.35);await new Promise(resolve=>setTimeout(resolve,Math.max(0,due-performance.now())));}
   if(token!==drawVersion)return;select(target.id,true,true);status('선택 완료! '+target.name);
  }finally{if(token===drawVersion)$('#random').disabled=busy||!store.read().restaurants.length;}
 }
 $('#random').onclick=()=>{if(routeFocus){restoreList();collapseDetails();}else draw();};


 function clearRoute(){const state=store.read();if(state.route)store.setRoute(null,state.contextRevision,state.selectedRestaurantId);routeVersion++;routeController?.abort();routeLines.forEach(l=>l.setMap(null));routePins.forEach(l=>l.setMap(null));routeLines=[];routePins=[];}
 function dialog(title){const modal=el('dialog');modal.className='menu-dialog';modal.append(el('h2',title));const close=el('button','닫기');close.onclick=()=>modal.close();modal.append(close);modal.addEventListener('close',()=>modal.remove());document.body.append(modal);modal.showModal();return modal;}
 async function loadHours(r,container){
  try{const response=await fetch('/map/api/restaurants/'+encodeURIComponent(r.id));const data=await response.json();if(!container.isConnected)return;if(!response.ok)throw Error();container.replaceChildren();
   if(!data.business_hours?.length){container.textContent='영업시간 미확인';return;}
   data.business_hours.forEach(h=>container.append(el('p',('월화수목금토일'[h.day]||'?')+'요일 · '+(h.holiday?'휴무':h.start&&h.end?h.start+' ~ '+h.end+(h.next_day?' (익일)':''):'시간 미확인')+(h.last_order?' · 주문마감 '+h.last_order:''))));
  }catch{if(container.isConnected)container.textContent='영업시간 미확인';}
 }
 async function walkingData(origin,destination,signal){
  const key=JSON.stringify([origin.lat,origin.lng,destination.lat,destination.lng]);let data=routeCache.get(key);
  if(!data||Date.now()-data.at>300000){
   const response=await fetch('/map/api/walking-route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({origin:{lat:origin.lat,lng:origin.lng},destination:{lat:destination.lat,lng:destination.lng}}),signal:AbortSignal.any([signal,AbortSignal.timeout(60000)])});
   const result=await response.json();if(!response.ok)throw Error(result.error||'경로 조회에 실패했습니다.');
   if(!Number.isFinite(result.distance)||!Number.isFinite(result.duration)||!Array.isArray(result.paths)||!result.paths.some(line=>Array.isArray(line)&&line.length>=2)||!result.paths.every(line=>Array.isArray(line)&&line.every(p=>Array.isArray(p)&&p.length>=2&&point({lat:p[1],lng:p[0]}))))throw Error('경로 응답을 확인해주세요.');
   data={...result,at:Date.now()};if(routeCache.size>=100)routeCache.delete(routeCache.keys().next().value);routeCache.set(key,data);
  }return data;
 }
 function clickPin(id){
  if(!map?.getProjection){select(id);return;}
  const projection=map.getProjection(),target=all().find(r=>r.id===id);if(!target)return;
  const p=projection.containerPointFromCoords(new sdk.LatLng(target.lat,target.lng));
  const nearby=all().filter(r=>{const q=projection.containerPointFromCoords(new sdk.LatLng(r.lat,r.lng));return Math.abs(p.x-q.x)<36&&Math.abs(p.y-q.y)<48;});
  if(nearby.length<=1){select(id);return;}const modal=dialog('겹친 식당 '+nearby.length+'곳');nearby.forEach(r=>{const button=el('button',r.name);button.onclick=()=>{modal.close();select(r.id);};modal.append(button);});
 }


 $('#setup-open').onclick=loadMap;
 const budgetValue=()=>Number($('#map-budget').value.replace(/[^0-9]/g,''));
 const formatBudget=value=>$('#map-budget').value=Math.min(100000,Math.max(1000,value||1000)).toLocaleString('ko-KR')+'원';
 $('#budget-less').onclick=()=>formatBudget(budgetValue()-1000);
 $('#budget-more').onclick=()=>formatBudget(budgetValue()+1000);
 $('#map-budget').oninput=e=>{const digits=e.target.value.replace(/[^0-9]/g,'');e.target.value=digits?Math.min(100000,Number(digits)).toLocaleString('ko-KR'):'';};
 $('#map-budget').onblur=()=>formatBudget(budgetValue());
 const radiusValue=value=>{const radius=Math.min(500,Math.max(50,value));$('#search-radius').value=radius;$('#radius-value').textContent=radius+'m';};
 $('#radius-less').onclick=()=>radiusValue(Number($('#search-radius').value)-50);
 $('#radius-more').onclick=()=>radiusValue(Number($('#search-radius').value)+50);
 $('#search-radius').oninput=e=>radiusValue(Number(e.target.value));
 $('#change-location').onclick=()=>window.LunchRunLocationPicker.open(location=>change({location}),store.read().location);

 $('#map-conditions').onsubmit=e=>{e.preventDefault();$('.search-options').open=false;change({conditions:{budget:Math.min(100000,Math.max(1000,budgetValue()||1000)),radius_m:Number($('#search-radius').value),cuisine:$('#cuisine-filter').value}});};
 $('.search-options>summary').onclick=e=>{e.preventDefault();$('.search-options').open=true;};
 document.addEventListener('click',e=>{
  if(!e.target.closest('.search-options,.lr-location-dialog'))$('.search-options').open=false;
  if(!e.target.closest('.restaurant-entry,.backend-map-pin,.menu-dialog'))collapseDetails();
 });
 window.addEventListener('pagehide',()=>{cancel();window.LunchRunLocationPicker.close();});
 window.addEventListener('pageshow',e=>{if(e.persisted){cancel();selected=null;render(true);}});
 window.addEventListener('resize',()=>{map?.relayout?.();redrawOverlap();});
 render(true);loadMap();if(new URLSearchParams(location.search).get('search')==='1'){history.replaceState(null,'','/map/');search();}
})();
