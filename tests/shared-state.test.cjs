const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/state.js'),'utf8');
function make(storage=new Map()){
 const context={window:{},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},Date,JSON,Number,Object,Set,Error};
 vm.runInNewContext(source,context);return context.window.LunchRunState;
}
const point={lat:37.48,lng:126.88,name:'출발점',address:'서울',source:'place'};
test('same-tab reload uses the same location, conditions and menu',()=>{
 const storage=new Map(),a=make(storage);a.setContext({location:point,conditions:{budget:9000,cuisine:'중식'}});a.setMenu({id:'noodle',name:'짜장면'});
 const b=make(storage),saved=b.read();assert.equal(saved.location.lat,point.lat);assert.equal(saved.conditions.budget,9000);assert.equal(saved.menu.id,'noodle');
 assert.equal(saved.conditions.deadline,a.read().conditions.deadline);
 b.setRestaurants({restaurants:[{id:'r1'}],candidate_restaurants:[{id:'r2'}]},saved.contextRevision,'noodle');b.setSelection('r1');b.setRoute({distance:100},saved.contextRevision,'r1');
 const restored=make(storage).read();assert.equal(restored.restaurants[0].id,'r1');assert.equal(restored.candidateRestaurants[0].id,'r2');assert.equal(restored.selectedRestaurantId,'r1');assert.equal(restored.route.distance,100);
});
test('context changes clear dependent results and reject old responses',()=>{
 const a=make();a.setContext({location:point});a.setMenu({id:'noodle',name:'짜장면'});const old=a.read().contextRevision;
 assert.equal(a.setRestaurants({restaurants:[{id:'r1'}]},old,'noodle'),true);a.setSelection('r1');a.setRoute({distance:100},old,'r1');
 a.setContext({conditions:{budget:8000}});const current=a.read();assert.equal(current.menu,null);assert.equal(current.restaurants.length,0);assert.equal(current.route,null);
 assert.equal(a.setRestaurants({restaurants:[{id:'old'}]},old,'noodle'),false);
});
test('reroll preserves the context but clears restaurants and selection',()=>{
 const a=make();a.setContext({location:point});a.setMenu({id:'a',name:'메뉴 A'});const before=a.read();a.setRestaurants({restaurants:[{id:'r1'}]},before.contextRevision,'a');a.setSelection('r1');
 a.setMenu({id:'b',name:'메뉴 B'});assert.equal(a.read().conditions.deadline,before.conditions.deadline);assert.equal(a.read().location.lat,point.lat);assert.equal(a.read().selectedRestaurantId,null);
});
test('identical context and navigation updates do not invalidate results',()=>{
 const a=make();a.setContext({location:point});a.setMenu({id:'a',name:'메뉴'});const before=a.read();a.setContext({location:point,conditions:before.conditions});a.setGame({mode:'solo',game:'gacha',view:'game'});
 assert.equal(a.read().contextRevision,before.contextRevision);assert.equal(a.read().menu.id,'a');assert.equal(a.setSelection('not-a-restaurant'),false);
});
