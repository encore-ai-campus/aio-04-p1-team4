const test=require('node:test'),assert=require('node:assert/strict');
const {harness,tick,stream}=require('./chat-harness.cjs');
test('DB 메뉴와 인분 미확인 표시를 공통 상태에 전달한다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'DB 결과',result:{menu:{id:'noodle',name:'짜장면',serving_unverified:true},restaurants:[]}}));
 h.mount();await tick();h.send('추천');await tick();await tick();assert.equal(h.store.read().menu.id,'noodle');assert.equal(h.store.read().menu.serving_unverified,true);assert.doesNotMatch(h.root.innerHTML,/lr-chat-menu|lr-chat-map|lr-chat-note/);h.close();
});
test('조건 변경 뒤 도착한 과거 응답을 적용하지 않는다',async()=>{
 let finish;const h=harness(url=>url.includes('/session')?Promise.resolve(new Response('{"turns":[]}')):new Promise(r=>finish=r));
 h.mount();await tick();h.send('추천');h.store.setContext({conditions:{budget:12000}});
 finish(stream({text:'과거 결과',result:{menu:{id:'old',name:'과거 메뉴'}}}));await tick();await tick();
 assert.equal(h.store.read().menu,null);assert.doesNotMatch(h.root.innerHTML,/과거 결과/);h.close();
});
test('매장명과 답변 HTML을 이스케이프한다',async()=>{
 const h=harness(async()=>new Response(JSON.stringify({turns:[{user_message:'<script>x</script>',assistant_message:'<img onerror=alert(1)>'}]})));
 h.mount();await tick();assert.doesNotMatch(h.root.innerHTML,/<script>|<img onerror/);assert.match(h.root.innerHTML,/&lt;script&gt;/);h.close();
});
test('조건 변경안은 적용 버튼을 눌러야 반영한다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'변경 제안',suggested_patch:{budget:12000},result:null}));
 h.mount();await tick();h.store.setMenu({id:'noodle',name:'짜장면'});h.send('예산 변경');await tick();await tick();
 assert.equal(h.store.read().conditions.budget,9000);h.root.querySelector('[data-chat-apply]').click();
 assert.equal(h.store.read().conditions.budget,12000);assert.equal(h.store.read().menu,null);h.close();
});

test('식당 안내 응답 이후에만 경로 버튼을 활성화하고 조건 변경시 비활성화한다',async()=>{
 const h=harness(async url=>url.includes('/session')?new Response('{"turns":[]}'):stream({text:'짜장면을 추천해요. 식당을 안내해 드릴까요?',restaurant_guidance:true,result:{menu:{id:'noodle',name:'짜장면'},restaurants:[]}}));
 h.mount();await tick();assert.match(h.root.innerHTML,/data-chat-route[^>]*disabled/);
 h.send('메뉴 추천');await tick();await tick();assert.doesNotMatch(h.root.innerHTML,/data-chat-route[^>]*disabled/);
 assert.equal(h.store.read().chat.messages.filter(m=>m.at).length,2);
 assert.match(h.root.innerHTML,/게스트/);assert.match(h.root.innerHTML,/<time/);
 h.store.setContext({conditions:{budget:10000}});assert.match(h.root.innerHTML,/data-chat-route[^>]*disabled/);h.close();
});
