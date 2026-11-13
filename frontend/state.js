// 같은 탭의 홈·게임·지도·챗봇이 공유하는 상태. 서버 요청의 검증은 계속 백엔드가 담당합니다.
window.LunchRunState=(()=>{
  const KEY='lunchrun:state:v1',listeners=new Set();
  const cuisines=['전체','한식','중식','일식/회','양식','분식','패스트푸드','치킨','도시락/구내식당','뷔페식','냉면','고기','카페/빵','술집','기타'];
  const copy=value=>JSON.parse(JSON.stringify(value));
  const defaults=()=>({schema:1,revision:0,contextRevision:0,location:null,conditions:{budget:5000,radius_m:500,cuisine:'전체',people:1,deadline:Date.now()+60*60000},menu:null,restaurants:[],candidateRestaurants:[],selectedRestaurantId:null,route:null,game:null,chat:null,searchedAt:null});
  let memory=defaults();
  function validLocation(p){return p&&Number.isFinite(p.lat)&&Number.isFinite(p.lng)&&Math.abs(p.lat)<=90&&Math.abs(p.lng)<=180&&typeof p.name==='string'&&p.name.length>0&&p.name.length<=200&&['geolocation','address','place'].includes(p.source);}
  function cleanLocation(p){
    if(p===null)return null;if(!validLocation(p))throw Error('출발 위치를 확인해주세요.');
    const result={lat:p.lat,lng:p.lng,name:p.name,address:typeof p.address==='string'?p.address.slice(0,500):'',source:p.source};
    if(Number.isFinite(p.accuracy)&&p.accuracy>=0)result.accuracy=p.accuracy;
    return result;
  }
  function validConditions(c){return c&&Number.isInteger(c.budget)&&c.budget>=1000&&c.budget<=100000&&Number.isInteger(c.radius_m)&&c.radius_m>=50&&c.radius_m<=500&&cuisines.includes(c.cuisine)&&Number.isSafeInteger(c.people)&&c.people>=1&&Number.isFinite(c.deadline);}
  const validMenu=m=>m===null||(m&&typeof m.id==='string'&&m.id.length>0&&m.id.length<=40&&typeof m.name==='string'&&m.name.length>0&&m.name.length<=100);
  function read(){
    try{
      const raw=sessionStorage.getItem(KEY);
      if(raw){const saved=JSON.parse(raw);
        if(saved.conditions&&Number.isInteger(saved.conditions.radius_m)&&saved.conditions.radius_m>500&&saved.conditions.radius_m<=1000){saved.conditions.radius_m=500;saved.contextRevision=(saved.contextRevision||0)+1;saved.menu=null;saved.restaurants=[];saved.candidateRestaurants=[];saved.selectedRestaurantId=null;saved.route=null;saved.searchedAt=null;sessionStorage.setItem(KEY,JSON.stringify(saved));}
        if(saved.schema!==1||!validConditions(saved.conditions)||!validMenu(saved.menu)||!Array.isArray(saved.restaurants)||!Array.isArray(saved.candidateRestaurants))throw Error('invalid saved state');
        saved.location=cleanLocation(saved.location);
        memory={...defaults(),...saved};
      }
    }catch{/* 손상되거나 사용할 수 없는 저장소는 현재 페이지의 메모리 상태를 사용합니다. */}
    return copy(memory);
  }
  function commit(next){
    const previous=read();
    if(JSON.stringify({...previous,revision:0})===JSON.stringify({...next,revision:0}))return previous;
    next.revision=previous.revision+1;memory=copy(next);
    try{sessionStorage.setItem(KEY,JSON.stringify(memory));}catch{/* 탭 저장소가 막혀도 현재 화면은 동작합니다. */}
    listeners.forEach(fn=>fn(copy(memory)));return copy(memory);
  }
  function clear(next){next.menu=null;next.restaurants=[];next.candidateRestaurants=[];next.selectedRestaurantId=null;next.route=null;next.searchedAt=null;}
  function setContext(patch){
    const next=read();const location=Object.hasOwn(patch,'location')?cleanLocation(patch.location):next.location;
    const conditions={...next.conditions,...patch.conditions};
    if(!validConditions(conditions))throw Error('조건 범위를 확인해주세요.');
    if(JSON.stringify([location,conditions])!==JSON.stringify([next.location,next.conditions])){
      next.location=location;next.conditions=conditions;next.contextRevision++;clear(next);
    }
    return commit(next);
  }
  function setMenu(menu){
    if(!validMenu(menu))throw Error('메뉴 정보를 확인해주세요.');
    const next=read();clear(next);next.menu=menu===null?null:copy(menu);return commit(next);
  }
  function setRestaurants(result,expectedContextRevision,menuId){
    const next=read();
    if(next.contextRevision!==expectedContextRevision||(next.menu?.id??null)!==menuId)return false;
    if(!Array.isArray(result.restaurants)||!Array.isArray(result.candidate_restaurants||[]))throw Error('식당 응답을 확인해주세요.');
    next.restaurants=copy(result.restaurants);next.candidateRestaurants=copy(result.candidate_restaurants||[]);
    next.selectedRestaurantId=null;next.route=null;next.searchedAt=Date.now();commit(next);return true;
  }
  function summary(){const s=read(),c=s.conditions;return [c.budget.toLocaleString('ko-KR')+'원',Math.max(0,Math.ceil((c.deadline-Date.now())/60000))+'분 남음',c.radius_m+'m',c.people+'명',c.cuisine,s.location?.address||s.location?.name||'위치 미설정'].join(' / ');}
  return {summary,read,setContext,setMenu,setRestaurants,
    hasSaved(){try{return sessionStorage.getItem(KEY)!==null;}catch{return false;}},
    remainingMinutes(deadline=read().conditions.deadline){return Math.max(0,Math.ceil((deadline-Date.now())/60000));},
    setSelection(id){const next=read();if(id!==null&&!next.restaurants.some(r=>r.id===id))return false;if(next.selectedRestaurantId!==id){next.selectedRestaurantId=id;next.route=null;commit(next);}return true;},
    setRoute(route,contextRevision,restaurantId){const next=read();if(next.contextRevision!==contextRevision||next.selectedRestaurantId!==restaurantId)return false;next.route=copy(route);commit(next);return true;},
    setGame(game){const next=read();next.game=copy(game);return commit(next);},
    setChat(chat){const next=read();next.chat=copy(chat);return commit(next);},
    subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},
  };
})();
