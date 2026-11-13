import { randomBytes, randomInt } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, renameSync, mkdirSync } from 'node:fs';
import path from 'node:path';
export class RoomError extends Error { constructor(status,message){super(message);this.status=status;} }
const fail=(status,message)=>{throw new RoomError(status,message);};
const token=()=>randomBytes(24).toString('hex');
const clean=(v,max=24)=>typeof v==='string'?v.trim().slice(0,max):'';
export class RoomStore {
 constructor(file,{clock=()=>Date.now()}={}){this.file=file;this.clock=clock;this.rooms={};if(file&&existsSync(file))this.rooms=JSON.parse(readFileSync(file,'utf8'));}
 save(){if(!this.file)return;mkdirSync(path.dirname(this.file),{recursive:true});writeFileSync(this.file+'.tmp',JSON.stringify(this.rooms));renameSync(this.file+'.tmp',this.file);}
 room(code){const r=this.rooms[String(code).toUpperCase()];if(!r)fail(404,'모임방을 찾지 못했어요.');if(r.expiresAt<this.clock())fail(410,'24시간이 지나 만료된 방이에요. 새 방을 만들어주세요.');if(r.phase==='drawing'&&this.clock()>=r.draw.endsAt){r.phase='decided';r.selectedId=r.draw.menuId;this.save();}return r;}
 member(r,key){const m=r.members.find(x=>x.token===key);if(!m)fail(401,'이 방에 닉네임으로 참여해 주세요.');return m;}
 host(r,key){const m=this.member(r,key);if(m.id!==r.hostId)fail(403,'방장만 할 수 있어요.');return m;}
 create({nickname,title,filters,menus}){if(!clean(nickname))fail(400,'닉네임을 입력해 주세요.');if(!Array.isArray(menus)||menus.length<1||menus.length>24)fail(400,'후보 메뉴가 1~24개 필요해요. 조건을 넓혀주세요.');if(Object.values(this.rooms).filter(r=>r.expiresAt>this.clock()).length>=100)fail(429,'모임방이 많아요. 잠시 후 시도해주세요.');let code;do{code=String(randomInt(100000,1000000));}while(this.rooms[code]);const me={id:token(),token:token(),nickname:clean(nickname),submitted:false,choices:[]};const r={code,title:clean(title,40)||'오늘의 점심 모임',filters,menus,originalMenus:menus,hostId:me.id,members:[me],phase:'lobby',round:1,createdAt:this.clock(),expiresAt:this.clock()+86400000,draw:null,selectedId:null};this.rooms[code]=r;this.save();return {code,token:me.token};}
 join(code,nickname){const r=this.room(code);if(r.phase!=='lobby')fail(409,'이미 선택이 시작된 방이에요. 방장에게 다시 모집을 요청해주세요.');if(r.members.length>=12)fail(409,'최대 12명까지 참여할 수 있어요.');const name=clean(nickname);if(!name)fail(400,'닉네임을 입력해 주세요.');if(r.members.some(m=>m.nickname===name))fail(409,'같은 닉네임이 있어요. 다른 이름을 사용해주세요.');const me={id:token(),token:token(),nickname:name,submitted:false,choices:[]};r.members.push(me);this.save();return {code:r.code,token:me.token};}
 compute(r){const count=Object.fromEntries(r.menus.map(m=>[m.id,0]));for(const m of r.members)for(const id of m.choices)count[id]++;const common=r.menus.filter(m=>count[m.id]===r.members.length),max=Math.max(...Object.values(count));return {counts:count,commonIds:common.map(m=>m.id),topIds:r.menus.filter(m=>count[m.id]===max).map(m=>m.id),maxVotes:max};}
 view(code,key){const r=this.room(code),me=this.member(r,key),completed=r.members.filter(m=>m.submitted).length;return {code:r.code,title:r.title,filters:r.filters,phase:r.phase,round:r.round,expiresAt:r.expiresAt,me:{id:me.id,nickname:me.nickname,isHost:me.id===r.hostId,choices:me.choices,submitted:me.submitted},members:r.members.map(m=>({id:m.id,nickname:m.nickname,isHost:m.id===r.hostId,submitted:m.submitted})),menus:r.menus,completed,total:r.members.length,result:['results','drawing','decided'].includes(r.phase)?this.compute(r):null,draw:r.phase==='drawing'?{endsAt:r.draw.endsAt,startedAt:r.draw.startedAt}:null,selectedId:r.selectedId};}
 action(code,key,kind,data={}){const r=this.room(code);if(data.round!==r.round)fail(409,'모임 라운드가 바뀌었어요. 새 화면에서 다시 선택해 주세요.');
  if(kind==='start'){this.host(r,key);if(r.phase!=='lobby')fail(409,'이미 시작한 모임이에요.');if(r.members.length<2)fail(400,'2명 이상 모이면 시작할 수 있어요.');r.phase='voting';}
  else if(kind==='select'){const me=this.member(r,key);if(r.phase!=='voting')fail(409,'지금은 메뉴를 선택할 수 없어요.');if(!Array.isArray(data.choices)||!data.choices.length)fail(400,'메뉴를 하나 이상 골라주세요.');const ids=[...new Set(data.choices)];if(ids.some(id=>!r.menus.some(m=>m.id===id)))fail(400,'이 방의 후보 메뉴만 고를 수 있어요.');me.choices=ids;me.submitted=true;if(r.members.every(m=>m.submitted))r.phase='results';}
  else if(kind==='revote'){this.host(r,key);if(r.phase!=='results'||this.compute(r).commonIds.length)fail(409,'공통 메뉴가 없을 때만 최다 후보로 다시 고를 수 있어요.');const top=this.compute(r).topIds;r.menus=r.menus.filter(m=>top.includes(m.id));this.newRound(r,'voting');}
  else if(kind==='reset'){this.host(r,key);r.menus=r.originalMenus;this.newRound(r,'lobby');}
  else if(kind==='remove'){this.host(r,key);if(r.phase!=='lobby')fail(409,'대기실에서만 참여자를 정리할 수 있어요.');if(data.id===r.hostId)fail(400,'방장은 삭제할 수 없어요.');r.members=r.members.filter(m=>m.id!==data.id);}
  else if(kind==='draw'){this.host(r,key);if(r.phase==='drawing')return {targetId:r.draw.menuId,endsAt:r.draw.endsAt};if(r.phase!=='results')fail(409,'모두 선택한 뒤 결정할 수 있어요.');const ids=this.compute(r).commonIds;if(!ids.length)fail(400,'먼저 최다 후보로 다시 골라주세요.');const target=ids[randomInt(ids.length)];r.draw={menuId:target,startedAt:this.clock(),endsAt:this.clock()+2800};r.phase='drawing';this.save();return {targetId:target,endsAt:r.draw.endsAt};}
  else fail(404,'지원하지 않는 요청이에요.');this.save();return {ok:true};}
 newRound(r,phase){r.round++;r.phase=phase;r.draw=null;r.selectedId=null;for(const m of r.members){m.choices=[];m.submitted=false;}}
}
