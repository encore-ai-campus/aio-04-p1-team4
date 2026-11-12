import json
from pathlib import Path
import pytest
from sqlalchemy import select
from app.database import Database, MenuAlias, MenuCatalog
from app.database.cli import initialize, load_json, restaurant_detail, summary

SAMPLE=Path(__file__).parents[1]/'sample_data/kakao_place_example.json'

def test_init_is_repeatable_and_alias_resolves(tmp_path):
    path=tmp_path/'lunchrun.db'
    first=initialize(path)
    again=initialize(path)
    assert len(first['tables'])==7
    assert again['catalog_added']==0
    database=Database(f'sqlite:///{path.as_posix()}')
    try:
        with database.session_factory() as session:
            row=session.scalar(select(MenuCatalog).join(MenuAlias).where(MenuAlias.normalized_name=='자장면'))
            assert row.name=='짜장면'
    finally:database.dispose()

def test_real_snapshot_save_and_query_are_idempotent(tmp_path):
    path=tmp_path/'lunchrun.db';initialize(path)
    database=Database(f'sqlite:///{path.as_posix()}')
    try:
        load_json(database,SAMPLE);load_json(database,SAMPLE)
        row=restaurant_detail(database,'965494663')
        assert row['name']=='토스트카페이순신'
        assert len(row['menus'])==5
        assert len(row['business_hours'])==7
        assert row['menus'][0]['price_status']=='known'
        assert row['detail_status']['menu_status']=='success'
        assert row['detail_status']['hours_status']=='success'
        assert row['detail_status']['last_success_at'].year==2026
        # 예제 원문의 17:57(+09:00)을 08:57 UTC로 저장·조회한다.
        assert row['detail_status']['last_success_at'].hour==8
        assert summary(database)['counts']['restaurant']==1
    finally:database.dispose()

def test_non_kakao_internal_id_rejected_before_saving(tmp_path):
    path=tmp_path/'lunchrun.db';initialize(path)
    data=json.loads(SAMPLE.read_text(encoding='utf-8'))
    data['documents'][0]['id']='license:123'
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(data),encoding='utf-8')
    database=Database(f'sqlite:///{path.as_posix()}')
    try:
        with pytest.raises(ValueError,match='카카오 장소 ID'):load_json(database,bad)
        assert summary(database)['counts']['restaurant']==0
    finally:database.dispose()
