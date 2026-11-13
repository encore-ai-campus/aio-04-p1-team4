// 홈과 게임에서 같은 위치 조회·선택 흐름을 사용합니다. 위치를 영구 저장하지 않습니다.
window.LunchRunLocationPicker = (() => {
  let dialog, callback, controller, timer, version=0, kind='place', items=[];
  const service=()=>window.LunchRunLocation;
  const query=s=>dialog.querySelector(s);
  function status(message){query('[data-location-status]').textContent=message;}
  function busy(value){
    query('[data-location-current]').disabled=value;
    query('[data-location-submit]').disabled=value;
    dialog.setAttribute('aria-busy',String(value));
  }
  function cancel(){version++;controller?.abort();clearTimeout(timer);controller=null;}
  function clearResults(){items=[];query('[data-location-results]').replaceChildren();}
  function active(token){return token===version&&dialog.open;}
  function begin(){cancel();clearResults();controller=new AbortController();busy(true);return version;}
  function choose(item){
    if(!item||!service().validCoordinates(item.lat,item.lng)||!['geolocation','address','place'].includes(item.source)){
      status('올바른 위치가 아닙니다. 다시 검색해주세요.');return;
    }
    const selected={name:item.name||'선택 위치',address:item.address||'',lat:item.lat,lng:item.lng,source:item.source};
    if(item.accuracy!=null)selected.accuracy=item.accuracy;
    cancel();dialog.close();callback(selected);
  }
  async function current(){
    const token=begin();status('브라우저 위치 권한을 확인해주세요.');
    timer=setTimeout(()=>{
      if(active(token)){cancel();busy(false);status('위치 확인 시간이 초과되었습니다. 다시 시도하거나 검색으로 선택해주세요.');}
    },30000);
    try{
      const item=await service().current();if(!active(token))return;
      status('좌표를 확인했습니다. 주소를 확인하고 있어요.');
      try{const result=await service().reverse(item,controller.signal);if(result.address)item.address=result.address;}catch{/* 주소 실패 시 확보한 좌표를 사용합니다. */}
      if(active(token))choose(item);
    }catch(error){if(active(token))status(error.message);}
    finally{if(active(token)){clearTimeout(timer);busy(false);}}
  }
  async function search(event){
    event.preventDefault();const text=query('[data-location-query]').value.trim();
    if(!text){status('주소 또는 장소를 입력해주세요.');return;}
    const token=begin();status('검색하고 있어요.');
    try{
      const result=await service().search(text,kind,controller.signal);if(!active(token))return;
      items=Array.isArray(result.items)?result.items:[];
      items.forEach(item=>{
        const button=document.createElement('button');button.type='button';button.className='lr-location-result';
        const name=document.createElement('strong'),address=document.createElement('span');
        name.textContent=item.name;address.textContent=item.address;
        button.append(name,address);button.onclick=()=>choose(item);query('[data-location-results]').append(button);
      });
      status(items.length?`검색 결과 ${items.length}개입니다. 출발지를 선택해주세요.`:'검색 결과가 없습니다. 검색어 또는 검색 종류를 바꿔주세요.');
    }catch(error){if(active(token))status(error.name==='TimeoutError'?'검색 시간이 초과되었습니다. 다시 시도해주세요.':error.message);}
    finally{if(active(token))busy(false);}
  }
  function init(){
    if(dialog)return;
    dialog=document.createElement('dialog');dialog.className='lr-location-dialog';dialog.setAttribute('aria-labelledby','lr-location-title');
    dialog.innerHTML=`<div class="lr-location-header"><div><small>WHERE TO START</small><h2 id="lr-location-title">점심의 출발점</h2></div><button type="button" data-location-close aria-label="위치 설정 닫기">×</button></div>
      <p>현재 위치를 가져오거나 주소·장소를 검색해 출발점을 선택하세요.</p>
      <p class="lr-location-note">현재 위치는 버튼을 눌렀을 때만 조회합니다. 주소 확인을 위해 좌표를 카카오에 전달합니다.</p>
      <button type="button" data-location-current>⌖ 현재 위치 가져오기</button>
      <div class="lr-location-tabs" role="group" aria-label="위치 검색 종류"><button type="button" data-location-kind="place" aria-pressed="true">장소명 검색</button><button type="button" data-location-kind="address" aria-pressed="false">주소 검색</button></div>
      <form data-location-form><label for="lr-location-query">주소 또는 장소</label><div class="lr-location-search"><input id="lr-location-query" data-location-query maxlength="100" autocomplete="off" placeholder="예: 가산디지털단지역" required><button type="submit" data-location-submit>검색</button></div></form>
      <p data-location-status role="status" aria-live="polite"></p><div data-location-results></div>`;
    document.body.append(dialog);
    query('[data-location-close]').onclick=()=>dialog.close();
    dialog.addEventListener('close',cancel);
    query('[data-location-current]').onclick=current;
    query('[data-location-form]').onsubmit=search;
    query('[data-location-query]').oninput=()=>{cancel();clearResults();busy(false);status('검색 버튼을 눌러주세요.');};
    dialog.querySelectorAll('[data-location-kind]').forEach(button=>button.onclick=()=>{
      cancel();kind=button.dataset.locationKind;clearResults();busy(false);
      dialog.querySelectorAll('[data-location-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
      query('[data-location-query]').placeholder=kind==='place'?'예: 가산디지털단지역':'예: 서울 금천구 가산디지털1로 25';status('검색 종류를 변경했습니다. 검색해주세요.');
    });
  }
  return {open(onSelect,selected){
    init();cancel();callback=onSelect;clearResults();busy(false);
    query('[data-location-query]').value='';
    status(selected?`현재 출발점: ${selected.name} · ${selected.address||''}`:'현재 위치 가져오기 또는 검색으로 출발점을 선택해주세요.');
    if(!dialog.open)dialog.showModal();
  },close(){if(dialog?.open)dialog.close();}};
})();
