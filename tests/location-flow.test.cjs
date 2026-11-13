const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const example={name:'출발',address:'주소',lat:37.5,lng:127,source:'place'};
function setup(service){
 const nodes=new Map();function node(){return {value:'',children:[],dataset:{},append(...v){this.children.push(...v);},replaceChildren(){this.children=[];},setAttribute(){},addEventListener(k,v){this[k]=v;},showModal(){this.open=true;},close(){this.open=false;this['close-event']?.();}};}
 const dialog=node();dialog.querySelector=s=>{if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);};dialog.querySelectorAll=()=>[];
 dialog.addEventListener=(k,v)=>{if(k==='close')dialog['close-event']=v;};
 const window={LunchRunLocation:{validCoordinates:(a,b)=>Number.isFinite(a)&&Number.isFinite(b),...service}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../frontend/location-picker.js'),'utf8'),{window,document:{createElement:t=>t==='dialog'?dialog:node(),body:{append(){}}},AbortController,setTimeout,clearTimeout});
 let selected=null;window.LunchRunLocationPicker.open(v=>selected=v);
 return {dialog,q:s=>dialog.querySelector('[data-location-'+s+']'),selected:()=>selected,close:()=>window.LunchRunLocationPicker.close()};
}
test('늦은 검색 결과가 새 검색을 덮지 않는다',async()=>{
 const pending=[];const h=setup({search:()=>new Promise(r=>pending.push(r))});
 h.q('query').value='처음';const first=h.q('form').onsubmit({preventDefault(){}});
 h.q('query').value='나중';const second=h.q('form').onsubmit({preventDefault(){}});
 pending[1]({items:[{...example,name:'새 결과'}]});await second;pending[0]({items:[example]});await first;
 assert.equal(h.q('results').children[0].children[0].textContent,'새 결과');h.close();
});
test('위치 선택창을 닫은 뒤 도착한 좌표를 무시한다',async()=>{
 let finish;const h=setup({current:()=>new Promise(r=>finish=r),reverse:async()=>({})});
 const promise=h.q('current').onclick();h.close();finish(example);await promise;assert.equal(h.selected(),null);
});
test('주소 변환이 실패해도 확보한 Geolocation 좌표를 선택한다',async()=>{
 const h=setup({current:async()=>({...example,source:'geolocation'}),reverse:async()=>{throw Error('offline');}});
 await h.q('current').onclick();assert.equal(h.selected().lat,37.5);assert.equal(h.selected().source,'geolocation');h.close();
});
