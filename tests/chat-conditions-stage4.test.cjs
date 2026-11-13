// 4단계: 실제 공통 상태와 채팅 코드를 사용해 서버 확정 조건·오래된 응답을 검증한다.
const test=require('node:test'),assert=require('node:assert/strict');
const {harness,tick,stream}=require('./chat-harness.cjs');
test('서버 적용값을 버튼 없이 동기화하고 새 메뉴를 유지한다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'적용 완료',applied_patch:{budget:8000,radius_m:100},result:{menu:{id:'noodle',name:'짜장면'},restaurants:[]}}));
 h.mount();await tick();h.send('예산과 반경 변경');await tick();await tick();
 assert.equal(h.store.read().conditions.budget,8000);assert.equal(h.store.read().conditions.radius_m,100);
 assert.equal(h.store.read().menu.id,'noodle');assert.match(h.root.innerHTML,/적용 완료/);
 assert.doesNotMatch(h.root.innerHTML,/data-chat-apply/);h.close();
});
test('조건과 식당 결과를 새 contextRevision으로 함께 저장한다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'검색 완료',applied_patch:{cuisine:'한식'},search_performed:true,result:{menu:{id:'bibimbap',name:'비빔밥'},restaurants:[{id:'new',name:'새식당'}]}}));
 h.mount();await tick();h.send('한식으로 바꾸고 식당도 찾아줘');await tick();await tick();
 assert.equal(h.store.read().conditions.cuisine,'한식');assert.equal(h.store.read().restaurants[0].id,'new');assert.ok(h.store.read().searchedAt);h.close();
});
test('조건을 바꾼 뒤 도착한 이전 적용 응답은 무시한다',async()=>{
 let finish;const h=harness(url=>url.includes('/session')?Promise.resolve(new Response('{"turns":[]}')):new Promise(r=>finish=r));
 h.mount();await tick();h.send('예산 변경');h.store.setContext({conditions:{budget:15000}});
 finish(stream({text:'오래된 적용',applied_patch:{budget:8000},result:{menu:{id:'old',name:'과거 메뉴'}}}));await tick();await tick();
 assert.equal(h.store.read().conditions.budget,15000);assert.equal(h.store.read().menu,null);assert.doesNotMatch(h.root.innerHTML,/오래된 적용/);h.close();
});
test('후보가 없어도 새 조건을 유지하고 예전 메뉴를 지운다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'후보 없음',applied_patch:{budget:1000},result:{menu:null,restaurants:[]}}));
 h.mount();await tick();h.store.setMenu({id:'old',name:'이전 메뉴'});h.send('예산 변경');await tick();await tick();
 assert.equal(h.store.read().conditions.budget,1000);assert.equal(h.store.read().menu,null);h.close();
});
