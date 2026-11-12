import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {phoneUrl} from './network.mjs';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {RoomStore,RoomError} from './room-store.mjs';
import {gameRequest,gameMenu,backendRequest} from './dist/backend.mjs';
const backendOrigin=process.env.BACKEND_ORIGIN||'http://127.0.0.1:8000';
const base=path.dirname(fileURLToPath(import.meta.url)),root=path.join(base,'dist'),port=Number(process.env.PORT||4174);
const bundledPython='C:/Users/Playdata/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const python=process.env.PYTHON_BIN||(fs.existsSync(bundledPython)?bundledPython:'python');
const store=new RoomStore(process.env.ROOM_STORE_FILE||path.join(base,'data','rooms.json')),qrCache=new Map(),limits=new Map();
const send=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
async function poolFor(filters){try{const data=await backendRequest('/api/menus/candidates',gameRequest(filters),{base:backendOrigin});if(!Array.isArray(data.menus))throw Error('메뉴 후보 응답을 확인해주세요.');return data.menus.slice(0,24).map(gameMenu);}catch(error){throw new RoomError(503,error.message);}}
function filtersFor(v={}){try{const body=gameRequest(v);return {location:body.location.name,selectedLocation:body.location,origin:v.origin,lunchDeadline:Number.isFinite(v.lunchDeadline)?v.lunchDeadline:Date.now()+v.time*60000,budget:v.budget,time:v.time,distance:v.distance,categories:[...(v.categories||[])]};}catch(error){throw new RoomError(400,error.message);}}

async function body(req){let raw='';for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>16384)throw new RoomError(413,'입력 내용이 너무 길어요.');}try{return JSON.parse(raw||'{}');}catch{throw new RoomError(400,'요청 형식을 확인해 주세요.');}}
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};
function forwardedHost(req){const remote=req.socket.remoteAddress;if(remote!=='127.0.0.1'&&remote!=='::1'&&remote!=='::ffff:127.0.0.1')return '';return req.headers['x-forwarded-host']||'';}
function publicUrl(req){const host=forwardedHost(req);if(!host)return phoneUrl(port);const protocol=req.headers['x-forwarded-proto']||'http',prefix=req.headers['x-forwarded-prefix']||'';return `${protocol}://${host}${prefix}`;}
http.createServer(async(req,res)=>{try{
 const u=new URL(req.url,'http://localhost'),parts=u.pathname.split('/').filter(Boolean),key=(req.headers.authorization||'').replace(/^Bearer /,'');
 res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','same-origin');
 if(req.method==='GET'&&u.pathname==='/api/network')return send(res,200,{publicUrl:publicUrl(req),localUrl:`http://127.0.0.1:${port}`,phoneNote:'같은 공유기의 Wi-Fi에서 QR로 참여하세요. 모바일 데이터·외부 인터넷에서는 이 주소로 접속할 수 없어요.'});
 if(req.method==='POST'){
  if(req.headers.origin&&new URL(req.headers.origin).host!==(forwardedHost(req)||req.headers.host))throw new RoomError(403,'다른 출처에서 요청할 수 없어요.');
  const addr=req.socket.remoteAddress||'',now=Date.now(),lim=limits.get(addr);if(lim&&now-lim.t<60000){if(++lim.n>180)throw new RoomError(429,'잠시 후 다시 시도해주세요.');}else limits.set(addr,{t:now,n:1});
  const data=await body(req);
  if(['/api/menus/candidates','/api/recommendations','/api/locations/search','/api/locations/reverse'].includes(u.pathname)){
   try{const result=await backendRequest(u.pathname,data,{base:backendOrigin});return send(res,200,result);}
   catch(error){throw new RoomError(502,error.message);}
  }
  if(u.pathname==='/api/rooms'){const filters=filtersFor(data.filters);return send(res,201,store.create({nickname:data.nickname,title:data.title,filters,menus:await poolFor(filters)}));}
  if(parts[0]==='api'&&parts[1]==='rooms'&&parts.length===4){const code=parts[2],action=parts[3];if(['start','draw'].includes(action)){const room=store.room(code);store.host(room,key);const available=new Set((await poolFor(room.filters)).map(m=>m.id));if(room.menus.some(m=>!available.has(m.id)))throw new RoomError(409,'조건에 맞는 메뉴 후보가 바뀌었습니다. 조건을 확인하고 새 모임방을 만들어주세요.');}return send(res,200,action==='join'?store.join(code,data.nickname):store.action(code,key,action,data));}
 }
 if(req.method==='GET'&&parts[0]==='api'&&parts[1]==='rooms'&&parts.length===3)return send(res,200,store.view(parts[2],key));
 if(req.method==='GET'&&parts[0]==='api'&&parts[1]==='rooms'&&parts[3]==='qr.svg'){
  const room=store.room(parts[2]),url=`${publicUrl(req)}/?room=${room.code}`;
  if(qrCache.get(room.code)?.url!==url){const result=spawnSync(python,[path.join(base,'qr.py')],{input:url,encoding:'utf8',windowsHide:true,timeout:10000});if(result.status!==0)throw new RoomError(503,'QR 생성이 불가능해요. 초대 링크나 방 코드를 사용해주세요.');qrCache.set(room.code,{url,svg:result.stdout});}
  res.writeHead(200,{'Content-Type':'image/svg+xml','Cache-Control':'no-store'});return res.end(qrCache.get(room.code).svg);
 }
 if(req.method==='GET'&&['/static/chat.js','/static/chat.css','/static/state.js','/static/location.js','/static/location-picker.js','/static/location-picker.css'].includes(u.pathname)){
   const upstream=await fetch(backendOrigin+u.pathname,{signal:AbortSignal.timeout(10000)});
   res.writeHead(upstream.status,{'Content-Type':upstream.headers.get('content-type')||'text/plain','Cache-Control':'no-cache'});
   return res.end(Buffer.from(await upstream.arrayBuffer()));
 }
 if(u.pathname.startsWith('/api/'))throw new RoomError(404,'API를 찾지 못했어요.');
 if(req.method!=='GET')throw new RoomError(405,'지원하지 않는 방식이에요.');
 const target=path.resolve(root,'.'+decodeURIComponent(u.pathname==='/'?'/index.html':u.pathname));if(!target.startsWith(root+path.sep))throw new RoomError(403,'접근할 수 없어요.');
 const data=fs.readFileSync(target);res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream','Cache-Control':'no-cache'});res.end(data);
 }catch(e){send(res,e.status|| (e.code==='ENOENT'?404:500),{error:e.status?e.message:'요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.'});}
}).listen(port,process.env.HOST||'0.0.0.0',()=>console.log(`LunchRun DEMO 3\nPC: http://127.0.0.1:${port}\nPHONE (same Wi-Fi): ${phoneUrl(port)}`));
