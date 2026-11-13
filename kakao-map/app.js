let restaurants = window.RESTAURANTS.filter(r=>!(window.DISTRICT_RESTAURANTS?.excludedIds||[]).includes(String(r.id)));
let allRestaurants=[...restaurants];
const cuisineFilter=document.getElementById('cuisine-filter');
window.LunchRunCuisine.populate(cuisineFilter,allRestaurants);
function applyCuisineFilter(){
  restaurants=allRestaurants.filter(r=>cuisineFilter.value==='전체'||window.LunchRunCuisine.classify(r)===cuisineFilter.value);
  selectedId=restaurants[0]?.id||null;
  renderRestaurants();
  if(map)drawRestaurantMarkers();
  else if(restaurants.length)select(selectedId,false);
  if(!restaurants.length){card.replaceChildren();const note=document.createElement('p');note.className='menu-empty';note.textContent='이 반경에는 선택한 종류의 가게가 없어요. 음식 종류나 검색 반경을 바꿔주세요.';card.append(note);}
}
cuisineFilter.addEventListener('change',applyCuisineFilter);
let searchCenter = window.SEARCH_CENTER || null;
const list = document.getElementById('restaurant-list');
const card = document.getElementById('selected-card');
const mapElement = document.getElementById('map');
const pins = document.getElementById('demo-pins');
const setup = document.getElementById('setup');
let selectedId = restaurants[0].id;
let map = null;
const markers = new Map();
let overlapPanel=null;
let overlapCountOverlays=[];
let overlapGroupsById=new Map();
function clearOverlapCounts(){
  overlapCountOverlays.forEach(overlay=>overlay.setMap(null));overlapCountOverlays=[];overlapGroupsById.clear();
}
function redrawOverlapCounts(){
  clearOverlapCounts();
  if(!map||walkingFocused||rouletteRunning)return;
  const projection=map.getProjection();
  const points=restaurants.map(r=>{
    const position=new kakao.maps.LatLng(r.lat,r.lng),point=projection.containerPointFromCoords(position);
    return {id:r.id,x:point.x,y:point.y,position,restaurant:r};
  });
  for(const {anchor,members} of window.LunchRunPinOverlaps.groups(points)){
    const group=members.map(point=>point.restaurant);
    members.forEach(point=>overlapGroupsById.set(point.id,group));
    if(group.length<2)continue;
    const button=document.createElement('button');button.type='button';button.className='overlap-count-badge';
    button.textContent=group.length;button.dataset.overlapAnchor=anchor.id;
    button.setAttribute('aria-label',`겹친 가게 ${group.length}곳 목록 보기`);button.title=`겹친 가게 ${group.length}곳`;
    button.addEventListener('click',event=>{event.stopPropagation();kakao.maps.event.preventMap();handleRestaurantPinClick(anchor.id);});
    overlapCountOverlays.push(new kakao.maps.CustomOverlay({map,position:anchor.position,content:button,xAnchor:0,yAnchor:1,zIndex:40,clickable:true}));
  }
}
function closeOverlapList(){
  overlapPanel?.remove();overlapPanel=null;mapElement.classList.remove('overlap-list-open');
}
function handleRestaurantPinClick(id){
  if(!map||walkingFocused||rouletteRunning)return;
  const projection=map.getProjection();
  const clicked=restaurants.find(r=>r.id===id);
  if(!clicked)return;
  const origin=projection.containerPointFromCoords(new kakao.maps.LatLng(clicked.lat,clicked.lng));
  // Compare the visible 36 x 48 pixel pins at the current zoom, without moving them.
  const group=overlapGroupsById.get(id)||restaurants.filter(r=>{
    const point=projection.containerPointFromCoords(new kakao.maps.LatLng(r.lat,r.lng));
    return Math.abs(point.x-origin.x)<36&&Math.abs(point.y-origin.y)<48;
  });
  closeOverlapList();
  if(group.length<2){select(id);return;}
  overlapPanel=document.createElement('section');overlapPanel.className='overlap-place-panel';overlapPanel.setAttribute('aria-label','겹친 핀의 가게 목록');
  const heading=document.createElement('div');heading.className='overlap-place-heading';
  const title=document.createElement('h3');title.textContent=`겹친 위치의 가게 ${group.length}곳`;
  const close=document.createElement('button');close.type='button';close.textContent='닫기';close.setAttribute('aria-label','겹친 가게 목록 닫기');close.addEventListener('click',closeOverlapList);
  heading.append(title,close);
  const note=document.createElement('p');note.textContent='화면에서 핀이 겹친 가게입니다. 가게를 선택해주세요.';
  const items=document.createElement('div');items.className='overlap-place-items';
  group.sort((a,b)=>a.name.localeCompare(b.name,'ko')).forEach(r=>{
    const button=document.createElement('button');button.type='button';button.className='overlap-place-item';button.dataset.overlapRestaurant=r.id;
    const name=document.createElement('strong');name.textContent=r.name;
    const type=document.createElement('small');type.textContent=window.LunchRunCuisine.classify(r);
    const address=document.createElement('span');address.textContent=r.address;
    button.append(name,type,address);button.addEventListener('click',()=>select(r.id));items.append(button);
  });
  overlapPanel.addEventListener('click',event=>event.stopPropagation());
  overlapPanel.addEventListener('keydown',event=>{if(event.key==='Escape')closeOverlapList();});
  overlapPanel.append(heading,note,items);mapElement.append(overlapPanel);mapElement.classList.add('overlap-list-open');
}
const locateButton = document.getElementById('locate');
const locationStatus = document.getElementById('location-status');
let currentLocationOverlay = null;
let accuracyCircle = null;
let redPinImage = null;
let searchCenterOverlay = null;
let searchSequence = 0;
let searchRadius=1000;
let displayedSearchRadius=0;
let searchRadiusCircle=null;
const radiusLabel=radius=>radius<1000?`${radius}m`:`${radius/1000}km`;
const radiusSlider=document.getElementById('search-radius');
const radiusOutput=document.getElementById('radius-value');
const radiusLess=document.getElementById('radius-less');
const radiusMore=document.getElementById('radius-more');
function updateRadiusControls(){
  radiusSlider.value=String(searchRadius);
  radiusSlider.setAttribute('aria-valuetext',radiusLabel(searchRadius));
  radiusOutput.value=radiusLabel(searchRadius);
  radiusSlider.disabled=!map;
  radiusLess.disabled=!map||searchRadius<=100;
  radiusMore.disabled=!map||searchRadius>=1000;
}
function changeSearchRadius(radius){
  if(!Number.isInteger(radius)||radius<100||radius>1000||radius%100!==0)return;
  if(radius===searchRadius){updateRadiusControls();return;}
  searchRadius=radius;updateRadiusControls();
  if(searchCenter)searchNearby(searchCenter,{preserveRouteOrigin:true});
}
radiusSlider.addEventListener('input',()=>{
  const label=radiusLabel(Number(radiusSlider.value));
  radiusOutput.value=label;radiusSlider.setAttribute('aria-valuetext',label);
});
radiusSlider.addEventListener('change',()=>changeSearchRadius(Number(radiusSlider.value)));
radiusLess.addEventListener('click',()=>changeSearchRadius(searchRadius-100));
radiusMore.addEventListener('click',()=>changeSearchRadius(searchRadius+100));
const nearbyButton = document.getElementById('nearby-search');
const searchStatus = document.getElementById('search-status');
const menuData = window.MENU_DATA || {restaurants:{}};
const menuDialog = document.getElementById('menu-dialog');
let businessHoursTimer=null;
let locationRequest=null;
let approximateLocation=null;
const approximateButton=document.getElementById('use-approximate');
const mapCenterButton=document.getElementById('map-center-search');
let routeOrigin=searchCenter?{...searchCenter}:null;
let routeOriginOverlay=null;
let walkingLines=[];
let walkingEndpointPins=[];
let walkingHiddenOverlays=[];
let walkingFocused=false;
let walkingRequest=null;
let walkingSequence=0;
const walkingCache=new Map();
const originDialog=document.getElementById('route-origin-dialog');
const originStatus=document.getElementById('route-origin-status');
const originChoices=document.getElementById('route-origin-choices');
let originSearchSequence=0;
const randomButton=document.getElementById('random');
const rouletteStatus=document.getElementById('roulette-status');
let rouletteRunning=false;
let rouletteTimer=null;
let rouletteHighlightedId=null;
const nearbyPageCache=new Map();

