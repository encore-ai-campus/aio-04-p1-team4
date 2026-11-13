const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(fetch){
 const storage=new Map(),window={addEventListener(){},removeEventListener(){}};
 const context=vm.createContext({window,sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},fetch,AbortController,AbortSignal,TextDecoder,Uint8Array,setTimeout,clearTimeout,Date});
 for(const name of ['state.js','chat.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend',name),'utf8'),context);
 const nodes=new Map(),root={id:'home-chat',html:'',get innerHTML(){return this.html;},set innerHTML(v){this.html=v;nodes.clear();},
 querySelector(selector){if(selector.startsWith('[data-chat-')&&!this.html.includes(selector.slice(1,-1)))return null;
 if(!nodes.has(selector))nodes.set(selector,{addEventListener(k,v){this[k]=v;},scrollHeight:0});return nodes.get(selector);}};
 const store=window.LunchRunState;
 store.setContext({location:{lat:37.5,lng:127,name:'현재 위치',source:'place'},conditions:{budget:9000,cuisine:'중식'}});
 return {root,store,mount:()=>window.LunchRunChat.mount(root),close:()=>window.LunchRunChat.close(),
 send(text){root.querySelector('textarea').onkeydown({key:'Enter',shiftKey:false,isComposing:false,keyCode:13,preventDefault(){},currentTarget:{value:text}});}};
}
function stream(data){return new Response(JSON.stringify({event:'completed',data})+'\n',{headers:{'Content-Type':'application/x-ndjson'}});}
module.exports={harness,tick,stream};
