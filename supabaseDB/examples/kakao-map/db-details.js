/* 카카오 장소의 상세정보는 서버가 수집하고 SQLite에서 조회한다. */
(() => {
  let controller = null, timer = null;
  const cancel = () => { controller?.abort(); clearInterval(timer); };
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text)n.textContent=text; if(cls)n.className=cls; return n; };
  const date = value => value ? new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}) : '확인일 미상';
  const minute = t => Number(t.slice(0,2))*60+Number(t.slice(3,5));
  function businessState(data) {
    const s=data.detail_status, rows=data.business_hours;
    if(s.hours_status!=='success'||!s.hours_source_url||!s.hours_checked_at||Date.now()-Date.parse(s.hours_checked_at)>7*86400000)
      return ['unknown','영업 여부 확인 필요'];
    const now=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Seoul'}));
    const day=(now.getDay()+6)%7, minutes=now.getHours()*60+now.getMinutes();
    const today=rows.filter(r=>r.day_of_week===day), yesterday=rows.filter(r=>r.day_of_week===(day+6)%7);
    const open=today.some(r=>r.holiday!==true&&r.start_time&&minutes>=minute(r.start_time)&&(r.ends_next_day||minutes<minute(r.end_time)))||
      yesterday.some(r=>r.holiday!==true&&r.start_time&&r.ends_next_day&&minutes<minute(r.end_time));
    if(open)return ['open','영업 중 · 등록시간 기준'];
    if(!today.length)return ['unknown','오늘 영업시간 확인 필요'];
    return ['closed','영업시간 외 · 등록시간 기준'];
  }
  function mount(r, container, {collect=true,onMenus,hoursContainer}={}) {
    cancel(); const active=new AbortController();controller=active;
    const section=el('section',null,'db-place-detail');section.setAttribute('aria-label','DB 메뉴와 영업시간');
    const hours=el('div',null,'business-hours');
    if(hoursContainer)hoursContainer.append(hours);else section.append(hours);
    const content=el('div'), notice=el('p','DB 상세정보를 확인하고 있어요.','db-detail-status');notice.setAttribute('role','status');
    const refresh=el('button','상세정보 확인','db-detail-refresh');refresh.type='button';
    section.append(content,notice,refresh);container.append(section);
    let current=null;
    const alive=()=>!active.signal.aborted&&section.isConnected;
    function render(data) {
      if(!alive())return; current=data;content.replaceChildren();hours.replaceChildren();clearInterval(timer);
      const s=data.detail_status, badge=el('span',null,'business-status');
      const update=()=>{const [kind,label]=businessState(data);badge.className='business-status is-'+kind;badge.textContent=label;};update();
      timer=setInterval(()=>{if(alive())update();else clearInterval(timer);},60000);hours.append(badge);
      if(data.business_hours.length){
        const details=el('details',null,'business-hours-details');details.append(el('summary','영업시간·확인일'));
        const list=el('p',null,'business-hours-raw');
        list.textContent=data.business_hours.map(h=>`${'월화수목금토일'[h.day_of_week]} ${h.holiday===true?'휴무':h.start_time?`${h.start_time.slice(0,5)} ~ ${h.ends_next_day?'다음날 ':''}${h.end_time.slice(0,5)}${h.last_order_time?' · 주문 마감 '+h.last_order_time.slice(0,5):''}`:'시간 확인 필요'}`).join('\n');
        details.append(list,el('small',`확인 ${date(s.hours_checked_at)} · 임시휴무는 매장에 확인해주세요.`));hours.append(details);
      } else hours.append(el('p',s.hours_status==='missing'?'카카오 페이지에 공개된 영업시간이 없어요.':'영업시간을 아직 확인하지 못했어요.','menu-missing'));
      if(data.menus.length){
        const button=el('button',`메뉴·가격 보기 (${data.menus.length}개)`,'menu-open');button.type='button';
        button.addEventListener('click',()=>onMenus({restaurantName:data.name,menus:data.menus.map(m=>({...m,priceText:m.price_status==='variable'?'시가':m.price===null?'가격 확인 필요':m.price.toLocaleString('ko-KR')+'원'})),source:s.menu_source_url?'카카오 상세페이지 · DB 저장':'기존 DB 자료 · 출처 재확인 필요',sourceUrl:s.menu_source_url||data.place_url,retrievedAt:s.menu_checked_at||''}));content.append(button);
      } else content.append(el('p',s.menu_status==='missing'?'카카오 페이지에 공개된 텍스트 메뉴가 없어요.':'메뉴를 아직 확인하지 못했어요.','menu-missing'));
      const checked=el('small',`DB 저장 자료 · 최근 시도 ${date(s.last_attempt_at)}`,'db-detail-checked');content.append(checked);
      const failed=[s.menu_status,s.hours_status].some(v=>['fetch_failed','parse_failed'].includes(v));
      notice.textContent=failed?'최신 정보를 확인하지 못했어요. 이전에 저장한 자료는 보존했어요.':`메뉴 ${data.menus.length}개 · 영업 구간 ${data.business_hours.length}개 · DB 조회`;
      refresh.textContent='상세정보 다시 확인';
    }
    async function load(force=false){
      refresh.disabled=true;
      try {
        if(!current){const cached=await fetch('/api/restaurants/'+encodeURIComponent(r.id),{signal:active.signal});if(cached.ok)render(await cached.json());else if(cached.status!==404)throw Error('DB 조회 실패');}
        if(!alive())return;
        if(collect||force){
          notice.textContent='카카오 상세페이지에서 메뉴·영업시간을 확인하고 있어요…';
          const response=await fetch('/api/restaurants/'+encodeURIComponent(r.id)+'/details'+(force?'?refresh=true':''),{method:'POST',headers:{'Content-Type':'application/json'},signal:active.signal,body:JSON.stringify({name:r.name,lat:r.lat,lng:r.lng,address:r.address||'',category:r.categoryPath||r.category||''})});
          if(!response.ok)throw Error('수집 요청 실패');render(await response.json());
        }else if(!current)notice.textContent='가게 핀이나 목록을 누르면 상세정보를 수집해 DB에 저장해요.';
      }catch(error){if(alive())notice.textContent='상세정보 서버에 연결하지 못했어요. 잠시 후 다시 확인해주세요.';}
      finally{if(alive())refresh.disabled=false;}
    }
    refresh.addEventListener('click',()=>load(true));load();
  }
  window.LunchRunDBDetails={mount,cancel};
})();
