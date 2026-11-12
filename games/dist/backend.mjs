// Browser and room server share the backend request contract.
export const FOOD_TYPES=['전체','한식','중식','일식/회','양식','분식','패스트푸드','치킨','도시락/구내식당','뷔페식','냉면','고기','카페/빵','술집','기타'];
export function gameRequest(filters,menuId=null){
 const point=filters.origin;
 if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite)||Math.abs(point[0])>90||Math.abs(point[1])>180)throw Error('출발 위치를 확인해주세요.');
 const remaining=Number.isFinite(filters.lunchDeadline)?Math.max(0,Math.ceil((filters.lunchDeadline-Date.now())/60000)):filters.time;
 for(const [key,min,max] of [['budget',1000,100000],['time',1,120],['distance',50,500]]){
  if(!Number.isInteger(key==='time'?remaining:filters[key])||(key==='time'?remaining:filters[key])<min||(key==='time'?remaining:filters[key])>max)throw Error(`${key}: ${min}~${max} 범위로 설정해주세요.`);
 }
 const categories=filters.categories??[];
 if(!Array.isArray(categories)||categories.length>1||categories.some(c=>!FOOD_TYPES.includes(c)))throw Error('음식 종류를 하나 선택해주세요.');
 return {conditions:{budget:filters.budget,minutes:remaining,cuisine:categories[0]??'전체'},location:{...(filters.selectedLocation||{}),lat:point[0],lng:point[1],name:filters.selectedLocation?.name||filters.location||'현재 위치',source:filters.selectedLocation?.source||'geolocation'},radius_m:filters.distance,menu_id:menuId};
}
export function gameMenu(menu){
 if(typeof menu?.id!=='string'||typeof menu?.name!=='string')throw Error('메뉴 응답 형식을 확인해주세요.');
 return {...menu,category:menu.cuisine??menu.category,emoji:menu.emoji||'🍽️',desc:menu.description||'',offers:[],price:menu.price_verified?menu.verified_price:null};
}
export async function backendRequest(path,body,{signal,base='',fetcher=fetch}={}){
 const controller=new AbortController();
 const abort=()=>controller.abort();
 if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(abort,path==='/api/recommendations'?120000:30000);
 try{
  const response=await fetcher(base+path,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body),signal:controller.signal});
  const data=await response.json();
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:response.status===422?'입력 조건을 확인해주세요.':`서버 요청 실패 (${response.status})`);
  return data;
 }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
export function matchEntry(name,pool){
 const normalize=s=>String(s).normalize('NFKC').replace(/\s+/g,'').toLowerCase();
 return pool.find(m=>normalize(m.name)===normalize(name));
}
