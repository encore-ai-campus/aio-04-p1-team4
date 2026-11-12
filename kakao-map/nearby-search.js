(function(root){
  const EARTH=6371008.8;
  function distanceMeters(a,b){
    const rad=Math.PI/180,dlat=(b.lat-a.lat)*rad,dlng=(b.lng-a.lng)*rad;
    const h=Math.sin(dlat/2)**2+Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin(dlng/2)**2;
    return 2*EARTH*Math.asin(Math.sqrt(Math.min(1,h)));
  }
  function boundsFor(center,radius){
    const angle=(radius+1)/EARTH,dy=angle*180/Math.PI;
    const dx=Math.asin(Math.min(1,Math.sin(angle)/Math.cos(center.lat*Math.PI/180)))*180/Math.PI;
    return {west:center.lng-dx,east:center.lng+dx,south:center.lat-dy,north:center.lat+dy};
  }
  function split(b){
    const x=(b.west+b.east)/2,y=(b.south+b.north)/2;
    return [{west:b.west,east:x,south:b.south,north:y},{west:x,east:b.east,south:b.south,north:y},
      {west:b.west,east:x,south:y,north:b.north},{west:x,east:b.east,south:y,north:b.north}];
  }
  function intersects(b,center,radius){
    return distanceMeters(center,{lat:Math.max(b.south,Math.min(b.north,center.lat)),lng:Math.max(b.west,Math.min(b.east,center.lng))})<=radius+1;
  }
  const normalized=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/서울특별시|서울시|서울/g,'').replace(/[\s()㈜]/g,'');
  const fingerprint=p=>normalized(p.name)+'|'+normalized(p.address);
  const nameKey=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/주식회사|\(주\)|㈜/g,'').replace(/[^가-힣a-z0-9]/g,'');
  function similarName(a,b){
    const x=nameKey(a),y=nameKey(b);
    if(!x||!y)return false;
    if(x===y)return true;
    const core=s=>s.replace(/(?:(?:서울)?(?:금천|가산디지털단지|가산디지털|가산|독산역|독산|시흥)(?:본|직영)?점|본점|직영점)$/,'');
    const u=core(x),v=core(y);
    return u.length>=3&&u===v;
  }
  function locationKey(p){
    const address=normalized(p.address).replace(/[,]/g,'');
    return address&&Number.isFinite(p.lat)&&Number.isFinite(p.lng)?`${p.lat}|${p.lng}|${address}`:null;
  }
  async function collectNearby({center,radius,knownPlaces=[],excludedIds=[],excludedPlaces=[],requestPage,isCurrent=()=>true,onProgress=()=>{},maxDepth=6,minInterval=140}){
    const matches=new Map(),keys=new Map(),naverKeys=new Map(),locations=new Map();
    const excluded=new Set(excludedIds.map(String));
    const roadKey=s=>String(s||'').match(/([가-힣A-Za-z0-9·]+(?:대로|로|길))\s*(\d+(?:-\d+)?)/)?.slice(1).join(' ')||'';
    const excludedAddresses=new Set(excludedPlaces.flatMap(p=>roadKey(p.address)?[p.name,...(p.aliases||[])].map(name=>nameKey(name)+'|'+roadKey(p.address)):[]));
    let errors=0,saturatedCells=0,requests=0,nextRequestAt=0;
    function merge(place){
      if(excluded.has(String(place?.id)))return;
      if(excludedAddresses.has(nameKey(place?.name)+'|'+roadKey(place?.address)))return;
      if(!place?.id||!Number.isFinite(place.lat)||!Number.isFinite(place.lng)||Math.abs(place.lat)>90||Math.abs(place.lng)>180)return;
      const distance=distanceMeters(center,place);if(distance>radius)return;
      const location=locationKey(place);
      if(location){
        for(const id of locations.get(location)||[]){
          const existing=matches.get(id);
          if(!existing||id===String(place.id)||!similarName(existing.name,place.name))continue;
          // Keep a menu-bearing record; otherwise prefer a real Kakao identity.
          const priority=p=>(p.menuCount>0?100:0)+(String(p.id).startsWith('license:')?0:10)+(p.naverId?1:0);
          if(priority(existing)>=priority(place))return;
          matches.delete(id);
          if(existing.naverId)naverKeys.delete(String(existing.naverId));
        }
      }
      if(place.naverId&&naverKeys.has(String(place.naverId)))return;
      const key=fingerprint(place),existing=keys.get(key);
      // Only replace an unmatched licensing row on an exact name/address match.
      if(existing&&String(existing).startsWith('license:')){
        if(String(place.id).startsWith('license:'))return;
        matches.delete(existing);
      }
      matches.set(String(place.id),{...matches.get(String(place.id)),...place,id:String(place.id),distance:Math.round(distance)});
      if(location){if(!locations.has(location))locations.set(location,new Set());locations.get(location).add(String(place.id));}
      if(place.naverId)naverKeys.set(String(place.naverId),String(place.id));
      keys.set(key,String(place.id));
    }
    knownPlaces.forEach(merge);
    const jobs=split(boundsFor(center,radius)).map(bounds=>({bounds,depth:1}));
    async function page(bounds,number){
      if(!isCurrent())return null;
      const now=Date.now(),wait=Math.max(0,nextRequestAt-now);nextRequestAt=Math.max(now,nextRequestAt)+minInterval;
      if(wait)await new Promise(resolve=>setTimeout(resolve,wait));
      if(!isCurrent())return null;
      try{requests++;return await requestPage(bounds,number);}catch(_){errors++;return null;}
    }
    async function worker(){
      while(jobs.length&&isCurrent()){
        const {bounds,depth}=jobs.shift();if(!intersects(bounds,center,radius))continue;
        const first=await page(bounds,1);if(!isCurrent())return;
        if(!first)continue;
        (first.items||[]).forEach(merge);
        if(first.totalCount>=45&&depth<maxDepth){
          jobs.push(...split(bounds).map(b=>({bounds:b,depth:depth+1})));
        }else{
          if(first.totalCount>=45)saturatedCells++;
          const pages=Math.min(3,Math.ceil((first.totalCount||first.items?.length||0)/15));
          for(let number=2;number<=pages&&isCurrent();number++){
            const result=await page(bounds,number);if(!isCurrent())return;
            if(result)(result.items||[]).forEach(merge);
          }
        }
        onProgress({count:matches.size,requests});
      }
    }
    await Promise.all([worker(),worker(),worker()]);
    if(!isCurrent())return null;
    return {restaurants:[...matches.values()].sort((a,b)=>a.distance-b.distance||a.name.localeCompare(b.name,'ko')),errors,saturatedCells,requests};
  }
  const api={collectNearby,distanceMeters,boundsFor};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.LunchRunNearby=api;
})(typeof window!=='undefined'?window:null);
