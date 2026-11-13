// 홈과 게임에서 사용하는 동일한 백엔드 챗봇. 답변과 식당 사실은 서버만 생성합니다.
window.LunchRunChat=(()=>{
  const store=window.LunchRunState;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let active=null;
  async function json(response){
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:`요청 실패 (${response.status})`);
    return data;
  }
  function body(snapshot=store.read()){
    const minutes=store.remainingMinutes(snapshot.conditions.deadline);
    if(!snapshot.location)throw Error('먼저 출발 위치를 설정해주세요.');
    if(minutes<1||minutes>120)throw Error('점심 종료 시각을 현재부터 1~120분 이내로 설정해주세요.');
    return {location:snapshot.location,conditions:{minutes,budget:snapshot.conditions.budget,cuisine:snapshot.conditions.cuisine},radius_m:snapshot.conditions.radius_m,menu_id:snapshot.menu?.id??null};
  }
  function validPatch(p){
    return p&&Object.keys(p).length>0&&Object.entries(p).every(([k,v])=>
      k==='minutes'?Number.isInteger(v)&&v>=10&&v<=120:
      k==='budget'?Number.isInteger(v)&&v>=1000&&v<=100000:
      k==='radius_m'?Number.isInteger(v)&&v>=50&&v<=500:
      k==='cuisine'?['전체','한식','중식','일식/회','양식','분식','패스트푸드','치킨','도시락/구내식당','뷔페식','냉면','고기','카페/빵','술집','기타'].includes(v):false);
  }
  function mount(root,{onState=()=>{}}={}){
    if(active?.root===root&&root.querySelector('.lr-chat'))return;
    active?.destroy();
    let messages=store.read().chat?.messages||[],draft=store.read().chat?.draft||'',proposal=null;
    let ready=false,busy=false,status='이전 대화를 확인하고 있어요.',controller=null,disposed=false,turn=0,retry=null;
    const persist=()=>store.setChat({messages:messages.slice(-20),draft});
    const fresh=(revision,id)=>!disposed&&turn===id&&store.read().contextRevision===revision;
    function paint(){
      if(disposed)return;
      const s=store.read();
      root.innerHTML=`<section class="lr-chat" aria-label="점심 AI 챗봇"><p class="lr-chat-context">출발 위치: ${esc(s.location?.name||'위치를 먼저 설정해주세요')}</p><div class="lr-chat-log ai-chat" role="log" aria-label="대화 내역">${messages.length?messages.map(m=>`<div class="lr-chat-message chat-row ${m.role==='user'?'lr-chat-user user':'assistant'}"><div class="chat-bubble"><small>${m.role==='user'?esc(window.LunchRunProfile?.readName?.()||'나'):'✦ AI'}</small><p>${esc(m.text)}</p></div></div>`).join(''):'<p class="lr-chat-empty chat-welcome">✦ AI : 안녕하세요. 원하는 점심 메뉴나 조건을 알려주세요.</p>'}</div>${proposal?`<div class="lr-chat-proposal"><strong>변경 제안</strong><p>${esc(Object.entries(proposal.patch).map(([k,v])=>`${({minutes:'점심시간(분)',budget:'예산(원)',radius_m:'반경(m)',cuisine:'음식 종류'})[k]}: ${v}`).join(' · '))}</p><button type="button" data-chat-apply ${busy?'disabled':''}>조건 적용${proposal.search?' 후 식당 검색':''}</button></div>`:''}<p class="lr-chat-status" role="status" aria-live="polite">${busy?'<span class="lr-chat-spinner" aria-hidden="true"></span>':''}${esc(status)}</p><form class="lr-chat-form"><label class="lr-chat-label ai-input-label" for="ai-message">원하는 점심 조건</label><div class="ai-compose lr-chat-compose"><textarea id="ai-message" name="message" rows="2" maxlength="500" placeholder="예: 메뉴 추천해줘 / 이 메뉴를 파는 식당 찾아줘" ${busy||!ready?'disabled':''}>${esc(draft)}</textarea></div><div class="lr-chat-actions"><button type="submit" class="primary" ${busy||!ready?'disabled':''}>보내기</button>${busy?'<button type="button" data-chat-cancel>취소</button>':''}${retry&&!busy?'<button type="button" data-chat-retry>다시 시도</button>':''}</div></form>${s.menu?`<p class="lr-chat-menu">선택 메뉴: <strong>${esc(s.menu.name)}</strong>${s.menu.serving_unverified?' · 인분 미확인 · 표시 가격 기준':''}</p>`:''}${s.searchedAt?`<a class="lr-chat-map" href="${root.id==='home-chat'?'/games/':'/map/'}">${root.id==='home-chat'?'게임으로 이동해 지도 보기':'검색된 식당 · 카카오 지도 보기'} →</a>`:''}<p class="lr-chat-note">가격·영업시간은 확인된 정보만 안내합니다. 메뉴 추천만으로 식당 검색을 실행하지 않습니다.</p></section>`;
      root.querySelector('form').onsubmit=e=>{e.preventDefault();send(draft);};
      root.querySelector('textarea').oninput=e=>{draft=e.target.value;persist();};
      root.querySelector('textarea').onkeydown=e=>{
        if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){
          e.preventDefault();
          send(e.currentTarget.value);
        }
      };
      root.querySelector('[data-chat-apply]')?.addEventListener('click',apply);
      root.querySelector('[data-chat-retry]')?.addEventListener('click',()=>ready?send(retry):restore());
      root.querySelector('[data-chat-cancel]')?.addEventListener('click',()=>cancel('요청을 취소했어요.'));
      const log=root.querySelector('.lr-chat-log');log.scrollTop=log.scrollHeight;
    }
    function cancel(message='조건이 바뀌어 이전 요청을 취소했어요.'){
      ++turn;controller?.abort();controller=null;busy=false;proposal=null;status=message;persist();paint();
    }
    function accept(result,revision,searched){
      if(!result)return;
      if(Object.hasOwn(result,'menu'))store.setMenu(result.menu);
      if(searched)store.setRestaurants(result,revision,store.read().menu?.id??null);
      onState();
    }
    async function restore(){
      status='이전 대화를 확인하고 있어요.';retry=null;paint();
      controller=new AbortController();const own=controller;
      try{
        const data=await json(await fetch('/api/chat/session',{cache:'no-store',signal:AbortSignal.any([own.signal,AbortSignal.timeout(15000)])}));
        if(disposed||own.signal.aborted)return;
        // 대화는 서버의 최근 10턴을 사용하고, 현재 위치·조건·메뉴는 덮어쓰지 않습니다.
        messages=(data.turns||[]).flatMap(t=>[{role:'user',text:t.user_message},{role:'assistant',text:t.assistant_message}]);
        ready=true;status=data.exists?'이전 대화를 불러왔어요. 현재 화면의 조건으로 이어갑니다.':'원하는 점심을 말해주세요.';persist();
      }catch(e){if(!disposed&&!own.signal.aborted){status=e.message;retry='session';}}
      finally{if(controller===own)controller=null;paint();}
    }
    async function send(message){
      if(busy||!ready||!message?.trim())return;
      const text=message.trim();if(text.length>500){status='500자 이내로 입력해주세요.';paint();return;}
      let payload;try{payload=body();}catch(e){status=e.message;paint();return;}
      const revision=store.read().contextRevision,id=++turn;proposal=null;retry=null;
      controller=new AbortController();const own=controller;let timedOut=false;
      const timer=setTimeout(()=>{timedOut=true;own.abort();},120000);
      busy=true;draft='';messages.push({role:'user',text});status='요청을 시작하고 있어요.';persist();paint();
      let reader;
      try{
        const response=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,message:text}),signal:own.signal});
        if(!response.ok){await json(response);}
        if(!response.body)throw Error('응답 스트림을 열지 못했어요.');
        reader=response.body.getReader();const decoder=new TextDecoder();let buffer='',completed=null,searched=false;
        function event(line){
          if(!line.trim())return;const e=JSON.parse(line);
          if(e.event==='failed')throw Error(e.message||'대화를 처리하지 못했어요.');
          if(e.event==='searching')searched=true;
          if(e.event==='completed')completed=e.data;
          else if(fresh(revision,id)&&typeof e.message==='string'){status=e.message;paint();}
        }
        while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value,{stream:!done});const lines=buffer.split('\n');buffer=lines.pop();lines.forEach(event);if(done)break;}
        event(buffer);
        if(!fresh(revision,id))return;
        if(!completed||typeof completed.text!=='string')throw Error('최종 답변을 받지 못했어요. 다시 시도해주세요.');
        accept(completed.result,revision,searched);
        messages.push({role:'assistant',text:completed.text});
        if(validPatch(completed.suggested_patch))proposal={patch:completed.suggested_patch,revision,id,search:completed.search_after_change===true};
        status='';persist();
      }catch(e){
        if(fresh(revision,id)){status=timedOut?'요청 시간이 초과됐어요. 다시 시도해주세요.':e.message;retry=text;}
      }finally{
        clearTimeout(timer);reader?.cancel().catch(()=>{});
        if(turn===id){busy=false;if(controller===own)controller=null;paint();}
      }
    }
    async function apply(){
      const p=proposal;if(busy||!p)return;
      if(!fresh(p.revision,p.id)||!validPatch(p.patch)){proposal=null;status='현재 조건에 맞춰 다시 요청해주세요.';paint();return;}
      const c={...store.read().conditions};
      for(const [key,value]of Object.entries(p.patch))if(key==='minutes')c.deadline=Date.now()+value*60000;else c[key]=value;
      proposal=null;store.setContext({conditions:c});onState();
      status='조건을 적용했어요. 새 조건으로 다시 추천해 달라고 해주세요.';paint();
      // 검색 동의가 포함된 백엔드 제안만 적용 후 검색합니다. 선택 메뉴는 조건 변경으로 무효화됩니다.
      if(p.search)await send('변경된 조건으로 식당을 찾아줘');
    }
    let lastRevision=store.read().contextRevision;
    const unsubscribe=store.subscribe(s=>{if(s.contextRevision!==lastRevision){lastRevision=s.contextRevision;onState();if(busy)cancel();else{proposal=null;paint();}}});
    function destroy(){if(disposed)return;disposed=true;++turn;controller?.abort();unsubscribe();persist();if(active?.root===root)active=null;}
    active={root,destroy};paint();restore();
  }
  const close=()=>active?.destroy();
  window.addEventListener('pagehide',close);
  return {mount,close};
})();
