(function(root){
  const labels=['전체','한식','중식','일식','양식','분식','치킨','피자','아시아음식','카페·디저트','술집','뷔페·구내식당'];
  function categoryLabel(text){
    if(!text)return null;
    for(const [label,pattern] of [
      ['중식',/중식|중국|짜장|짬뽕|마라탕|양꼬치/],
      ['일식',/일식|일본|초밥|스시|돈까스|돈가스|라멘|우동|소바/],
      ['피자',/피자/],['치킨',/치킨|통닭/],
      ['분식',/분식|김밥|떡볶이|만두/],
      ['카페·디저트',/카페|까페|커피|제과|베이커리|디저트|아이스크림|도넛|빵집|주스|차전문|찻집|파리바게뜨/],
      ['아시아음식',/아시아|베트남|태국|인도음식|인도요리|쌀국수|동남아/],
      ['양식',/양식|서양|경양식|이탈리|프랑스|스테이크|파스타|햄버거|버거|샌드위치|멕시코|패밀리레스토랑|패밀리레스트랑|패스트푸드|토스트|샐러드|포케/],
      ['술집',/주점|술집|호프|포장마차|이자카야|와인바|소주방|대포집|정종|주류|맥주|칵테일|펍/],
      ['뷔페·구내식당',/뷔페|부페|구내식당|급식/],
      ['한식',/한식|국밥|해장국|찌개|백반|육류|식육|숯불구이|고기|삼겹살|갈비|족발|보쌈|냉면|국수|설렁탕|곰탕|감자탕|추어탕|순대|닭갈비|닭요리|닭발|찜닭|삼계탕|해물|생선|장어|곱창|막창|죽,|죽전문|횟집|회,|수산|도시락|한식뷔페/]
    ])if(pattern.test(text))return label;
    return null;
  }
  function details(r){
    if(r.cuisineReview?.label)return r.cuisineReview;
    const saved=root.CUISINE_DATA?.byLicense?.[r.licenseId]||root.CUISINE_DATA?.byId?.[r.id];
    if(saved&&saved.label!=='기타·미분류')return saved;
    // Matched map categories describe the actual place; licensing types can be stale.
    for(const [text,method] of [[r.categoryPath,'카카오 상세 분류'],[r.naverCategory||(['verified','listing_verified'].includes(r.naverPlace?.status)?r.naverPlace.naverCategory:null),'네이버 확인 업종'],[r.category,'등록 업태']]){
      const label=categoryLabel(text);if(label)return {label,method,evidence:text};
    }
    const menuRules=[['한식',/찌개|국밥|삼겹|목살|등심덧살|한우차돌|LA갈비|불고기|제육|비빔밥|갈비탕|곰탕|냉면|순대국|두루치기|족발|보쌈/],['중식',/짜장면|자장면|짬뽕|탕수육|마라탕/],['일식',/돈까스|돈카츠|초밥|스시|돈코츠라멘|사시미|카츠정식|카레|까스/],['양식',/파스타|스테이크|리조또|버거|샌드위치|포케/],['분식',/떡볶이|김밥|김말이/],['카페·디저트',/아메리카노|에스프레소|카페라떼|카푸치노|케이크|휘낭시에|베이글/],['아시아음식',/쌀국수|월남쌈|팟타이|반미/],['피자',/피자/],['치킨',/치킨|후라이드|통닭/]];
    const menus=r.menus||[];
    const scores=menuRules.map(([label,pattern])=>({label,hits:menus.filter(m=>pattern.test(m.name))})).sort((a,b)=>b.hits.length-a.hits.length);
    const best=scores[0],next=scores[1];
    if(best.hits.length>=2&&best.hits.length>=menus.length*.4&&best.hits.length>=next.hits.length*2)return {label:best.label,method:'공개 메뉴 대조',evidence:best.hits.slice(0,5).map(m=>m.name).join(' / ')};
    return saved||{label:'기타·미분류',method:'분류 근거 부족',evidence:''};
  }
  const classify=r=>details(r).label;
  function populate(select,rows){
    const counts=new Map();
    rows.forEach(r=>{const label=classify(r);counts.set(label,(counts.get(label)||0)+1);});
    const value=select.value||'전체';select.replaceChildren();
    labels.forEach(label=>{const option=document.createElement('option');option.value=label;option.textContent=`${label} (${label==='전체'?rows.length:counts.get(label)||0})`;select.append(option);});
    select.value=labels.includes(value)?value:'전체';
  }
  root.LunchRunCuisine={labels,classify,details,populate};
})(typeof window==='undefined'?globalThis:window);
