(function(root){
  const modes={walk:'도보',car:'자동차',traffic:'대중교통'};
  function validPoint(p){return !!p&&Number.isFinite(p.lat)&&Number.isFinite(p.lng)&&Math.abs(p.lat)<=90&&Math.abs(p.lng)<=180;}
  function routeUrl(origin,destination,mode='walk'){
    if(!Object.hasOwn(modes,mode)||!validPoint(origin)||!validPoint(destination))return null;
    const point=(p,fallback)=>`${encodeURIComponent(p.name||fallback)},${p.lat},${p.lng}`;
    return `https://map.kakao.com/link/by/${mode}/${point(origin,'출발지')}/${point(destination,'목적지')}`;
  }
  function formatDuration(seconds){
    if(!Number.isFinite(seconds)||seconds<0)return '';
    const minutes=Math.ceil(seconds/60);
    if(!minutes)return '0분';
    return minutes<60?`${minutes}분`:`${Math.floor(minutes/60)}시간${minutes%60?' '+minutes%60+'분':''}`;
  }
  function formatDistance(meters){return meters<1000?`${Math.round(meters)}m`:`${(meters/1000).toFixed(1)}km`;}
  function walkingConnections(paths,origin,destination){
    const nonempty=paths.filter(path=>path.length);
    if(!nonempty.length)return [];
    const connections=[];
    const connect=(a,b)=>{if(Math.abs(a[0]-b[0])>1e-7||Math.abs(a[1]-b[1])>1e-7)connections.push([a,b]);};
    connect([origin.lng,origin.lat],nonempty[0][0]);
    for(let i=1;i<nonempty.length;i++)connect(nonempty[i-1].at(-1),nonempty[i][0]);
    connect(nonempty.at(-1).at(-1),[destination.lng,destination.lat]);
    return connections;
  }
  const api={routeUrl,validPoint,modes,formatDuration,formatDistance,walkingConnections};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.LunchRunRoutes=api;
})(typeof window!=='undefined'?window:null);
