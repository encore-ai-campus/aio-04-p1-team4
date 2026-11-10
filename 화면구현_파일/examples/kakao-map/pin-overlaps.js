(function(root){
  // Partition visible pin rectangles: each restaurant belongs to one badge/list.
  function groups(points){
    const pending=[...points].sort((a,b)=>String(a.id).localeCompare(String(b.id),'en'));
    const assigned=new Set(),result=[];
    for(const anchor of pending){
      if(assigned.has(anchor.id))continue;
      const members=pending.filter(p=>!assigned.has(p.id)&&Math.abs(p.x-anchor.x)<36&&Math.abs(p.y-anchor.y)<48);
      members.forEach(p=>assigned.add(p.id));result.push({anchor,members});
    }
    return result;
  }
  root.LunchRunPinOverlaps={groups};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.LunchRunPinOverlaps;
})(typeof window==='undefined'?globalThis:window);
