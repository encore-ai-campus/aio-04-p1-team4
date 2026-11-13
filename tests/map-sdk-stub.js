// SDK contract double: tests UI wiring without contacting Kakao or fabricating production maps.
window.kakao={maps:{load:fn=>fn(),LatLng:class{constructor(lat,lng){this.lat=lat;this.lng=lng;}},Map:class{constructor(container){this.container=container;}panTo(p){window.testPan=p;}setBounds(){}},Circle:class{setMap(){}getBounds(){return {};}},CustomOverlay:class{constructor(options){this.node=options.content;this.map=options.map;this.map.container.append(this.node);}setMap(map){if(!map)this.node.remove();}setZIndex(){}}}};
window.kakao.maps.LatLngBounds=class{extend(){}};
window.kakao.maps.Polyline=class{setMap(){}};
window.kakao.maps.Map.prototype.getCenter=function(){return {getLat:()=>37.48,getLng:()=>126.88};};
