const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..','frontend');
function harness(){
 const source=fs.readFileSync(path.join(root,'app.js'),'utf8');
 const context=vm.createContext({remainingLunch:()=>30,clearTimeout});
 vm.runInContext(source.slice(source.indexOf('const $='),source.indexOf('async function run')),context);
 return {run:code=>vm.runInContext(code,context)};
}
test('request preserves food type for groups and sends only backend fields',()=>{
 const h=harness();
 h.run("state.origin={latitude:37.5,longitude:127};state.people=4;state.category='일식/회';state.menuId='menu-1'");
 const body=JSON.parse(h.run('JSON.stringify(payload())'));
 assert.deepEqual(body,{conditions:{budget:5000,minutes:30,cuisine:'일식/회'},location:{lat:37.5,lng:127,name:'현재 위치',source:'geolocation'},radius_m:500,menu_id:'menu-1'});
 assert.equal(h.run('foodTypes.length'),15);
});
test('missing location and expired or excessive time are rejected',()=>{
 const h=harness();assert.throws(()=>h.run('payload()'),/위치/);
 h.run('state.origin={latitude:37.5,longitude:127}');
 for(const minutes of [0,121]){h.run(`remainingLunch=()=>${minutes}`);assert.throws(()=>h.run('payload()'),/1~120/);}
 for(const minutes of [1,120]){h.run(`remainingLunch=()=>${minutes}`);assert.equal(h.run('payload().conditions.minutes'),minutes);}
});
test('condition changes invalidate the selected menu and restaurant results',()=>{
 const h=harness();h.run("state.menu='비빔밥';state.menuId='m1';state.restaurants=[{id:'r1'}];invalidate()");
 assert.equal(h.run('state.menuId'),null);assert.equal(h.run('state.restaurants.length'),0);
});
test('same-origin config enables real requests and preserves server error messages',async()=>{
 const source=fs.readFileSync(path.join(root,'api.js'),'utf8').replaceAll('export ','');
 const calls=[];let reply={ok:true,json:async()=>({apiBase:''})};
 const context=vm.createContext({location:{protocol:'http:'},AbortController,setTimeout,clearTimeout,fetch:async(...args)=>{calls.push(args);return reply;}});
 vm.runInContext(source,context);
 assert.equal(await vm.runInContext('configure()',context),false);
 reply={ok:false,status:422,json:async()=>({detail:'조건 오류'})};
 await assert.rejects(vm.runInContext("request('/api/recommendations',{})",context),/조건 오류/);
 assert.equal(calls[1][0],'/api/recommendations');
});
