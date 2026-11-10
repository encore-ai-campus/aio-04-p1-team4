const catalog = window.MENU_CATALOG;
const isNaverPlaceConfirmed=r=>['verified','listing_verified'].includes(r.naverPlace?.status);
const entries = [...catalog.restaurants].sort((a,b)=>a.name.localeCompare(b.name,'ko'));
const summary = catalog.summary;
const stats = document.getElementById('catalog-stats');
for(const [value,label] of [[entries.length,'모든 가게'],[summary.restaurantsWithMenus,'메뉴 있는 가게'],[entries.filter(r=>!r.menus.length).length,'메뉴 없는 가게'],[summary.menuCount,'수집한 메뉴'],[summary.pricedMenuCount,'가격 표시 메뉴']]){
  const box=document.createElement('div');box.className='catalog-stat';
  const strong=document.createElement('strong');strong.textContent=value.toLocaleString('ko-KR');
  const span=document.createElement('span');span.textContent=label;box.append(strong,span);stats.append(box);
}
document.getElementById('catalog-note').textContent=`최근 확인일 ${catalog.retrievedAt.slice(0,10)} · 원본 인허가 음식점 ${(summary.sourceLicensedRestaurants || summary.licensedRestaurants).toLocaleString('ko-KR')}곳 중 카카오 장소 매칭 ${summary.matchedRestaurants.toLocaleString('ko-KR')}곳을 확인했습니다. 카카오에 메뉴가 없는 가게 중 ${summary.naverSupplementedRestaurants || 0}곳은 네이버 플레이스로 보완했습니다. 독산역 주변 추가 가게도 포함합니다. ${summary.excludedLicensedRestaurants ? `식사 추천에서 제외한 인허가 등록 ${summary.excludedLicensedRestaurants}건은 목록과 집계에서 뺐습니다. ` : ''} 텍스트로 등록된 메뉴만 수집했으며, 메뉴판 사진은 포함하지 않습니다. 가게별 출처와 확인일을 참고하고 가격과 영업 여부는 매장에 확인해주세요.`;
const queryInput=document.getElementById('catalog-query');
const statusInput=document.getElementById('catalog-status');
const cuisineInput=document.getElementById('catalog-cuisine');
window.LunchRunCuisine.populate(cuisineInput,entries);
const results=document.getElementById('catalog-results');
const initialFilters=new URLSearchParams(location.search);
const initialStatus=initialFilters.get('status');
if([...statusInput.options].some(option=>option.value===initialStatus))statusInput.value=initialStatus;
if(initialFilters.has('q'))queryInput.value=initialFilters.get('q').slice(0,200);
let page=0,filtered=[],pageSize=20;
const compact=value=>(value||'').toLocaleLowerCase('ko-KR').replace(/\s+/g,'');
const naverStatusLabels={collected:'메뉴 보완 완료',no_menu_tab:'공개 텍스트 메뉴 탭 없음',no_structured_menu:'메뉴 탭에 텍스트 메뉴 미확인',not_found:'해당 검색에서 가게 미확인',match_review:'가게명·주소 연결 검토 필요',address_review:'동명 가게의 주소 연결 미확정',name_review:'가게명 연결 미확정',candidate_id_unconfirmed:'주소 일치 후보의 장소 연결 미확정',search_unavailable:'검색 조회 미완료',search_review:'검색 결과 검토 필요',page_error:'페이지 조회 실패'};
const placeStatusLabels={listing_verified:'네이버 지도 목록 확인됨',verified:'네이버 장소 확인됨',not_found:'검색에서 가게 미확인',name_review:'상호 대조 필요',address_review:'주소 대조 필요',detail_review:'층·호수 대조 필요',non_food_review:'음식점 업종 확인 필요',candidate_id_unconfirmed:'상세 페이지 연결 확인 필요',search_unavailable:'검색 조회 미완료',search_review:'검색 결과 검토 필요',page_error:'페이지 조회 실패'};
document.getElementById('catalog-note').append(` 네이버로 장소 확인 ${summary.naverPlaceVerifiedRestaurants || 0}건(고유 ${summary.naverPlaceVerifiedUniquePlaces || 0}곳) · 장소 미확정 ${(summary.placeUnresolvedRestaurants ?? summary.unmatchedLicensedRestaurants).toLocaleString('ko-KR')}건.`);
if(summary.hiddenUnverifiedRestaurants)document.getElementById('catalog-note').append(` 카카오맵·네이버 지도에서 동일 가게를 확인하지 못한 ${summary.hiddenUnverifiedRestaurants.toLocaleString('ko-KR')}건은 표시하지 않습니다.`);
if(summary.naverPlaceListingVerifiedRestaurants)document.getElementById('catalog-note').append(` 네이버 지도 목록에서만 확인된 ${summary.naverPlaceListingVerifiedRestaurants}건은 상세 ID 없이 목록 링크로 제공합니다.`);
if(summary.naverMenuRecheckedRestaurants)document.getElementById('catalog-note').append(` 메뉴가 없던 ${summary.naverMenuRecheckedRestaurants}곳을 네이버에서 재확인해 ${summary.naverMenuRecheckSupplementedRestaurants}곳의 메뉴를 추가했습니다.`);
function findEntries(){
  const q=compact(queryInput.value);
  filtered=entries.filter(r=>{
    if(cuisineInput.value!=='전체'&&window.LunchRunCuisine.classify(r)!==cuisineInput.value)return false;
    const mode=statusInput.value;
    if(mode==='with-menu'&&!r.menus.length)return false;
    if(mode==='without-menu'&&r.menus.length)return false;
    return !q||compact(`${r.name} ${r.naverPlace?.naverName || ''} ${(r.aliases || []).join(' ')} ${r.address} ${r.category} ${r.menus.map(m=>m.name).join(' ')}`).includes(q);
  });page=0;render();
}
function menuTable(menus){
  const table=document.createElement('table');
  const head=document.createElement('thead');const tr=document.createElement('tr');
  for(const title of ['메뉴','가격']){const th=document.createElement('th');th.textContent=title;tr.append(th);}head.append(tr);table.append(head);
  const body=document.createElement('tbody');
  for(const m of menus){const row=document.createElement('tr');const name=document.createElement('td');name.textContent=m.name+(m.soldOut?' · 품절 표기':'');if(m.description){const detail=document.createElement('small');detail.className='menu-description';detail.textContent=m.description;name.append(detail);}const price=document.createElement('td');price.textContent=m.priceText || (Number.isFinite(m.price)?m.price.toLocaleString('ko-KR')+'원':'가격 미등록');row.append(name,price);body.append(row);}table.append(body);return table;
}
function render(){
  results.replaceChildren();
  document.getElementById('catalog-result-count').textContent=`${filtered.length.toLocaleString('ko-KR')}곳 · 메뉴 ${filtered.reduce((s,r)=>s+r.menus.length,0).toLocaleString('ko-KR')}개`;
  for(const r of filtered.slice(page*pageSize,(page+1)*pageSize)){
    const box=document.createElement('article');box.className='catalog-restaurant';
    const top=document.createElement('div');top.className='catalog-card-top';
    const heading=document.createElement('h3');heading.textContent=r.name;top.append(heading);
    if(r.url){const link=document.createElement('a');link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=r.id?'카카오맵 ↗':'주소로 지도 보기 ↗';top.append(link);}box.append(top);
    if(isNaverPlaceConfirmed(r)){const link=document.createElement('a');link.href=r.naverPlace.sourceUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent=r.naverPlace.status==='listing_verified'?'네이버 지도 목록 ↗':'네이버 플레이스 ↗';top.append(link);}
    const cuisine=window.LunchRunCuisine.details(r);
    const badge=document.createElement('span');badge.className='catalog-status';badge.textContent=r.menus.length?`메뉴 ${r.menus.length}개 · ${cuisine.label}`:`${r.status} · ${cuisine.label}`;box.append(badge);
    const classification=document.createElement('p');classification.className='catalog-source';classification.textContent=`음식 종류 근거: ${cuisine.method}${cuisine.checkedAt?' · '+cuisine.checkedAt.slice(0,10):''}`;if(cuisine.label==='기타·미분류'&&cuisine.evidence)classification.textContent+=` · ${cuisine.evidence}`;if(cuisine.sourceUrl){const link=document.createElement('a');link.href=cuisine.sourceUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent=' · 확인 출처 ↗';classification.append(link);}box.append(classification);
    const addr=document.createElement('p');addr.className='catalog-address';addr.textContent=r.address;box.append(addr);
    const q=compact(queryInput.value);
    const menus=[...r.menus].sort((a,b)=>Number(compact(b.name).includes(q))-Number(compact(a.name).includes(q)));
    if(menus.length){box.append(menuTable(menus.slice(0,5)));if(menus.length>5){const detail=document.createElement('details');const label=document.createElement('summary');label.textContent=`나머지 메뉴 ${menus.length-5}개 보기`;detail.append(label,menuTable(menus.slice(5)));box.append(detail);}}
    else{const note=document.createElement('p');note.className='catalog-address';note.textContent=isNaverPlaceConfirmed(r)?'네이버에서 같은 가게를 확인했습니다. 연결된 메뉴 정보는 아직 없습니다.':r.id?'가져온 텍스트 메뉴가 없습니다. 카카오맵 원문을 확인해주세요.':'원본 가게와 지도 장소의 연결을 확인해야 합니다.';box.append(note);}
    if(r.retrievedAt){const source=document.createElement('p');source.className='catalog-source';source.textContent=`${r.source} · 확인 ${r.retrievedAt.slice(0,10)} · 현재 가격과 다를 수 있습니다. `;if(r.sourceUrl){const link=document.createElement('a');link.href=r.sourceUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='메뉴 원문 ↗';source.append(link);}box.append(source);}results.append(box);
    if(r.naverStatus&&!r.menus.length){const note=document.createElement('p');note.className='catalog-source';note.textContent=`네이버 확인: ${naverStatusLabels[r.naverStatus] || '추가 확인 필요'} · ${(r.naverCheckedAt || '').slice(0,10)}. `;if(r.naverUrl){const link=document.createElement('a');link.href=r.naverUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='확인 페이지 ↗';note.append(link);}box.append(note);}
    if(r.naverPlace){const note=document.createElement('p');note.className='catalog-source';note.textContent=`장소 대조: ${placeStatusLabels[r.naverPlace.status] || '추가 확인 필요'} · 확인 ${(r.naverPlace.checkedAt || '').slice(0,10)}`;if(isNaverPlaceConfirmed(r))note.textContent+=` · 네이버 상호: ${r.naverPlace.naverName} · ${r.naverPlace.naverAddress}`;box.append(note);}
  }
  if(!filtered.length){const empty=document.createElement('p');empty.className='catalog-empty';empty.textContent='검색 결과가 없습니다. 음식 종류, 검색어 또는 메뉴 확인 상태를 바꿔주세요.';results.append(empty);}
  document.getElementById('catalog-page-number').textContent=filtered.length?`${page+1} / ${Math.ceil(filtered.length/pageSize)}`:'0 / 0';
  document.getElementById('catalog-prev').disabled=page===0;document.getElementById('catalog-next').disabled=(page+1)*pageSize>=filtered.length;
}
document.getElementById('catalog-search').addEventListener('submit',e=>{e.preventDefault();findEntries();});
queryInput.addEventListener('input',findEntries);statusInput.addEventListener('change',findEntries);
cuisineInput.addEventListener('change',findEntries);
for(const [id,step] of [['catalog-prev',-1],['catalog-next',1]])document.getElementById(id).addEventListener('click',()=>{page+=step;render();document.getElementById('catalog-result-count').scrollIntoView({behavior:'smooth'});});
document.getElementById('catalog-download').addEventListener('click',()=>{
  const rows=[['카카오ID','지점명','주소','업태구분명','카카오분류(추가가게)','메뉴명','가격(원)','가격원문','확인상태','확인일시','출처링크','위도','경도','출처','메뉴설명','메뉴종류','품절표기','네이버확인상태','네이버확인일시','네이버확인링크','네이버장소ID','네이버장소확인상태','네이버장소링크','네이버장소확인일시']];
  for(const r of filtered){for(const menu of (r.menus.length?r.menus:[{}]))rows.push([r.id,r.name,r.address,r.licenseId?(r.licensedCategory || r.category):'',r.licenseId?'':r.category,menu.name,menu.price,menu.priceText,r.status,r.retrievedAt,r.sourceUrl || r.url,r.lat,r.lng,r.source,menu.description,menu.menuType,menu.soldOut?'품절':'',naverStatusLabels[r.naverStatus] || '',r.naverCheckedAt,r.naverUrl,r.naverPlace?.naverId,placeStatusLabels[r.naverPlace?.status] || '',r.naverPlace?.sourceUrl,r.naverPlace?.checkedAt]);}
  const cell=v=>{let s=String(v??'');if(/^[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
  const blob=new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'});
  const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='금천구_음식점_메뉴.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
findEntries();
