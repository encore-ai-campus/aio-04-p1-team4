// /map uses only the shared context and backend-validated restaurant response.
(()=>{
 const store=window.LunchRunState,$=s=>document.querySelector(s);
 let geoJob=null,geoVersion=0;
 let overlapBadges=[];
 let routeLines=[],routePins=[],routeController,routeVersion=0,routeOrigin=null,drawVersion=0;
 const routeCache=new Map();
 let map,sdk,pins=[],circle,version=0,controller,selected=null,busy=false,sdkPromise;
 const status=text=>$('#search-status').textContent=text;
 const point=r=>Number.isFinite(r.lat)&&Number.isFinite(r.lng)&&Math.abs(r.lat)<=90&&Math.abs(r.lng)<=180;
 const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
 const all=()=>{const s=store.read();return [...s.restaurants.map(r=>({...r,verified:true})),...s.candidateRestaurants.map(r=>({...r,verified:false}))];};
 function cancel(){geoVersion++;geoJob?.cancel();drawVersion++;clearRoute();version++;controller?.abort();busy=false;$('#random').disabled=false;}
 async function post(path,body,signal){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.any([signal,AbortSignal.timeout(120000)])});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'검색에 실패했습니다. 조건과 연결을 확인해주세요.');return data;}
 function body(s){const minutes=store.remainingMinutes(s.conditions.deadline);if(!s.location)throw Error('먼저 출발 위치를 설정해주세요.');if(minutes<1||minutes>120)throw Error('점심 종료 시각을 1~120분 이내로 설정해주세요.');return {location:s.location,conditions:{budget:s.conditions.budget,minutes,cuisine:s.conditions.cuisine},radius_m:s.conditions.radius_m,menu_id:s.menu?.id??null};}
 function safeLink(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)?u.href:null;}catch{return null;}}
 function select(id,pan=true,fromDraw=false){
  if(!fromDraw)drawVersion++;clearRoute();
  const r=all().find(r=>r.id===id);if(!r)return;selected=id;if(r.verified)store.setSelection(id);else store.setSelection(null);
  document.querySelectorAll('[data-restaurant]').forEach(n=>{n.classList.toggle('active',n.dataset.restaurant===id);n.setAttribute('aria-pressed',String(n.dataset.restaurant===id));});
  const card=$('#selected-card');card.replaceChildren();card.hidden=false;
  const heading=el('div',null,'restaurant-card-heading');heading.append(el('h2',r.name));const close=el('button','×','restaurant-card-toggle');close.setAttribute('aria-label','식당 상세 닫기');close.onclick=()=>{card.hidden=true;};heading.append(close);const toggle=el('button','접기 ▴','restaurant-card-toggle');toggle.onclick=()=>{[...card.children].slice(1).forEach(n=>n.hidden=!n.hidden);toggle.textContent=toggle.textContent.startsWith('접기')?'펼치기 ▾':'접기 ▴';};heading.append(toggle);card.append(heading);
  card.append(el('p',r.verified?'검증된 추천 · 조회 시점 기준':'확인 필요 후보 · 가격 또는 영업정보 미확인'),el('p',r.category||''),el('p',r.address||'주소 미확인'),el('p',r.phone||'전화번호 미확인'));
  card.append(el('p',`메뉴: ${r.menu_name||r.search_keyword||store.read().menu?.name||'미확인'} · ${typeof r.price==='number'?r.price.toLocaleString()+'원':'가격 미확인'}`));
  card.append(el('p',r.open_status==='open'?'영업 상태: 조회 당시 영업 중':'영업 상태: 확인 필요'));
  if(Number.isFinite(r.distance_m))card.append(el('p',`출발점에서 직선 ${Math.round(r.distance_m)}m`));
  if(Array.isArray(r.warnings)&&r.warnings.length)card.append(el('p',r.warnings.join(' · ')));
  card.append(el('p','사진·평점·전체 영업시간은 제공된 데이터가 없으면 표시하지 않습니다.'));
  const url=safeLink(r.place_url);if(url){const link=el('a','카카오맵 상세보기 ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
  appendDetails(r,card);appendDirections(r,card);
  pins.forEach(p=>p.overlay.setZIndex(p.id===id?10:2));if(pan&&map&&point(r))map.panTo(new sdk.LatLng(r.lat,r.lng));
 }
 function redrawOverlap(){
  overlapBadges.forEach(o=>o.setMap(null));overlapBadges=[];pins.forEach(p=>p.node.hidden=false);
  if(!map?.getProjection||!window.LunchRunPinOverlaps)return;const projection=map.getProjection();
  const positions=all().filter(point).map(r=>{const p=projection.containerPointFromCoords(new sdk.LatLng(r.lat,r.lng));return {...r,x:p.x,y:p.y};});
  for(const group of window.LunchRunPinOverlaps.groups(positions)){if(group.members.length<2)continue;group.members.forEach(r=>{const pin=pins.find(p=>p.id===r.id);if(pin)pin.node.hidden=true;});const button=el('button',String(group.members.length),'backend-map-pin overlap-count');button.style.background='#ff641a';button.setAttribute('aria-label','겹친 식당 '+group.members.length+'곳');button.onclick=()=>clickPin(group.anchor.id);overlapBadges.push(new sdk.CustomOverlay({map,position:new sdk.LatLng(group.anchor.lat,group.anchor.lng),content:button,zIndex:15,yAnchor:1.2}));}
 }
 function paintMap(){
  if(!map)return;pins.forEach(p=>p.overlay.setMap(null));pins=[];circle?.setMap(null);
  const s=store.read();if(!s.location)return;const origin=new sdk.LatLng(s.location.lat,s.location.lng);
  circle=new sdk.Circle({map,center:origin,radius:s.conditions.radius_m,strokeWeight:2,strokeColor:'#ef642d',fillColor:'#ef642d',fillOpacity:.06});
  const add=(r,label,source=false)=>{if(!point(r))return;const node=el('button',label,'backend-map-pin');node.type='button';node.style.background=source?'#267955':r.verified?'#ef642d':'#687487';node.setAttribute('aria-label',source?'출발 위치':r.name);if(!source)node.onclick=()=>clickPin(r.id);const overlay=new sdk.CustomOverlay({map,position:new sdk.LatLng(r.lat,r.lng),content:node,yAnchor:1.2,zIndex:source?3:2,clickable:true});pins.push({id:r.id,overlay,node});};
  add({...s.location,id:'origin'},'⌖ 출발',true);all().forEach((r,i)=>add(r,String(i+1)));map.setBounds(circle.getBounds(),40,40,100,40);setTimeout(redrawOverlap,0);
 }
 function render(restored=false){
  const s=store.read();$('#search-location').textContent=s.location?`${s.location.name} · 반경 ${s.conditions.radius_m}m`:'출발 위치 미설정';$('#search-radius').value=s.conditions.radius_m;$('#radius-value').textContent=s.conditions.radius_m+'m';$('#cuisine-filter').value=s.conditions.cuisine;$('#map-budget').value=s.conditions.budget;
  $('#list-title').textContent=s.menu?`${s.menu.name} 관련 식당`:'메뉴를 먼저 선택해주세요';$('#count').textContent=`추천 ${s.restaurants.length} · 확인 필요 ${s.candidateRestaurants.length}`;
  const list=$('#restaurant-list');list.replaceChildren();all().forEach((r,i)=>{const button=el('button',null,'restaurant-item');button.type='button';button.dataset.restaurant=r.id;button.append(el('span',String(i+1),'number'));const info=el('div');info.append(el('strong',r.name),el('small',r.verified?'검증된 추천':'확인 필요 후보'),el('small',r.address||'주소 미확인'),el('small',typeof r.price==='number'?r.price.toLocaleString()+'원':'가격 미확인'));if(r.serving_unverified)info.append(el('small','인분 미확인 · 표시 가격 기준'));button.append(info);button.onclick=()=>select(r.id);list.append(button);});
  if(!all().length)list.append(el('p',busy?'식당을 검색하고 있어요.':'표시할 식당이 없습니다. 조건을 확인하거나 메뉴를 다시 골라주세요.'));
  $('#random').disabled=busy||!s.restaurants.length;
  $('#selected-card').hidden=true;paintMap();const id=selected||s.selectedRestaurantId;if(id)select(id,false);
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

 async function draw(){
  const rows=store.read().restaurants;if(busy||!rows.length)return;const token=++drawVersion;
  const candidates=rows.filter(r=>r.id!==selected),pool=candidates.length?candidates:rows;
  const target=pool[Math.floor(Math.random()*pool.length)];
  const visual=rows.length>15?[...rows.filter(r=>r.id!==target.id).slice(0,14),target]:rows;
  $('#random').disabled=true;status('식당 마커를 순서대로 확인하고 있어요…');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  try{for(let i=0;i<(reduced?1:visual.length*2);i++){if(token!==drawVersion)return;select(visual[i%visual.length].id,true,true);await new Promise(resolve=>setTimeout(resolve,reduced?500:60+i*15));}
   if(token!==drawVersion)return;select(target.id,true,true);status('선택 완료! '+target.name);
  }finally{if(token===drawVersion)$('#random').disabled=busy||!store.read().restaurants.length;}
 }
 $('#random').onclick=draw;


 function clearRoute(){const state=store.read();if(state.route)store.setRoute(null,state.contextRevision,state.selectedRestaurantId);routeVersion++;routeController?.abort();routeLines.forEach(l=>l.setMap(null));routePins.forEach(l=>l.setMap(null));routeLines=[];routePins=[];}
 function dialog(title){const modal=el('dialog');modal.className='menu-dialog';modal.append(el('h2',title));const close=el('button','닫기');close.onclick=()=>modal.close();modal.append(close);modal.addEventListener('close',()=>modal.remove());document.body.append(modal);modal.showModal();return modal;}
 async function appendDetails(r,card){
  const section=el('section');section.append(el('p','저장된 상세정보 확인 중…'));card.append(section);
  try{const response=await fetch('/map/api/restaurants/'+encodeURIComponent(r.id));const data=await response.json();if(!section.isConnected)return;if(!response.ok)throw Error(data.detail||'상세정보를 불러오지 못했습니다.');
   section.replaceChildren();const label={open:'현재 영업 중',closed:'현재 영업 종료',unknown:'영업시간 미확인'};
   section.append(el('p',(label[data.open_status]||label.unknown)+(data.checked_at?' · 확인 '+new Date(data.checked_at).toLocaleString('ko-KR'):'')));
   const hours=el('details'),summary=el('summary','요일별 영업시간');hours.append(summary);
   if(!data.business_hours.length)hours.append(el('p','저장된 영업시간이 없습니다.'));
   data.business_hours.forEach(h=>hours.append(el('p',('월화수목금토일'[h.day]||'?')+'요일 · '+(h.holiday?'휴무':h.start&&h.end?h.start+' ~ '+h.end+(h.next_day?' (익일)':''):'시간 미확인')+(h.last_order?' · 주문마감 '+h.last_order:'')+(h.holiday===null?' · 휴무 여부 확인 필요':''))));
   section.append(hours);const menus=el('button','메뉴·가격 보기 ('+data.menus.length+'개)');menus.className='menu-open';menus.onclick=()=>{const modal=dialog(r.name+' 메뉴·가격');if(!data.menus.length)modal.append(el('p','저장된 메뉴 정보가 없습니다.'));data.menus.forEach(m=>modal.append(el('p',m.name+' · '+(m.price_status==='known'&&Number.isFinite(m.price)?m.price.toLocaleString()+'원':m.price_status==='variable'?'시가·변동':'가격 미확인'))));modal.append(el('p','DB 수집 시점의 정보이며 실제 매장 상황은 달라질 수 있습니다.'));};section.append(menus);
  }catch(error){if(section.isConnected)section.replaceChildren(el('p',error.message));}
 }
 function appendDirections(r,card){
  const section=el('section'),note=el('p','도보 경로를 조회하면 출발점과 식당 사이의 길을 표시합니다.');
  const label=el('p');const update=()=>label.textContent='출발: '+(routeOrigin||store.read().location)?.name;
  update();const originButton=el('button','길찾기 출발지 변경');originButton.onclick=()=>{const modal=dialog('길찾기 출발지 선택');const apply=item=>{routeOrigin=item;modal.close();select(r.id,false);};const current=el('button','현재 검색 기준점 사용');current.onclick=()=>apply(store.read().location);modal.append(current);const center=el('button','지도 가운데를 출발지로');center.onclick=()=>{if(map){const p=map.getCenter();apply({lat:p.getLat(),lng:p.getLng(),name:'지도 중심',source:'place'});}};modal.append(center);const custom=el('button','현재 위치·주소·장소로 선택');custom.onclick=()=>{modal.close();window.LunchRunLocationPicker.open(item=>{routeOrigin=item;select(r.id,false);},routeOrigin||store.read().location);};modal.append(custom);};
  const walk=el('button','도보 경로 보기'),cancelButton=el('button','경로 취소');cancelButton.onclick=()=>{clearRoute();paintMap();note.textContent='경로 표시를 취소했습니다.';};
  walk.onclick=async()=>{
   clearRoute();const token=routeVersion,origin=routeOrigin||store.read().location;if(!origin||!point(origin)){note.textContent='출발지를 먼저 설정해주세요.';return;}
   routeController=new AbortController();walk.disabled=true;note.textContent='실제 도보 경로를 확인하고 있어요…';
   try{const key=JSON.stringify([origin.lat,origin.lng,r.lat,r.lng]);let data=routeCache.get(key);
    if(!data||Date.now()-data.at>300000){const response=await fetch('/map/api/walking-route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({origin:{lat:origin.lat,lng:origin.lng},destination:{lat:r.lat,lng:r.lng}}),signal:AbortSignal.any([routeController.signal,AbortSignal.timeout(60000)])});const result=await response.json();if(!response.ok)throw Error(result.error||'경로 조회에 실패했습니다.');if(!Number.isFinite(result.distance)||!Number.isFinite(result.duration)||!Array.isArray(result.paths))throw Error('경로 응답을 확인해주세요.');data={...result,at:Date.now()};if(routeCache.size>=100)routeCache.delete(routeCache.keys().next().value);routeCache.set(key,data);}
    if(token!==routeVersion||!section.isConnected)return;note.textContent='도보 약 '+window.LunchRunRoutes.formatDuration(data.duration)+' · '+window.LunchRunRoutes.formatDistance(data.distance)+' · 실제 시간은 달라질 수 있습니다.';
    if(map){const bounds=new sdk.LatLngBounds();const lines=[...data.paths,...window.LunchRunRoutes.walkingConnections(data.paths,origin,r)];
     lines.forEach((line,index)=>{const path=line.map(([lng,lat])=>new sdk.LatLng(lat,lng));path.forEach(p=>bounds.extend(p));routeLines.push(new sdk.Polyline({map,path,strokeWeight:5,strokeColor:'#2878e8',strokeStyle:index<data.paths.length?'solid':'shortdash',zIndex:20}));});
     for(const [p,name] of [[origin,'출발'],[r,'도착']]){const pos=new sdk.LatLng(p.lat,p.lng);bounds.extend(pos);routePins.push(new sdk.CustomOverlay({map,position:pos,content:el('span',name,'backend-map-pin'),zIndex:30}));}
     map.setBounds(bounds,45,35,220,45);
    }
    store.setRoute({origin,destination:{id:r.id,lat:r.lat,lng:r.lng},distance:data.distance,duration:data.duration},store.read().contextRevision,r.id);
   }catch(error){if(token===routeVersion&&section.isConnected)note.textContent=error.name==='AbortError'?'경로 조회가 취소되었거나 시간이 초과됐습니다.':error.message;}
   finally{if(section.isConnected)walk.disabled=false;}
  };
  section.append(el('h3','식당까지 길찾기'),label,originButton,walk,cancelButton,note);
  const origin=routeOrigin||store.read().location;if(origin)for(const [mode,text] of [['walk','도보'],['car','자동차'],['traffic','대중교통']]){const url=window.LunchRunRoutes.routeUrl(origin,r,mode);if(url){const link=el('a',text+' 길찾기 ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';section.append(link,document.createTextNode(' '));}}
  card.append(section);
 }
 function clickPin(id){
  if(!map?.getProjection){select(id);return;}
  const projection=map.getProjection(),target=all().find(r=>r.id===id);if(!target)return;
  const p=projection.containerPointFromCoords(new sdk.LatLng(target.lat,target.lng));
  const nearby=all().filter(r=>{const q=projection.containerPointFromCoords(new sdk.LatLng(r.lat,r.lng));return Math.abs(p.x-q.x)<36&&Math.abs(p.y-q.y)<48;});
  if(nearby.length<=1){select(id);return;}const modal=dialog('겹친 식당 '+nearby.length+'곳');nearby.forEach(r=>{const button=el('button',r.name);button.onclick=()=>{modal.close();select(r.id);};modal.append(button);});
 }


 $('#precise-location').onclick=()=>{
  geoJob?.cancel();const token=++geoVersion;
  if(!navigator.geolocation||!window.isSecureContext){status('현재 위치는 HTTPS 또는 localhost에서 사용할 수 있습니다. 주소·장소 검색을 이용해주세요.');return;}
  status('최대 30초 동안 더 정확한 위치를 확인하고 있어요…');
  const apply=p=>change({location:{lat:p.latitude,lng:p.longitude,accuracy:p.accuracy,name:'현재 위치',source:'geolocation',address:'기기 추정 오차 약 '+Math.round(p.accuracy)+'m'}});
  geoJob=window.LunchRunGeoDiagnostics.requestLocation({geolocation:navigator.geolocation,
   onProgress:p=>{if(token===geoVersion)status('현재 추정 오차 약 '+Math.round(p.accuracy)+'m · 더 정확한 위치를 기다립니다.');},
   onResult:result=>{if(token!==geoVersion)return;geoJob=null;if(result.kind==='accurate'){apply(result.position);return;}
    if(result.kind==='approximate'){const modal=dialog('대략 위치 확인');modal.append(el('p','기기 추정 오차 약 '+Math.round(result.position.accuracy)+'m입니다. 이 위치를 사용하시겠어요?'));const button=el('button','대략 위치 사용');button.onclick=()=>{modal.close();if(token===geoVersion)apply(result.position);};modal.append(button);}
    else status(result.code===1?'위치 권한이 거부되었습니다. 주소·장소 검색을 이용해주세요.':'위치를 확인하지 못했습니다. 주소·장소 검색을 이용해주세요.');
   }});
 };


 $('#catalog-open').onclick=()=>{
  const modal=dialog('DB 전체 메뉴 검색'),form=el('form'),input=el('input'),submit=el('button','검색'),results=el('div');input.required=true;input.maxLength=100;input.placeholder='메뉴 이름';input.setAttribute('aria-label','DB 메뉴 검색어');submit.type='submit';form.append(input,submit);modal.append(form,results);let sequence=0;
  form.onsubmit=async event=>{event.preventDefault();const token=++sequence;results.replaceChildren(el('p','검색 중…'));try{const response=await fetch('/map/api/menu-search?query='+encodeURIComponent(input.value.trim()));const data=await response.json();if(token!==sequence||!modal.open)return;if(!response.ok)throw Error(data.detail||'검색 실패');results.replaceChildren();if(!data.items.length)results.append(el('p','저장된 메뉴가 없습니다.'));data.items.forEach(item=>{const row=el('p',item.menu_name+' · '+item.restaurant_name+' · '+(item.price_status==='known'&&Number.isFinite(item.price)?item.price.toLocaleString()+'원':'가격 미확인'));const url=safeLink(item.place_url);if(url){const link=el('a',' 상세보기');link.href=url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}results.append(row);});if(data.has_more)results.append(el('p','상위 100개입니다. 검색어를 구체적으로 입력해주세요.'));}catch(error){if(modal.open)results.replaceChildren(el('p',error.message));}};
 };
 $('#search-again').onclick=search;$('#setup-open').onclick=loadMap;
 $('#map-center-search').onclick=()=>{if(map){const center=map.getCenter();change({location:{lat:center.getLat(),lng:center.getLng(),name:'지도 중심',source:'place'}});}};
 $('#radius-less').onclick=()=>change({conditions:{radius_m:Math.max(50,store.read().conditions.radius_m-50)}});
 $('#radius-more').onclick=()=>change({conditions:{radius_m:Math.min(500,store.read().conditions.radius_m+50)}});
 $('#change-location').onclick=()=>window.LunchRunLocationPicker.open(location=>change({location}),store.read().location);
 $('#search-radius').onchange=e=>change({conditions:{radius_m:Number(e.target.value)}});
 $('#map-conditions').onsubmit=e=>{e.preventDefault();change({conditions:{budget:Number($('#map-budget').value),cuisine:$('#cuisine-filter').value}});};
 window.addEventListener('pagehide',()=>{cancel();window.LunchRunLocationPicker.close();});
 window.addEventListener('pageshow',e=>{if(e.persisted){cancel();selected=null;render(true);}});
 window.addEventListener('resize',()=>{map?.relayout?.();redrawOverlap();});
 render(true);loadMap();if(new URLSearchParams(location.search).get('search')==='1'){history.replaceState(null,'','/map/');search();}
})();
