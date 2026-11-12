// 새로고침 시 서버의 최근 대화와 조건을 화면 상태로 복원하는지 검증합니다.
const test=require('node:test');const assert=require('node:assert/strict');
const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/app.js'),'utf8')
  .replace(/\nrestoreChatSession\(\);\s*\nrender\(\);\s*$/,'');

function setup(saved){
  const fetch=async()=>({ok:true,json:async()=>saved});
  const context=vm.createContext({
    clearInterval,clearTimeout,AbortSignal,fetch,
    document:{querySelector:()=>({addEventListener(){}}),querySelectorAll:()=>[],addEventListener(){}},
    window:{addEventListener(){}},localStorage:{getItem:()=>null},location:{hash:'#recommend'},
    LunchRunLocation:{validCoordinates:()=>true}
  });
  vm.runInContext(source,context);
  vm.runInContext('render=()=>{};',context);
  return code=>vm.runInContext(code,context);
}

test('세션의 최근 대화·조건·선정 메뉴를 화면 상태로 복원함',async()=>{
  const run=setup({
    exists:true,
    turns:[{user_message:'식당 추천해줘',assistant_message:'추천 결과입니다.'}],
    conditions:{minutes:30,budget:9000,cuisine:'중식',diet:'any',spicy:true},
    location:{lat:37.48,lng:126.88,name:'예시 위치',address:'',source:'place',accuracy:null},
    radius_m:300,
    selected_menu:{id:'noodle',name:'짜장면',emoji:'🍽️'}
  });
  await run('restoreChatSession()');
  assert.equal(run('state.messages.length'),2);
  assert.equal(run('state.messages[0].text'),'식당 추천해줘');
  assert.equal(run('state.conditions.budget'),9000);
  assert.equal(run('state.radiusM'),300);
  assert.equal(run('state.location.name'),'예시 위치');
  assert.equal(run('state.result.menu.id'),'noodle');
});

test('복원 중 사용자가 상태를 바꾸면 오래된 응답을 적용하지 않음',async()=>{
  let resolve;
  const run=setup(null);
  run('fetch=()=>new Promise(r=>{globalThis.finishFetch=r;})');
  const request=run('restoreChatSession()');
  run('state.version=1;globalThis.finishFetch({ok:true,json:async()=>({exists:true,turns:[],conditions:{budget:1000}})})');
  await request;
  assert.equal(run('state.conditions.budget'),12000);
});
