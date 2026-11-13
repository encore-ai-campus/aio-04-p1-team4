"""대표 메뉴 확장 예정 자료만 생성한다. DB 접근·적재 기능은 없다."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import re
import shutil
from prepare_csv_stage3 import norm

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT/'tmp'/'csv_stage3_preview'
OUT = ROOT/'tmp'/'csv_stage3_catalog_review'

# Exact dish names only. Ingredients and different dishes are never collapsed by substring.
MEALS = {
 '한식': '제육볶음|육개장|청국장|부대찌개|순두부찌개|제육덮밥|오징어볶음|순대국|뼈해장국|갈비탕|김치볶음밥|동태탕|차돌된장찌개|뚝배기불고기|짬뽕밥|돌솥비빔밥|내장탕|떡만두국|알탕|오므라이스|오징어덮밥|떡국|선지해장국|해물순두부|육회비빔밥|소고기국밥|돼지국밥|소머리국밥|설렁탕|곰탕|우거지해장국|황태해장국|북어국|북엇국|콩나물국밥|돼지김치찌개|참치김치찌개|고등어구이|고등어조림|갈치조림|갈치구이|불고기덮밥|소불고기덮밥|닭갈비덮밥|낙지덮밥|낙지볶음|닭곰탕|닭개장|닭칼국수|만두국|떡갈비정식|보쌈정식|불고기정식|백반|가정식백반|한식뷔페|한식백반|쌈밥|쌈밥정식|두부찌개|고추장찌개|차돌순두부|김치순두부|들깨순두부|들깨수제비|수제비|감자수제비|칼국수|들깨칼국수|바지락칼국수|장칼국수|콩국수|잔치국수|비빔국수|열무국수|메밀국수|막국수|비빔막국수|물막국수',
 '중식': '볶음밥|간짜장|새우볶음밥|삼선짬뽕|잡채밥|차돌짬뽕|잡탕밥|짜장밥|삼선볶음밥|마파두부밥|마파두부덮밥|해물짬뽕|삼선짜장|유니짜장|고추짬뽕|백짬뽕|쟁반짜장|짜장면곱빼기|짬뽕곱빼기|군만두정식',
 '일식/회': '치즈돈가스|등심돈가스|안심돈가스|고구마돈가스|로스카츠|히레카츠|가츠동|규동|사케동|회덮밥|알밥|가라아게덮밥|카레라이스|카레우동|냉모밀|판모밀|메밀소바|돈가스정식|돈가스카레|연어덮밥|장어덮밥|새우튀김우동|김치우동|어묵우동|유부우동|붓카케우동',
 '분식': '라면|참치김밥|치즈김밥|김치김밥|야채김밥|소고기김밥|김밥|떡라면|치즈라면|만두라면|해물라면|라볶이|쫄면|떡볶이|국물떡볶이|떡만두라면|참치마요덮밥|치킨마요덮밥|돈가스김밥',
 '냉면': '물냉면|비빔냉면|냉면|회냉면|물비빔냉면',
 '양식': '토마토파스타|봉골레파스타|알리오올리오|로제파스타|미트소스스파게티|볼로네제파스타|까르보나라|새우로제파스타|새우크림파스타|해물토마토파스타|버섯크림리조또|토마토리조또',
}
ALIASES = {
 '순대국밥':'순대국', '순댓국':'순대국', '만둣국':'만두국',
 '치즈돈까스':'치즈돈가스','등심돈까스':'등심돈가스','안심돈까스':'안심돈가스',
 '고구마돈까스':'고구마돈가스','돈까스정식':'돈가스정식','돈까스카레':'돈가스카레',
 '돈까스김밥':'돈가스김밥','김치돈까스':'김치돈가스',
 '차돌박이짬뽕':'차돌짬뽕', '자장밥':'짜장밥', '간자장':'간짜장',
}
# Canonical dish omitted above must not become a dangling alias.
MEALS['일식/회'] += '|김치돈가스'
MEALS['한식'] = MEALS['한식'].replace('|짬뽕밥', '')
MEALS['중식'] += '|짬뽕밥'
SIDES = {'공기밥','계란찜','계란말이','라면사리','우동사리','쫄면사리','사리','밥추가','면추가','치즈추가','치즈','볶음밥추가','셀프볶음밥','사리추가','떡사리','계란후라이','군만두','물만두','새우튀김','감자튀김'}
ALCOHOL = {'처음처럼','참이슬후레쉬','참이슬오리지널','참이슬','카스','테라','새로','청하','진로','진로이즈백','클라우드','한라산','좋은데이','대선','백세주','복분자','화요','일품진로','하이볼'}
BEVERAGE = re.compile(r'아메리카노|라떼|커피|에이드|콜드브루|에스프레소|카푸치노|카페모카|스무디|프라페|주스|쥬스|콜라|사이다|탄산|밀크티|녹차|홍차|얼그레이|캐모마일|페퍼민트|보이차|루이보스|생수|음료')
ALCOHOL_PATTERN = re.compile(r'소주|맥주|막걸리|와인|위스키|위스키|하이볼|생맥|주류|고량주|연태|칭따오|산미구엘|기네스|하이네켄|버드와이저|호가든|산토리|아사히|잭다니엘|발렌타인|조니워커')
SHARING = re.compile(r'세트|커플|패밀리|모듬|모둠|한판|\b[2-9]\s*인|[2-9]\s*인분|\b\d+\s*인세트|\([대중]\)|\b[대중]\s*$|\d+\s*(g|kg|그람|그램)\b',re.I)


def read(name):
    with (SOURCE/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def write(name,rows,fields):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    catalogs=read('menu_catalog.csv');aliases=read('menu_alias.csv');menus=read('menus.csv')
    lookup={norm(a['name']):a['menu_catalog_id'] for a in aliases}
    by_name={norm(c['name']):c['id'] for c in catalogs}
    for cuisine,names in MEALS.items():
        for name in names.split('|'):
            n=norm(name)
            if n not in by_name:
                uid='dish_'+hashlib.sha256(n.encode()).hexdigest()[:20]
                catalogs.append(dict(id=uid,name=name,normalized_name=n,active=True,cuisine=cuisine,search_keyword=name,description='',price_hint=''))
                by_name[n]=uid
            lookup[n]=by_name[n]
    # Keep 까르보나라 distinct instead of asserting all cream pasta is identical.
    for name,target in ALIASES.items():
        lookup[norm(name)]=by_name[norm(target)]
    decisions=Counter();unresolved=Counter();examples={}
    for m in menus:
        name=m['name'];n=norm(name);m['menu_catalog_id']='';m['catalog_rule']=''
        if n in lookup:
            state='linked';m['menu_catalog_id']=lookup[n];m['catalog_rule']='exact_curated_name_or_alias'
        elif n in SIDES or re.search(r'추가|토핑|사리',name):state='excluded_side_or_addon'
        elif n in ALCOHOL or ALCOHOL_PATTERN.search(name):state='excluded_alcohol'
        elif BEVERAGE.search(name):state='excluded_beverage'
        elif SHARING.search(name):state='review_set_or_portion'
        else:
            # Only explicit 1-person/ordinary portion annotations are safely removable.
            clean=re.sub(r'^(?:1\s*인(?:분)?\s*)','',name).strip()
            clean=re.sub(r'\s*\((?:1\s*인(?:분)?|보통)\)\s*$','',clean).strip()
            if clean!=name and norm(clean) in lookup:
                state='linked';m['menu_catalog_id']=lookup[norm(clean)];m['catalog_rule']='explicit_single_portion_annotation'
            else:state='review_unmapped_dish'
        # Whole pizza cannot be assumed to fit a per-person lunch budget.
        if m['menu_catalog_id']=='pizza':
            m['menu_catalog_id']='';state='review_set_or_portion';m['catalog_rule']='pizza_serving_size_unverified'
        m['catalog_status']=state
        m['serving_status']='explicit_single' if re.search(r'(?<!\d)1\s*인(?!\d)',name) else 'unverified'
        decisions[state]+=1
        if state!='linked':unresolved[(name,state)]+=1
        examples.setdefault(state,[])
        if len(examples[state])<10 and name not in examples[state]:examples[state].append(name)
    used=Counter(m['menu_catalog_id'] for m in menus if m['menu_catalog_id'])
    # Only actual matching names become proposed catalog/alias rows.
    catalogs=[c for c in catalogs if used[c['id']]]
    for c in catalogs:c['linked_products']=used[c['id']]
    id_names={c['id']:c['name'] for c in catalogs}
    alias_rows=[]
    for name,uid in sorted(lookup.items()):
        if uid in id_names:alias_rows.append(dict(menu_catalog_id=uid,name=name,normalized_name=name))
    fields=list(menus[0])
    write('menus.csv',menus,fields)
    write('menu_catalog.csv',catalogs,['id','name','normalized_name','active','cuisine','search_keyword','description','price_hint','linked_products'])
    write('menu_alias.csv',alias_rows,['menu_catalog_id','name','normalized_name'])
    write('unlinked_product_review.csv',[dict(name=n,catalog_status=s,product_count=count) for (n,s),count in unresolved.most_common()],['name','catalog_status','product_count'])
    for name in ('restaurants.csv','restaurant_matches.csv','reviews.csv','excluded_rows.csv'):
        shutil.copyfile(SOURCE/name,OUT/name)
    assert sum(decisions.values())==len(menus)
    assert all(not m['menu_catalog_id'] or m['menu_catalog_id'] in id_names for m in menus)
    assert len({a['normalized_name'] for a in alias_rows})==len(alias_rows)
    summary=dict(planned_restaurants=len(read('restaurants.csv')),planned_menus=len(menus),
        original_catalog_count=10,proposed_catalog_count=len(catalogs),original_linked_products=402,
        classification=dict(decisions),linked_known_price=sum(bool(m['menu_catalog_id']) and m['price_status']=='known' for m in menus),
        examples=examples,supabase_written=False)
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
