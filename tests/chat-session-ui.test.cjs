const test=require('node:test'),assert=require('node:assert/strict');
const {harness,tick}=require('./chat-harness.cjs');
test('서버 대화를 복원해도 현재 조건은 유지한다',async()=>{
 const h=harness(async()=>new Response(JSON.stringify({exists:true,conditions:{budget:1000},turns:[{user_message:'질문',assistant_message:'DB 답변'}]})));
 h.mount();await tick();await tick();assert.equal(h.store.read().conditions.budget,9000);
 assert.match(h.root.innerHTML,/DB 답변/);assert.equal(h.store.read().chat.messages.length,2);h.close();
});
test('복원 중 조건 변경은 오래된 서버 조건에 덮이지 않는다',async()=>{
 let finish;const h=harness(()=>new Promise(r=>finish=r));h.mount();h.store.setContext({conditions:{budget:12000}});
 finish(new Response(JSON.stringify({exists:true,conditions:{budget:1000},turns:[]})));await tick();await tick();
 assert.equal(h.store.read().conditions.budget,12000);h.close();
});
