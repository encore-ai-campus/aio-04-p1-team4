(function(root){
  const clock=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  function koreanTime(now){
    const parts=Object.fromEntries(clock.formatToParts(now).map(p=>[p.type,p.value]));
    return {date:`${parts.year}-${parts.month}-${parts.day}`,minute:Number(parts.hour)*60+Number(parts.minute)};
  }
  function previousDate(date){const d=new Date(date+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-1);return d.toISOString().slice(0,10);}
  const time=minute=>`${String(Math.floor(minute/60)%24).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`;
  function status(record,now=new Date()){
    const unknown={kind:'unknown',label:'영업시간 확인 필요',detail:'확인된 영업시간 정보가 없어요.'};
    if(!record)return unknown;
    if(record.identityReview)return {...unknown,detail:'같은 가게의 영업시간인지 추가 확인이 필요해요.'};
    const current=koreanTime(now);
    if(!record.checkedDate||current.date<record.checkedDate||current.date>record.validUntil)return {...unknown,detail:record.checkedDate?'영업시간을 다시 확인해야 해요.':record.status==='not_checked'?'아직 영업시간을 확인하지 않은 가게예요.':record.status==='page_error'?'영업시간 페이지를 확인하지 못했어요.':'공개된 영업시간을 확인하지 못했어요.'};
    const today=record.dates[current.date];
    if(today?.exception&&today.closed)return {kind:'holiday',label:'휴무',detail:today.text};
    const prior=record.dates[previousDate(current.date)];
    for(const [day,minute] of [[prior,current.minute+1440],[today,current.minute]]){
      if(!day?.known)continue;
      const active=day.periods?.find(([start,end])=>start<=minute&&minute<end);
      if(!active)continue;
      const rest=day.breaks?.find(([start,end])=>start<=minute&&minute<end);
      if(rest)return {kind:'break',label:'브레이크타임',detail:`${time(rest[1])}까지 쉬는 시간`};
      const sessionStart=Math.max(active[0],...(day.breaks||[]).filter(([,end])=>end<=minute).map(([,end])=>end));
      if(day.lastOrders?.some(last=>sessionStart<=last&&last<=minute&&last<=active[1]))return {kind:'last-order',label:'주문 마감',detail:`영업 종료 ${time(active[1])} · 라스트오더 경과`};
      return {kind:'open',label:'영업 중',detail:active[0]===0&&active[1]===1440?'24시간 영업':`${time(active[1])} 영업 종료 예정`};
    }
    const carryover=Math.max(0,...Object.values(record.dates).filter(day=>day.known).flatMap(day=>(day.periods||[]).map(([,end])=>end-1440)));
    if(!prior?.known&&current.minute<carryover)return {...unknown,detail:'전날 시작한 야간 영업시간을 확인해야 해요.'};
    if(!today?.known)return {...unknown,detail:today?.exceptionReview?'휴무·예약 등 예외 조건을 확인해주세요.':'오늘의 영업시간을 확인하지 못했어요.'};
    if(today.closed)return {kind:'holiday',label:'휴무',detail:today.text};
    const next=today.periods?.find(([start])=>start>current.minute);
    return {kind:'closed',label:next?'영업 전':'영업 종료',detail:next?`${time(next[0])} 영업 시작 예정`:'오늘 영업시간이 지났어요.'};
  }
  function recordFor(restaurant){
    const data=root.BUSINESS_HOURS_DATA;
    return data?.byId?.[restaurant.id]||data?.byNaverId?.[restaurant.naverId]||null;
  }
  root.LunchRunBusinessHours={status,recordFor,koreanTime};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.LunchRunBusinessHours;
})(typeof window==='undefined'?globalThis:window);
