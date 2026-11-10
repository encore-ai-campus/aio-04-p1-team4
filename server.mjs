import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {phoneUrl} from './network.mjs';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {RoomStore,RoomError} from './room-store.mjs';
import {filterMenus,LOCATIONS} from './dist/engine.mjs';
const base=path.dirname(fileURLToPath(import.meta.url)),root=path.join(base,'dist'),port=Number(process.env.PORT||4174);
const bundledPython='C:/Users/Playdata/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const python=process.env.PYTHON_BIN||(fs.existsSync(bundledPython)?bundledPython:'python');
const store=new RoomStore(path.join(base,'data','rooms.json')),qrCache=new Map(),limits=new Map();
const send=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
function poolFor(filters){const all=filterMenus(filters),picked=[];for(const term of ['김치찌개','된장찌개','제육','돈까스','돈카츠','비빔밥','순두부','쌀국수','짜장','김밥','볶음밥','냉면','우동','라면','파스타','초밥']){const m=all.filter(m=>m.name.includes(term)&&!picked.some(p=>p.id===m.id)).sort((a,b)=>a.name.length-b.name.length)[0];if(m)picked.push(m);}for(const m of all){if(picked.length>=20)break;if(!picked.some(p=>p.id===m.id))picked.push(m);}return picked.map(({id,name,category,emoji,price})=>({id,name,category,emoji,price}));}
function filtersFor(v={}){const n=(key,def,min,max)=>{const x=Number(v[key]??def);if(!Number.isFinite(x)||x<min||x>max)throw new RoomError(400,'추천 조건의 범위를 확인해 주세요.');return x;};if(v.location&&!LOCATIONS[v.location])throw new RoomError(400,'지원하는 출발 위치를 선택해주세요.');return {location:v.location||'독산역',budget:n('budget',12000,0,1000000),time:n('time',45,10,90),distance:n('distance',500,100,1000),categories:Array.isArray(v.categories)?v.categories.filter(x=>['한식','중식','일식','양식','분식','아시안'].includes(x)):[]};}
async function body(req){let raw='';for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>16384)throw new RoomError(413,'입력 내용이 너무 길어요.');}try{return JSON.parse(raw||'{}');}catch{throw new RoomError(400,'요청 형식을 확인해 주세요.');}}
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};
http.createServer(async(req,res)=>{try{
 const u=new URL(req.url,'http://localhost'),parts=u.pathname.split('/').filter(Boolean),key=(req.headers.authorization||'').replace(/^Bearer /,'');
 res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','same-origin');
 if(req.method==='GET'&&u.pathname==='/api/network')return send(res,200,{publicUrl:phoneUrl(port),localUrl:`http://127.0.0.1:${port}`,phoneNote:'같은 공유기의 Wi-Fi에서 QR로 참여하세요. 모바일 데이터·외부 인터넷에서는 이 주소로 접속할 수 없어요.'});
 if(req.method==='POST'){
  if(req.headers.origin&&new URL(req.headers.origin).host!==req.headers.host)throw new RoomError(403,'다른 출처에서 요청할 수 없어요.');
  const addr=req.socket.remoteAddress||'',now=Date.now(),lim=limits.get(addr);if(lim&&now-lim.t<60000){if(++lim.n>180)throw new RoomError(429,'잠시 후 다시 시도해주세요.');}else limits.set(addr,{t:now,n:1});
  const data=await body(req);
  if(u.pathname==='/api/rooms'){const filters=filtersFor(data.filters);return send(res,201,store.create({nickname:data.nickname,title:data.title,filters,menus:poolFor(filters)}));}
  if(parts[0]==='api'&&parts[1]==='rooms'&&parts.length===4){const code=parts[2],action=parts[3];return send(res,200,action==='join'?store.join(code,data.nickname):store.action(code,key,action,data));}
 }
 if(req.method==='GET'&&parts[0]==='api'&&parts[1]==='rooms'&&parts.length===3)return send(res,200,store.view(parts[2],key));
 if(req.method==='GET'&&parts[0]==='api'&&parts[1]==='rooms'&&parts[3]==='qr.svg'){
  const room=store.room(parts[2]),url=`${phoneUrl(port)}/?room=${room.code}`;
  if(qrCache.get(room.code)?.url!==url){const result=spawnSync(python,[path.join(base,'qr.py')],{input:url,encoding:'utf8',windowsHide:true,timeout:10000});if(result.status!==0)throw new RoomError(503,'QR 생성이 불가능해요. 초대 링크나 방 코드를 사용해주세요.');qrCache.set(room.code,{url,svg:result.stdout});}
  res.writeHead(200,{'Content-Type':'image/svg+xml','Cache-Control':'no-store'});return res.end(qrCache.get(room.code).svg);
 }
 if(u.pathname.startsWith('/api/'))throw new RoomError(404,'API를 찾지 못했어요.');
 if(req.method!=='GET')throw new RoomError(405,'지원하지 않는 방식이에요.');
 const target=path.resolve(root,'.'+decodeURIComponent(u.pathname==='/'?'/index.html':u.pathname));if(!target.startsWith(root+path.sep))throw new RoomError(403,'접근할 수 없어요.');
 const data=fs.readFileSync(target);res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream','Cache-Control':'no-cache'});res.end(data);
 }catch(e){send(res,e.status|| (e.code==='ENOENT'?404:500),{error:e.status?e.message:'요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.'});}
}).listen(port,process.env.HOST||'0.0.0.0',()=>console.log(`LunchRun DEMO 3\nPC: http://127.0.0.1:${port}\nPHONE (same Wi-Fi): ${phoneUrl(port)}`));