function requestNearbyPage(bounds,page){
  const key=[bounds.west,bounds.south,bounds.east,bounds.north].map(v=>v.toFixed(7)).join(',')+'|'+page;
  const cached=nearbyPageCache.get(key);
  if(cached&&Date.now()-cached.time<300000)return Promise.resolve(cached.result);
  return new Promise((resolve,reject)=>{
    new kakao.maps.services.Places().categorySearch('FD6',(data,status,pagination)=>{
      if(status===kakao.maps.services.Status.ERROR){reject(new Error('Place search failed'));return;}
      const items=status===kakao.maps.services.Status.ZERO_RESULT?[]:data.map(p=>({
        id:p.id,name:p.place_name,address:p.road_address_name||p.address_name,
        lat:Number(p.y),lng:Number(p.x),category:p.category_name.split(' > ').pop(),categoryPath:p.category_name,url:p.place_url,source:'카카오 검색'
      }));
      const result={items,totalCount:Number(pagination?.totalCount)||items.length};
      if(nearbyPageCache.size>=1000)nearbyPageCache.delete(nearbyPageCache.keys().next().value);
      nearbyPageCache.set(key,{time:Date.now(),result});resolve(result);
    },{bounds:new kakao.maps.LatLngBounds(new kakao.maps.LatLng(bounds.south,bounds.west),new kakao.maps.LatLng(bounds.north,bounds.east)),size:15,page,sort:kakao.maps.services.SortBy.ACCURACY});
  });
}

function randomButtonLabel(text){
  const arrow=document.createElement('span');arrow.textContent='↗';
  randomButton.replaceChildren(document.createTextNode(text),arrow);
}
function clearRoulette(){
  clearTimeout(rouletteTimer);rouletteTimer=null;rouletteRunning=false;
  rouletteHighlightedId=null;
  mapElement.classList.remove('roulette-running');
  randomButton.classList.remove('is-spinning');randomButton.disabled=restaurants.length===0;
  randomButtonLabel('오늘 갈 곳 뽑기');rouletteStatus.hidden=true;
  card.setAttribute('aria-busy','false');
  document.querySelectorAll('.roulette-candidate,.roulette-dim').forEach(el=>el.classList.remove('roulette-candidate','roulette-dim'));
  document.querySelectorAll('[data-restaurant]').forEach(el=>{const active=el.dataset.restaurant===selectedId;el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));});
  markers.forEach((marker,id)=>{marker.setOpacity(id===selectedId?1:.65);marker.setZIndex(id===selectedId?10:1);});
  redrawOverlapCounts();
  
}
function highlightRouletteCandidate(id){
  document.querySelectorAll('[data-restaurant]').forEach(el=>{
    const active=el.dataset.restaurant===id;
    el.classList.toggle('active',active);el.classList.toggle('roulette-candidate',active);el.setAttribute('aria-pressed',String(active));
  });
  if(rouletteHighlightedId===null)markers.forEach(marker=>{marker.setOpacity(.25);marker.setZIndex(1);});
  else if(rouletteHighlightedId!==id){markers.get(rouletteHighlightedId)?.setOpacity(.25);markers.get(rouletteHighlightedId)?.setZIndex(1);}
  markers.get(id)?.setOpacity(1);markers.get(id)?.setZIndex(100);rouletteHighlightedId=id;
  const button=Array.from(list.children).find(el=>el.dataset.restaurant===id);
  if(button){
    const rect=button.getBoundingClientRect(),parent=list.getBoundingClientRect();
    if(rect.top<parent.top||rect.bottom>parent.bottom)list.scrollTop+=rect.top-parent.top-(list.clientHeight-rect.height)/2;
  }
}
function startRoulette(){
  if(rouletteRunning||!restaurants.length)return;
  closeOverlapList();
  
  clearWalkingRoute();
  clearRoulette();
  const candidates=[...restaurants];
  const pool=candidates.filter(r=>r.id!==selectedId);
  const winner=(pool.length?pool:candidates)[Math.floor(Math.random()*(pool.length||candidates.length))];
  let snapshot=candidates;
  // Every result can win; only the decorative animation is bounded in duration.
  if(candidates.length>15){
    const current=candidates.find(r=>r.id===selectedId);
    const others=candidates.filter(r=>r.id!==winner.id&&r.id!==selectedId);
    for(let i=others.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[others[i],others[j]]=[others[j],others[i]];}
    snapshot=[...(current?[current]:[]),...others.slice(0,current?13:14),winner];
  }
  const startIndex=Math.max(0,snapshot.findIndex(r=>r.id===selectedId));
  const winnerIndex=snapshot.findIndex(r=>r.id===winner.id);
  const remaining=(winnerIndex-startIndex+snapshot.length)%snapshot.length;
  const total=snapshot.length>1?snapshot.length*2+remaining:1;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  rouletteRunning=true;clearOverlapCounts();randomButton.disabled=true;randomButton.classList.add('is-spinning');
  randomButtonLabel('식당 고르는 중…');
  card.setAttribute('aria-busy','true');
  rouletteStatus.hidden=false;rouletteStatus.textContent='지도 마커를 하나씩 돌려보고 있어요…';
  mapElement.classList.add('roulette-running');
  // The restaurant list sits below the map on narrow screens.
  // Bring the draw into view once without scrolling on every candidate.
  mapElement.scrollIntoView({block:'center',behavior:'auto'});
  if(map&&snapshot.length>1){
    const bounds=new kakao.maps.LatLngBounds();snapshot.forEach(r=>bounds.extend(new kakao.maps.LatLng(r.lat,r.lng)));
    map.setBounds(bounds,90,55,220,55);
  }
  function finish(){
    rouletteTimer=null;rouletteRunning=false;mapElement.classList.remove('roulette-running');
    redrawOverlapCounts();
    card.scrollTop=0;
    document.querySelectorAll('.roulette-dim,.roulette-candidate').forEach(el=>el.classList.remove('roulette-dim','roulette-candidate'));
    markers.forEach((marker,id)=>marker.setOpacity(id===winner.id?1:.65));
    randomButton.disabled=false;randomButton.classList.remove('is-spinning');randomButtonLabel('다시 뽑기');
    rouletteStatus.textContent='선택 완료! 깜빡인 마커의 식당으로 정했어요.';
    card.setAttribute('aria-busy','false');
  }
  function settle(){
    select(winner.id,true,'roulette');
    markers.get(winner.id)?.setZIndex(100);
    randomButtonLabel('선택 완료!');
    rouletteStatus.textContent='마커가 깜빡인 뒤 선택이 완료돼요.';
    if(reducedMotion){rouletteTimer=setTimeout(finish,600);return;}
    let flashes=0;
    function flash(){
      if(!rouletteRunning)return;
      const dim=++flashes%2===1;
      const demoPin=Array.from(pins.children).find(el=>el.dataset.restaurant===winner.id);
      demoPin?.classList.toggle('roulette-dim',dim);
      markers.get(winner.id)?.setOpacity(dim?0:1);
      if(flashes>=6){finish();return;}
      rouletteTimer=setTimeout(flash,500);
    }
    rouletteTimer=setTimeout(flash,500);
  }
  if(reducedMotion){settle();return;}
  let step=0;
  function tick(){
    if(!rouletteRunning)return;
    const candidate=snapshot[(startIndex+ ++step)%snapshot.length];
    highlightRouletteCandidate(candidate.id);
    if(step>=total){rouletteTimer=setTimeout(settle,450);return;}
    const slowStart=Math.max(1,total-12);
    const slowdown=Math.max(0,(step-slowStart)/(total-slowStart||1));
    if(step>=slowStart){rouletteStatus.textContent='천천히 멈추고 있어요…';}
    rouletteTimer=setTimeout(tick,140+360*slowdown*slowdown);
  }
  tick();
}

