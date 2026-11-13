// 삭제된 상태 위젯 대신 현재 채팅의 서버 오류·재시도 동작을 검증한다.
const test=require('node:test'),assert=require('node:assert/strict');
const {harness,tick}=require('./chat-harness.cjs');
test('Groq 서버 오류를 표시하고 가짜 메뉴를 생성하지 않는다',async()=>{
 const h=harness(async u=>u.includes('/session')?new Response('{"turns":[]}'):new Response('{"detail":"잠시 후 재시도"}',{status:503}));
 h.mount();await tick();h.send('추천');await tick();await tick();assert.match(h.root.innerHTML,/잠시 후 재시도/);
 assert.equal(h.store.read().menu,null);assert.ok(h.root.querySelector('[data-chat-retry]'));h.close();
});
