const test=require('node:test'),assert=require('node:assert/strict');
const {groups}=require('../kakao-map/pin-overlaps.js');
const {routeUrl,walkingConnections}=require('../kakao-map/routes.js');
test('겹친 식당을 중복 없이 묶고 떨어진 핀은 분리한다',()=>{
 const result=groups([{id:'a',x:10,y:10},{id:'b',x:12,y:12},{id:'c',x:200,y:200}]);
 assert.deepEqual(result.map(g=>g.members.length),[2,1]);assert.equal(new Set(result.flatMap(g=>g.members.map(p=>p.id))).size,3);
});
test('카카오 길찾기는 유효 좌표와 인코딩한 이름을 사용한다',()=>{
 const a={lat:37.5,lng:127,name:'출발 / 위치'},b={lat:37.51,lng:127.01,name:'식당'};
 assert.ok(routeUrl(a,b).startsWith('https://map.kakao.com/link/by/walk/'));assert.ok(routeUrl(a,b).includes(encodeURIComponent(a.name)));
 assert.equal(routeUrl({...a,lat:NaN},b),null);assert.equal(routeUrl(a,b,'javascript'),null);
});
test('끊긴 경로는 실제 구간 사이의 연결선을 반환한다',()=>{
 assert.deepEqual(walkingConnections([[[127,37.5],[127.1,37.6]],[[127.2,37.7],[127.3,37.8]]],{lat:37.5,lng:127},{lat:37.8,lng:127.3}),[[[127.1,37.6],[127.2,37.7]]]);
});