function drawRouteOrigin(){
  if(routeOriginOverlay)routeOriginOverlay.setMap(null);
  routeOriginOverlay=null;
  if(!map||!window.LunchRunRoutes.validPoint(routeOrigin))return;
  // The search-center overlay already labels this point.
  if(searchCenter&&routeOrigin.lat===searchCenter.lat&&routeOrigin.lng===searchCenter.lng)return;
  const label=document.createElement('div');label.className='route-origin-label';label.textContent=`출발: ${routeOrigin.name}`;
  routeOriginOverlay=new kakao.maps.CustomOverlay({map,position:new kakao.maps.LatLng(routeOrigin.lat,routeOrigin.lng),content:label,yAnchor:1.5,zIndex:35});
}
function setRouteOrigin(origin){
  cancelLocationRequest();
  locationStatus.hidden=true;
  routeOrigin={...origin};++originSearchSequence;
  originDialog.close();drawRouteOrigin();select(selectedId,false);
}
function openRouteOrigin(){
  originChoices.replaceChildren();
  originStatus.textContent=map?'식당까지 길찾기에 사용할 출발지를 선택하세요.':'지도 연결 후 장소를 검색할 수 있어요. 현재 검색 기준점은 사용할 수 있습니다.';
  document.getElementById('route-use-map-center').disabled=!map;
  document.getElementById('route-use-search-center').disabled=!window.LunchRunRoutes.validPoint(searchCenter);
  originDialog.showModal();
}
document.getElementById('route-origin-close').addEventListener('click',()=>originDialog.close());
originDialog.addEventListener('close',()=>{++originSearchSequence;});
document.getElementById('route-use-search-center').addEventListener('click',()=>{if(searchCenter)setRouteOrigin(searchCenter);});
document.getElementById('route-use-map-center').addEventListener('click',()=>{
  if(!map)return;const point=map.getCenter();setRouteOrigin({name:'지도에서 선택한 출발지',lat:point.getLat(),lng:point.getLng()});
});
document.getElementById('route-origin-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(!map||!window.kakao?.maps?.services){originStatus.textContent='지도 연결 후 다시 검색해주세요.';return;}
  const query=document.getElementById('route-origin-query').value.trim();if(!query)return;
  const sequence=++originSearchSequence;originChoices.replaceChildren();originStatus.textContent='출발할 장소를 찾고 있어요…';
  new kakao.maps.services.Places().keywordSearch(query,(data,status)=>{
    if(sequence!==originSearchSequence||!originDialog.open)return;
    if(status!==kakao.maps.services.Status.OK){originStatus.textContent='장소를 찾지 못했어요. 지역명과 장소명을 함께 입력해주세요.';return;}
    originStatus.textContent='아래에서 출발지를 선택하세요.';
    data.forEach(place=>{
      const button=document.createElement('button');button.type='button';
      const name=document.createElement('strong');name.textContent=place.place_name;
      const address=document.createElement('small');address.textContent=place.road_address_name||place.address_name;
      button.append(name,address);button.addEventListener('click',()=>setRouteOrigin({name:place.place_name,lat:Number(place.y),lng:Number(place.x)}));originChoices.append(button);
    });
  },{size:5});
});

