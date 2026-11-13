import {test} from 'node:test';
import assert from 'node:assert/strict';
import {gameRequest,gameMenu,matchEntry,backendRequest,FOOD_TYPES} from './dist/backend.mjs';
import {RoomStore} from './room-store.mjs';
const filters={location:'현재 위치',origin:[37.48,126.88],budget:9000,time:30,distance:500,categories:['중식']};
test('game request keeps backend conditions and chosen ID',()=>{
 const body=gameRequest({...filters,origin:[37.48,126.88]},'noodle');
 assert.deepEqual(body.conditions,{budget:9000,minutes:30,cuisine:'중식'});
 assert.equal(body.menu_id,'noodle');assert.equal(body.location.lat,37.48);
 assert.equal(FOOD_TYPES.length,15);
 for(const change of [{budget:100001},{distance:0},{time:121},{categories:['한식','중식']},{origin:[91,127]}])assert.throws(()=>gameRequest({...filters,...change}));
});
test('named places cannot silently become fixed coordinates',()=>{
 assert.throws(()=>gameRequest({...filters,origin:null,location:'독산역'}),/위치/);
 const selectedLocation={lat:37.48,lng:126.88,name:'선택 장소',address:'서울',source:'place'};
 assert.deepEqual(gameRequest({...filters,selectedLocation}).location,selectedLocation);
});
test('games and room requests use the original deadline and reject expired lunch time',()=>{
 assert.throws(()=>gameRequest({...filters,lunchDeadline:Date.now()-1000}),/time/);
 const request=gameRequest({...filters,time:120,lunchDeadline:Date.now()+5*60000});
 assert.equal(request.conditions.minutes,5);
});
test('unknown price stays unknown and entered text must match backend pool',()=>{
 const m=gameMenu({id:'noodle',name:'짜장면',cuisine:'중식',price_hint:8000,price_verified:false});
 assert.equal(m.price,null);assert.equal(matchEntry(' 짜 장 면 ',[m]),m);
 assert.equal(matchEntry('피자',[m]),undefined);
});
test('backend failure does not fall back to demo candidates',async()=>{
 await assert.rejects(backendRequest('/api/menus/candidates',gameRequest(filters),{fetcher:async()=>({ok:false,status:503,json:async()=>({detail:'DB unavailable'})})}),/DB unavailable/);
});
test('intersection supports a single backend candidate without adding fake menus',()=>{
 const store=new RoomStore(null);const menus=[{id:'noodle',name:'짜장면'}];
 const host=store.create({nickname:'host',filters,menus});const guest=store.join(host.code,'guest');
 store.action(host.code,host.token,'start',{round:1});
 for(const token of [host.token,guest.token])store.action(host.code,token,'select',{round:1,choices:['noodle']});
 assert.deepEqual(store.view(host.code,host.token).result.commonIds,['noodle']);
});