function restoreRestaurantPins(){
  if(!walkingFocused)return;
  walkingFocused=false;
  markers.forEach(marker=>marker.setMap(map));
  redrawOverlapCounts();
  const current=[searchCenterOverlay,searchRadiusCircle,currentLocationOverlay,accuracyCircle,routeOriginOverlay];
  walkingHiddenOverlays.forEach(overlay=>{if(current.includes(overlay))overlay.setMap(map);});
  walkingHiddenOverlays=[];
}
function focusWalkingRoute(){
  closeOverlapList();
  clearOverlapCounts();
  
  walkingFocused=true;
  markers.forEach(marker=>marker.setMap(null));
  walkingHiddenOverlays=[searchCenterOverlay,searchRadiusCircle,currentLocationOverlay,accuracyCircle,routeOriginOverlay].filter(overlay=>overlay&&overlay.getMap()===map);
  walkingHiddenOverlays.forEach(overlay=>overlay.setMap(null));
}
function clearWalkingRoute(){
  ++walkingSequence;
  walkingRequest?.abort();walkingRequest=null;
  walkingLines.forEach(line=>line.setMap(null));walkingLines=[];
  walkingEndpointPins.forEach(pin=>pin.setMap(null));walkingEndpointPins=[];
  restoreRestaurantPins();
}
function paintWalkingRoute(result,origin,destination){
  if(!map)return;
  walkingLines.forEach(line=>line.setMap(null));walkingLines=[];
  const bounds=new kakao.maps.LatLngBounds();
  for(const [point,label,color] of [[origin,'출발','#16825d'],[destination,'도착','#e53935']]){
    const content=document.createElement('div');content.className='walking-endpoint-pin';
    content.setAttribute('role','img');content.setAttribute('aria-label',`${label}: ${point.name||label}`);
    content.title=`${label}: ${point.name||label}`;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('width','52');svg.setAttribute('height','64');svg.setAttribute('viewBox','0 0 52 64');svg.setAttribute('aria-hidden','true');
    const shape=document.createElementNS(svg.namespaceURI,'path');shape.setAttribute('d','M26 63C22 54 3 37 3 25a23 23 0 1 1 46 0c0 12-19 29-23 38Z');shape.setAttribute('fill',color);shape.setAttribute('stroke','#fff');shape.setAttribute('stroke-width','2');
    const text=document.createElementNS(svg.namespaceURI,'text');text.setAttribute('x','26');text.setAttribute('y','29');text.setAttribute('text-anchor','middle');text.setAttribute('fill','#fff');text.setAttribute('font-size','13');text.setAttribute('font-weight','700');text.textContent=label;
    svg.append(shape,text);content.append(svg);
    const position=new kakao.maps.LatLng(point.lat,point.lng);bounds.extend(position);
    walkingEndpointPins.push(new kakao.maps.CustomOverlay({map,position,content,xAnchor:.5,yAnchor:1,zIndex:1200}));
  }
  result.paths.forEach(path=>{
    const points=path.map(([lng,lat])=>new kakao.maps.LatLng(lat,lng));
    points.forEach(point=>bounds.extend(point));
    walkingLines.push(new kakao.maps.Polyline({map,path:points,strokeWeight:6,strokeColor:'#2878E8',strokeOpacity:.9,strokeStyle:'solid',zIndex:20}));
  });
  window.LunchRunRoutes.walkingConnections(result.paths,origin,destination).forEach(path=>{
    walkingLines.push(new kakao.maps.Polyline({map,path:path.map(([lng,lat])=>new kakao.maps.LatLng(lat,lng)),strokeWeight:4,strokeColor:'#2878E8',strokeOpacity:.9,strokeStyle:'shortdash',zIndex:21}));
  });
  if(result.paths.length){
    const wide=mapElement.clientWidth>=650;
    const left=wide?Math.min(card.offsetWidth+50,mapElement.clientWidth*.6):25;
    const bottom=wide?45:Math.min(card.offsetHeight+35,mapElement.clientHeight*.7);
    map.setBounds(bounds,45,35,bottom,left);
  }
}
async function loadWalkingRoute(restaurant,section,note,button,force=false){
  if(!window.LunchRunRoutes.validPoint(routeOrigin)){openRouteOrigin();return;}
  clearWalkingRoute();
  focusWalkingRoute();
  const cancel=section.querySelector('.walking-route-cancel');
  cancel.hidden=false;
  const sequence=walkingSequence;
  const origin={lat:routeOrigin.lat,lng:routeOrigin.lng};
  const destination={lat:restaurant.lat,lng:restaurant.lng};
  const key=JSON.stringify([origin,destination]);
  const controller=new AbortController();walkingRequest=controller;
  button.disabled=true;button.textContent='도보 경로 확인 중…';
  note.textContent='실제 걸어가는 길과 예상 시간을 찾고 있어요…';note.classList.remove('route-error');
  try{
    let cached=walkingCache.get(key),result;
    if(!force&&cached&&Date.now()-cached.at<300000)result=cached.result;
    else{
      const response=await fetch('api/walking-route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({origin,destination}),signal:controller.signal});
      const body=await response.json().catch(()=>null);
      if(!response.ok)throw new Error(body?.error||'도보 경로를 불러오지 못했어요. 개발 서버에서 다시 시도해주세요.');
      result=body;
      if(!Number.isFinite(result?.duration)||!Number.isFinite(result?.distance)||!Array.isArray(result.paths))throw new Error('도보 경로 정보를 확인하지 못했어요.');
      if(walkingCache.size>=100)walkingCache.delete(walkingCache.keys().next().value);
      walkingCache.set(key,{at:Date.now(),result});
    }
    if(sequence!==walkingSequence||!section.isConnected)return;
    note.replaceChildren();
    const estimate=document.createElement('strong');estimate.className='walking-estimate';
    estimate.textContent=`도보 약 ${window.LunchRunRoutes.formatDuration(result.duration)} · ${window.LunchRunRoutes.formatDistance(result.distance)}`;
    const detail=document.createElement('span');detail.textContent='카카오 도보 경로 기준 · 실제 시간은 달라질 수 있어요.';
    if(window.LunchRunRoutes.walkingConnections(result.paths,origin,destination).length)detail.textContent+=' 점선: 핀과 경로 사이 연결 구간';
    note.append(estimate,detail);paintWalkingRoute(result,{...origin,name:routeOrigin.name},restaurant);
  }catch(error){
    if(error.name==='AbortError'||sequence!==walkingSequence||!section.isConnected)return;
    restoreRestaurantPins();
    cancel.hidden=true;
    note.textContent=error.message;note.classList.add('route-error');
  }finally{
    if(sequence===walkingSequence&&section.isConnected){button.disabled=false;button.textContent='경로 다시 찾기';walkingRequest=null;}
  }
}
function appendDirections(restaurant,container=card){
  const section=document.createElement('section');section.className='route-panel';section.setAttribute('aria-label','이동 시간과 길찾기');
  const top=document.createElement('div');top.className='route-heading';
  const title=document.createElement('strong');title.textContent='도보 길찾기';
  const change=document.createElement('button');change.type='button';change.textContent='출발지 변경';change.addEventListener('click',openRouteOrigin);top.append(title,change);
  const origin=document.createElement('p');origin.className='route-from';origin.textContent=routeOrigin?`출발: ${routeOrigin.name}`:'출발지를 선택해주세요.';
  const note=document.createElement('p');note.className='route-time-note';note.setAttribute('role','status');note.textContent='경로찾기를 눌러 도보 시간과 길을 확인하세요.';
  const walk=document.createElement('button');walk.type='button';walk.className='walking-route-button';walk.textContent='경로찾기';
  walk.addEventListener('click',()=>loadWalkingRoute(restaurant,section,note,walk,true));
  const cancel=document.createElement('button');cancel.type='button';cancel.className='walking-route-cancel';cancel.textContent='경로찾기 취소';cancel.hidden=true;
  cancel.addEventListener('click',()=>{
    select(restaurant.id,false);
    if(map&&restaurants.length){
      const bounds=new kakao.maps.LatLngBounds();
      restaurants.forEach(r=>bounds.extend(new kakao.maps.LatLng(r.lat,r.lng)));
      if(searchRadiusCircle){const radius=searchRadiusCircle.getBounds();bounds.extend(radius.getSouthWest());bounds.extend(radius.getNorthEast());}
      map.setBounds(bounds,60,35,35,Math.min(card.offsetWidth+40,mapElement.clientWidth*.6));
    }
    card.querySelector('.walking-route-button')?.focus({preventScroll:true});
  });
  const actions=document.createElement('div');actions.className='walking-route-actions';actions.append(walk,cancel);
  section.append(top,origin,note,actions);container.append(section);
}

function cancelLocationRequest() {
  if(locationRequest)locationRequest.cancel();
  locationRequest=null;approximateLocation=null;
  approximateButton.hidden=true;
  locateButton.disabled=!map;locateButton.textContent='◎ 내 위치';
}

document.getElementById('menu-close').addEventListener('click',()=>menuDialog.close());
function openMenus(id) {
  const data=menuData.restaurants[id];
  if (!data?.menus?.length) return;
  document.getElementById('menu-title').textContent=data.restaurantName;
  const menuItems=document.getElementById('menu-items');menuItems.replaceChildren();
  data.menus.forEach(menu=>{
    const row=document.createElement('div');row.className='menu-row';
    const name=document.createElement('span');name.textContent=menu.name;
    if(menu.soldOut)name.append(' · 품절 표기');
    if(menu.description){const description=document.createElement('small');description.className='menu-description';description.textContent=menu.description;name.append(description);}
    const price=document.createElement('strong');
    price.textContent=menu.priceText || (Number.isFinite(menu.price)?menu.price.toLocaleString('ko-KR')+'원':'가격 확인 필요');
    row.append(name,price);menuItems.append(row);
  });
  const date=(data.retrievedAt || menuData.retrievedAt || '').slice(0,10);
  const source=document.getElementById('menu-source');source.replaceChildren();
  source.append(`출처: ${data.source || menuData.source} · 확인 ${date} · 매장 가격과 다를 수 있어요. `);
  if(data.sourceUrl){const link=document.createElement('a');link.href=data.sourceUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='원문 보기 ↗';source.append(link);}
  menuDialog.showModal();
}
document.getElementById('count').textContent = `${restaurants.length}곳`;
document.getElementById('origin').textContent = location.protocol === 'file:' ? 'http://localhost:5500 (개발 서버로 실행하세요)' : location.origin;

function appendBusinessHours(restaurant,container){
  const record=window.LunchRunBusinessHours.recordFor(restaurant);
  const section=document.createElement('div');section.className='business-hours';
  const line=document.createElement('div');line.className='business-hours-line';
  const badge=document.createElement('span');badge.className='business-status';badge.setAttribute('role','status');
  const description=document.createElement('small');line.append(badge,description);section.append(line);
  const update=()=>{
    if(!section.isConnected){clearInterval(businessHoursTimer);return;}
    const state=window.LunchRunBusinessHours.status(record);
    badge.textContent=state.label;badge.className='business-status is-'+state.kind;
    description.textContent=state.kind==='unknown'?state.detail:`영업시간 기준 · ${state.detail}`;
    badge.title=state.detail;
  };
  if(record?.status==='hours'&&record.raw&&record.sourceUrl&&!record.identityReview){
    const disclosure=document.createElement('details');disclosure.className='business-hours-details';
    const summary=document.createElement('summary');summary.textContent='영업시간·확인일';
    const hours=document.createElement('p');hours.className='business-hours-raw';
    hours.textContent=record.raw.replace(/^(?:.|\n)*?(?=(?:월|화|수|목|금|토|일|매일)(?:\n|\())/,'');
    const evidence=document.createElement('p');evidence.className='business-hours-evidence';
    const checked=record.checkedAt?window.LunchRunBusinessHours.koreanTime(new Date(record.checkedAt)).date:'확인일 미상';
    evidence.append(`등록 영업시간 기준 · 확인 ${checked}. 임시휴무는 매장에 확인해주세요. `);
    const source=document.createElement('a');source.href=record.sourceUrl;source.target='_blank';source.rel='noopener noreferrer';source.textContent='영업시간 원문 ↗';evidence.append(source);
    disclosure.append(summary,hours,evidence);section.append(disclosure);
  }
  container.append(section);update();businessHoursTimer=setInterval(update,60000);
}
function select(id, pan = true, source = 'manual') {
  closeOverlapList();
  
  clearInterval(businessHoursTimer);
  clearWalkingRoute();
  if(source!=='roulette'){clearRoulette();card.setAttribute('aria-busy','false');}
  selectedId = id;
  const r = restaurants.find(r => r.id === id);
  if (!r) return;
  document.querySelectorAll('[data-restaurant]').forEach(el => {
    const active = el.dataset.restaurant === id;
    el.classList.toggle('active', active);
    el.setAttribute('aria-pressed', String(active));
  });
  card.replaceChildren();
  card.classList.remove('is-collapsed');
  const heading=document.createElement('div');heading.className='restaurant-card-heading';
  const title=document.createElement('h2');title.textContent=r.name;
  const details=document.createElement('div');details.id='restaurant-card-body';
  const toggle=document.createElement('button');toggle.type='button';toggle.className='restaurant-card-toggle';
  toggle.setAttribute('aria-controls',details.id);
  function updateToggle(){
    toggle.textContent=details.hidden?'펼치기 ▾':'접기 ▴';
    toggle.setAttribute('aria-expanded',String(!details.hidden));
    toggle.setAttribute('aria-label',details.hidden?'가게 정보 펼치기':'가게 정보 접기');
    card.classList.toggle('is-collapsed',details.hidden);
  }
  toggle.addEventListener('click',()=>{details.hidden=!details.hidden;updateToggle();});
  updateToggle();heading.append(title,toggle);card.append(heading,details);
  const top = document.createElement('div'); top.className = 'card-top';
  const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = window.LunchRunCuisine.classify(r);
  const selected = document.createElement('span'); selected.textContent = Number.isFinite(r.distance) ? `기준점에서 직선 ${r.distance.toLocaleString('ko-KR')}m` : '선택한 식당';
  top.append(badge, selected);
  const address = document.createElement('p'); address.textContent = r.address;
  const bottom = document.createElement('div'); bottom.className = 'card-bottom';
  const coords = document.createElement('code'); coords.textContent = `${r.lat.toFixed(5)}, ${r.lng.toFixed(5)}`;
  const link = document.createElement('a'); link.href = r.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = '카카오맵에서 보기 ↗';
  bottom.append(coords, link); details.append(top, address, bottom);
  appendBusinessHours(r,details);
  if(r.source==='인허가 자료'){
    const source=document.createElement('p');source.className='restaurant-source';source.textContent='인허가 자료의 위치입니다. 카카오 장소와의 연결 및 현재 영업 여부는 확인이 필요해요.';details.append(source);
    link.textContent='주소로 지도 보기 ↗';
  }
  if(r.source==='네이버 확인 자료'){
    const source=document.createElement('p');source.className='restaurant-source';source.textContent='네이버 확인 가게 · 방문 전 영업 여부를 확인해주세요.';details.append(source);
    link.textContent='네이버 플레이스에서 보기 ↗';
  }
  appendDirections(r,details);
  const menuRecord=menuData.restaurants[r.id];
  if (menuRecord?.menus?.length) {
    const menuButton=document.createElement('button');menuButton.className='menu-open';
    menuButton.textContent=`메뉴·가격 보기 (${menuRecord.menus.length}개)`;
    menuButton.addEventListener('click',()=>openMenus(r.id));details.append(menuButton);
  } else {
    const missing=document.createElement('p');missing.className='menu-missing';
    missing.textContent=r.source==='네이버 확인 자료'?'연결된 메뉴 정보가 없어요. 네이버 플레이스에서 확인해주세요.':'연결된 메뉴 정보가 없어요. 카카오맵에서 확인해주세요.';details.append(missing);
  }
  if (map) {
    const p = new kakao.maps.LatLng(r.lat, r.lng);
    if (pan) map.panTo(p);
    markers.forEach((marker, markerId) => {
      marker.setZIndex(markerId === id ? 10 : 1);
      marker.setOpacity(markerId === id ? 1 : .65);
    });
  }
}

function renderRestaurants() {
closeOverlapList();
clearOverlapCounts();

clearWalkingRoute();
clearRoulette();card.setAttribute('aria-busy','false');
list.replaceChildren(); pins.replaceChildren();
document.getElementById('count').textContent = `${restaurants.length}곳`;
document.getElementById('random').disabled = restaurants.length === 0;
const latitudeMin = Math.min(...restaurants.map(r => r.lat));
const latitudeMax = Math.max(...restaurants.map(r => r.lat));
const longitudeMin = Math.min(...restaurants.map(r => r.lng));
const longitudeMax = Math.max(...restaurants.map(r => r.lng));
restaurants.forEach((r, i) => {
  const button = document.createElement('button');
  button.className = 'restaurant-item'; button.dataset.restaurant = r.id;
  const number = document.createElement('span'); number.className = 'number'; number.textContent = String(i + 1).padStart(2, '0');
  const info = document.createElement('span');
  const name = document.createElement('strong'); name.textContent = r.name;
  const cuisine=window.LunchRunCuisine.classify(r);
  const sub = document.createElement('small'); sub.textContent = Number.isFinite(r.distance) ? `${cuisine} · 직선 ${r.distance.toLocaleString('ko-KR')}m` : cuisine;
  if (menuData.restaurants[r.id]?.menus?.length) sub.textContent+=' · 메뉴 있음';
  if(r.source==='인허가 자료')sub.textContent+=' · 인허가 자료';
  if(r.source==='네이버 확인 자료')sub.textContent+=' · 네이버 확인';
  info.append(name, sub); button.append(number, info); button.addEventListener('click', () => select(r.id)); list.append(button);
  const pin = document.createElement('button'); pin.className = 'pin'; pin.dataset.restaurant = r.id; pin.setAttribute('aria-label', `${r.name} 선택`);
  pin.style.left = `${18 + (r.lng-longitudeMin)/(longitudeMax-longitudeMin || 1)*64}%`;
  pin.style.top = `${23 + (latitudeMax-r.lat)/(latitudeMax-latitudeMin || 1)*38}%`;
  const label = document.createElement('span'); label.className = 'pin-label'; label.textContent = r.name;
  const symbol = document.createElement('span'); symbol.className = 'pin-symbol'; symbol.textContent = i + 1;
  pin.append(label, symbol); pin.addEventListener('click', () => select(r.id)); pins.append(pin);
});
}

function drawRestaurantMarkers() {
  closeOverlapList();
  clearOverlapCounts();
  
  markers.forEach(marker => marker.setMap(null)); markers.clear();
  if (searchCenterOverlay) searchCenterOverlay.setMap(null);
  if(searchRadiusCircle)searchRadiusCircle.setMap(null);
  searchRadiusCircle=null;
  const bounds = new kakao.maps.LatLngBounds();
  if (searchCenter) {
    const point = new kakao.maps.LatLng(searchCenter.lat, searchCenter.lng);
    bounds.extend(point);
    if(displayedSearchRadius){
      searchRadiusCircle=new kakao.maps.Circle({map,center:point,radius:displayedSearchRadius,strokeWeight:2,strokeColor:'#679354',strokeOpacity:.65,strokeStyle:'shortdash',fillColor:'#7da65e',fillOpacity:.035,zIndex:0});
      const radiusBounds=searchRadiusCircle.getBounds();
      bounds.extend(radiusBounds.getSouthWest());bounds.extend(radiusBounds.getNorthEast());
    }
    if (searchCenter.name !== '내 위치') {
      const label = document.createElement('div'); label.className = 'search-center-label';
      label.textContent = `검색 기준: ${searchCenter.name}`;
      searchCenterOverlay = new kakao.maps.CustomOverlay({map,position:point,content:label,yAnchor:1.5,zIndex:30});
    }
  }
  restaurants.forEach(r => {
    const position = new kakao.maps.LatLng(r.lat, r.lng);
    const marker = new kakao.maps.Marker({map,position,title:r.name,image:redPinImage});
    kakao.maps.event.addListener(marker,'click',()=>handleRestaurantPinClick(r.id));
    markers.set(r.id,marker); bounds.extend(position);
  });
  
  if (restaurants.length || searchCenter) map.setBounds(bounds, 65, 55, 220, 55);
  if(searchCenter&&['내 위치','대략 위치','지도에서 선택한 위치'].includes(searchCenter.name)){
    map.setCenter(new kakao.maps.LatLng(searchCenter.lat,searchCenter.lng));
  }
  if (restaurants.length) select(restaurants[0].id, false);
  else card.replaceChildren();
  drawRouteOrigin();
  redrawOverlapCounts();
}

async function searchNearby(center,{preserveRouteOrigin=false}={}) {
  clearWalkingRoute();
  if (!map || !kakao.maps.services) { searchStatus.textContent = '카카오 지도 연결을 기다려주세요.'; return; }
  clearRoulette();card.setAttribute('aria-busy','false');
  cancelLocationRequest();
  if(center.name!=='내 위치'&&center.name!=='대략 위치'){
    if(currentLocationOverlay)currentLocationOverlay.setMap(null);
    if(accuracyCircle)accuracyCircle.setMap(null);
    locationStatus.hidden=true;
  }
  const sequence = ++searchSequence;
  const radius=searchRadius;
  searchStatus.textContent = `${center.name} 반경 ${radiusLabel(radius)}의 음식점을 검색하고 있어요…`;
  let lastProgress=0;
  const result=await window.LunchRunNearby.collectNearby({
    center,radius,knownPlaces:(window.DISTRICT_RESTAURANTS?.restaurants||[]).map(r=>({...r,menuCount:menuData.restaurants[r.id]?.menus?.length||0})),excludedIds:window.DISTRICT_RESTAURANTS?.excludedIds||[],excludedPlaces:window.DISTRICT_RESTAURANTS?.excludedPlaces||[],requestPage:requestNearbyPage,
    isCurrent:()=>sequence===searchSequence,
    onProgress:progress=>{
      if(sequence===searchSequence&&Date.now()-lastProgress>600){
        lastProgress=Date.now();searchStatus.textContent=`${center.name} 반경 ${radiusLabel(radius)} 검색 중 · ${progress.count.toLocaleString('ko-KR')}곳 확인`;
      }
    }
  });
  if(!result||sequence!==searchSequence)return;
    searchCenter = center;
    displayedSearchRadius=radius;
    if(!preserveRouteOrigin)routeOrigin={...center};
    allRestaurants=result.restaurants;
    window.LunchRunCuisine.populate(cuisineFilter,allRestaurants);
    applyCuisineFilter();
    document.getElementById('search-location').textContent = `◎ ${center.name} 기준 · 반경 ${radiusLabel(radius)}`;
    document.getElementById('list-title').textContent = `${center.name} 주변 음식점`;
    const warning=result.errors?' · 일부 구역 조회 실패':result.saturatedCells?' · 일부 밀집 구역은 제공 한도로 누락 가능':'';
    searchStatus.textContent = allRestaurants.length ? `${center.name} 반경 ${radiusLabel(radius)} · 전체 ${allRestaurants.length.toLocaleString('ko-KR')}곳 · 음식 종류별로 볼 수 있어요${warning}` : `반경 ${radiusLabel(radius)}에 검색 결과가 없어요. 다른 기준 장소를 선택해주세요.${warning}`;
}

nearbyButton.addEventListener('click',()=>locateButton.click());
document.getElementById('place-search-form').addEventListener('submit',event=>{
  event.preventDefault();
  if (!map || !kakao.maps.services) return;
  const query = document.getElementById('place-query').value.trim();
  if (!query) { searchStatus.textContent='역이나 장소 이름을 입력해주세요.'; return; }
  const choices=document.getElementById('place-choices'); choices.replaceChildren();
  searchStatus.textContent='검색 기준으로 사용할 장소를 찾고 있어요…';
  new kakao.maps.services.Places().keywordSearch(query,(data,status)=>{
    if (status!==kakao.maps.services.Status.OK) {searchStatus.textContent='장소를 찾지 못했어요. 지역과 장소명을 함께 입력해주세요.';return;}
    searchStatus.textContent='검색 기준으로 사용할 장소를 선택해주세요.';
    data.forEach(p=>{
      const button=document.createElement('button');button.type='button';
      const name=document.createElement('strong');name.textContent=p.place_name;
      const address=document.createElement('small');address.textContent=p.road_address_name||p.address_name;
      button.append(name,address);
      button.addEventListener('click',()=>{choices.replaceChildren();searchNearby({name:p.place_name,lat:Number(p.y),lng:Number(p.x)});});
      choices.append(button);
    });
  },{size:5});
});
randomButton.addEventListener('click',startRoulette);
document.getElementById('setup-open').addEventListener('click', () => setup.showModal());
document.getElementById('setup-close').addEventListener('click', () => setup.close());

function applyLocation(position, approximate=false) {
    clearWalkingRoute();
    const {latitude,longitude,accuracy}=position;
    const locationName=approximate?'대략 위치':'내 위치';
    const point = new kakao.maps.LatLng(latitude, longitude);
    if (currentLocationOverlay) currentLocationOverlay.setMap(null);
    if (accuracyCircle) accuracyCircle.setMap(null);
    const dot = document.createElement('div');
    dot.className = 'user-location';
    dot.setAttribute('role', 'img');
    dot.setAttribute('aria-label', approximate?'정확도가 낮은 추정 위치':'기기의 추정 현재 위치');
    const label = document.createElement('span'); label.textContent = locationName;
    dot.append(label);
    currentLocationOverlay = new kakao.maps.CustomOverlay({
      map, position: point, content: dot, xAnchor: .5, yAnchor: .5, zIndex: 50
    });
    accuracyCircle = new kakao.maps.Circle({
      map, center: point, radius: accuracy, strokeWeight: 1,
      strokeColor: '#2878E8', strokeOpacity: .35,
      fillColor: '#2878E8', fillOpacity: .09
    });
    map.setLevel(4);map.panTo(point);
    locationStatus.hidden=false;
    locationStatus.textContent=`${locationName} · 기기 추정 오차 약 ${Math.max(1,Math.round(accuracy)).toLocaleString('ko-KR')}m. 위치가 다르면 지도를 움직여 검색해주세요.`;
    searchNearby({name:locationName,lat:latitude,lng:longitude});
}

mapCenterButton.addEventListener('click',()=>{
  if(!map)return;
  const point=map.getCenter();
  searchNearby({name:'지도에서 선택한 위치',lat:point.getLat(),lng:point.getLng()});
});
approximateButton.addEventListener('click',()=>{
  if(approximateLocation)applyLocation(approximateLocation,true);
});
locateButton.addEventListener('click', () => {
  cancelLocationRequest();
  locationStatus.hidden = false;
  if (!map) { locationStatus.textContent = '카카오 지도가 연결된 후 이용할 수 있어요.'; return; }
  if (!navigator.geolocation || !window.isSecureContext) {
    locationStatus.textContent = '이 브라우저에서는 위치를 확인할 수 없어요. HTTPS 또는 localhost에서 열어주세요.';
    return;
  }
  locateButton.disabled = true;
  locateButton.textContent = '위치 확인 중…';
  locationStatus.textContent = '새 위치를 정밀 요청하고 있어요. 최대 30초 정도 걸릴 수 있어요.';
  // Invalidate an earlier nearby search while a fresh location is being resolved.
  const locationSequence=++searchSequence;
  locationRequest=window.LunchRunLocation.requestLocation({
    geolocation:navigator.geolocation,
    onProgress:position=>{
      locationStatus.textContent=`현재 추정 오차 약 ${Math.round(position.accuracy).toLocaleString('ko-KR')}m · 더 정확한 위치를 기다리고 있어요. 아직 지도에 적용하지 않았어요.`;
    },
    onResult:result=>{
      locationRequest=null;locateButton.textContent='◎ 내 위치 다시 확인';locateButton.disabled=false;
      if(result.kind==='accurate'){applyLocation(result.position);return;}
      if(result.kind==='approximate'){
        approximateLocation=result.position;
        locationStatus.textContent=`위치 오차가 약 ${Math.round(result.position.accuracy).toLocaleString('ko-KR')}m로 커서 자동 이동하지 않았어요. 지도를 직접 움직여 검색하거나 대략 위치를 선택해주세요.`;
        approximateButton.textContent=`대략 위치 사용 (오차 약 ${Math.round(result.position.accuracy).toLocaleString('ko-KR')}m)`;
        approximateButton.hidden=false;return;
      }
    const messages = {
      1: '위치 접근이 차단됐어요. 브라우저의 사이트 권한에서 위치를 허용한 뒤 다시 눌러주세요.',
      2: '위치 제공자가 좌표를 반환하지 못했어요. 아래 오류 상세를 확인해주세요.',
      3: '30초 동안 기기에서 위치 정보를 받지 못했어요. 권한 허용 상태에서도 위치 제공자가 응답하지 않을 수 있어요.'
    };
      const diagnosticText=(messages[result.code] || '위치를 확인하지 못했어요.')+` [오류 ${result.code}]`+(result.message?` ${result.message}`:'');
      locationStatus.textContent=diagnosticText;
      if(navigator.permissions?.query){
        navigator.permissions.query({name:'geolocation'}).then(permission=>{
          if(searchSequence!==locationSequence)return;
          const permissionLabel={granted:'허용',denied:'차단',prompt:'허용 확인 전'}[permission.state]||permission.state;
          locationStatus.textContent=diagnosticText+` · 브라우저 위치 권한: ${permissionLabel}`;
        }).catch(()=>{});
      }
      searchStatus.textContent = '현재 위치를 받지 못했어요. 지도를 움직여 중심으로 검색하거나 가까운 역·장소를 입력해주세요.';
    }
  });
});
document.getElementById('setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const key = document.getElementById('javascript-key').value.trim();
  const error = document.getElementById('setup-error');
  if (!key) { error.textContent = 'JavaScript 키를 입력해주세요.'; return; }
  error.textContent = '카카오 지도를 불러오는 중입니다…';
  try { await loadKakao(key); setup.close(); } catch (_) { error.textContent = '연결되지 않았습니다. JavaScript 키·등록 도메인·카카오맵 활성화를 확인해주세요.'; }
});

async function loadKakao(key) {
  if (map) return;
  if (location.protocol === 'file:') throw new Error('A registered HTTP origin is required');
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`;
    script.onload = () => { if (window.kakao?.maps?.load) kakao.maps.load(resolve); else reject(new Error('SDK unavailable')); };
    script.onerror = reject;
    document.head.append(script);
    setTimeout(() => reject(new Error('SDK timeout')), 15000);
  });
  // Keep the working example if SDK initialization fails.
  const live = document.createElement('div'); live.style.cssText = 'position:absolute;inset:0';
  mapElement.prepend(live);
  try {
    map = new kakao.maps.Map(live, { center: new kakao.maps.LatLng(restaurants[0].lat, restaurants[0].lng), level: 5 });
    ['click','dragstart','zoom_start'].forEach(event=>kakao.maps.event.addListener(map,event,closeOverlapList));
    ['dragstart','zoom_start'].forEach(event=>kakao.maps.event.addListener(map,event,clearOverlapCounts));
    kakao.maps.event.addListener(map,'idle',redrawOverlapCounts);
    window.addEventListener('resize',closeOverlapList);
    const redPinSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="48" viewBox="0 0 36 48"><path d="M18 46C15 41 2 27 2 18a16 16 0 1 1 32 0c0 9-13 23-16 28Z" fill="#E53935" stroke="#FFFFFF" stroke-width="2"/><circle cx="18" cy="18" r="5.5" fill="#FFFFFF"/></svg>';
    redPinImage = new kakao.maps.MarkerImage(
      'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(redPinSvg),
      new kakao.maps.Size(36, 48),
      { offset: new kakao.maps.Point(18, 46) }
    );
    drawRestaurantMarkers();
    document.getElementById('illustration').hidden = true; pins.hidden = true;
    mapElement.classList.add('kakao-on');
    document.getElementById('mode-label').textContent = '카카오맵 · 실제 지도';
    document.getElementById('setup-open').textContent = '카카오맵 연결됨';
    locateButton.disabled = false;
    nearbyButton.disabled = false;
    updateRadiusControls();
    mapCenterButton.disabled = false;
    document.getElementById('place-submit').disabled = false;
    if (searchCenter) {
      document.getElementById('list-title').textContent = `${searchCenter.name} 주변 음식점`;
      searchNearby(searchCenter,{preserveRouteOrigin:true});
    }
  } catch (error) { live.remove(); map = null; throw error; }
}
updateRadiusControls();
renderRestaurants();
select(selectedId);
if (location.protocol !== 'file:') {
  fetch('config.json').then(r=>r.ok?r.json():{}).then(config=>{
    if(config.javascriptKey) loadKakao(config.javascriptKey).catch(()=>{
      document.getElementById('map-hint').textContent = '카카오맵 연결 설정을 확인해주세요. 현재는 핀 동작 예시입니다.';
    });
  }).catch(()=>{});
}
