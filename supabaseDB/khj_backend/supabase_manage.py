"""비밀값을 출력하지 않고 Supabase 연결·스키마·API 검증 자료 이전을 관리한다."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import inspect, select, text
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.database import Database, Restaurant, Menu, BusinessHours, PlaceDetailStatus
from app.database.cli import initialize_url, summary
from app.database.seed import seed_menu_catalog

ROOT=Path(__file__).resolve().parent


def configured_url():
    env={**dotenv_values(ROOT.parent/'.env'),**dotenv_values(ROOT/'.env'),**os.environ}
    url=env.get('DATABASE_URL') or env.get('SUPABASE_DB_URL')
    if not url:
        raise ValueError('missing_supabase_db_url')
    return url


def values(row, *, omit=()):
    result={}
    for column in row.__table__.columns:
        if column.name in omit:
            continue
        value=getattr(row,column.name)
        if isinstance(value,datetime) and value.tzinfo is None:
            value=value.replace(tzinfo=timezone.utc)
        result[column.name]=value
    return result


def copy_verified(source, destination):
    counts={'copied_restaurants':0,'copied_menus':0,'copied_hours':0,'existing_skipped':0}
    with source.session_factory() as src, destination.session_factory.begin() as dst:
        for row in src.scalars(select(Restaurant).where(Restaurant.basic_source=='kakao_api')):
            if dst.get(Restaurant,row.id) is not None:
                counts['existing_skipped']+=1
                continue
            dst.add(Restaurant(**values(row)))
            dst.flush()
            status=row.detail_status
            if status:
                dst.add(PlaceDetailStatus(**values(status)))
            if status and status.menu_source_url==row.place_url:
                for menu in row.menus:
                    dst.add(Menu(**values(menu,omit=('id',))))
                    counts['copied_menus']+=1
            if status and status.hours_source_url==row.place_url:
                for hours in row.business_hours:
                    dst.add(BusinessHours(**values(hours,omit=('id',))))
                    counts['copied_hours']+=1
            counts['copied_restaurants']+=1
    return counts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('check','init','copy-sqlite','reset'))
    args=parser.parse_args()
    database=None
    try:
        url=configured_url()
        database=Database(url)
        if database.engine.dialect.name!='postgresql':
            raise ValueError('postgresql_url_required')
        if args.action=='check':
            with database.engine.connect() as connection:
                connection.execute(text('select 1'))
                tables=inspect(connection).get_table_names()
                rls=connection.execute(text("SELECT relname,relrowsecurity FROM pg_class JOIN pg_namespace ON pg_namespace.oid=pg_class.relnamespace WHERE nspname='public' AND relname IN ('menu_catalog','menu_alias','restaurant','menu','business_hours','place_detail_status','alembic_version')")).all()
            details=summary(database) if all(t in tables for t in ('restaurant','menu','business_hours','menu_catalog','menu_alias','place_detail_status','alembic_version')) else {'tables':tables}
            print(json.dumps({'connected':True,'database':'postgresql',**details,'row_level_security':dict(rls)},ensure_ascii=False))
        elif args.action=='reset':
            # 사용자 요청으로 지정한 앱 테이블만 초기화한다. 다른 스키마/테이블은 건드리지 않는다.
            # DROP과 재생성을 한 트랜잭션에서 수행하여 실패하면 원래 상태로 복구한다.
            with database.engine.begin() as connection:
                for name in ('place_detail_status','business_hours','menu','restaurant','menu_alias','menu_catalog','alembic_version'):
                    connection.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
                config=Config(str(ROOT/'alembic.ini'))
                config.set_main_option('script_location',str(ROOT/'alembic'))
                config.attributes['database_url']=database.engine.url.render_as_string(hide_password=False)
                config.attributes['connection']=connection
                command.upgrade(config,'head')
                with Session(bind=connection) as session:
                    seed_menu_catalog(session)
                    session.commit()
            print(json.dumps({'reset':True,**summary(database)},ensure_ascii=False))
        else:
            result=initialize_url(url)
            if args.action=='copy-sqlite':
                source=Database(f'sqlite:///{(ROOT/"data/lunchrun.db").as_posix()}')
                try: result.update(copy_verified(source,database))
                finally: source.dispose()
            result.update(summary(database))
            print(json.dumps(result,ensure_ascii=False))
        return 0
    except Exception as error:
        message=str(getattr(error,'orig',error)).lower()
        code=('password_authentication_failed' if 'password authentication failed' in message else
              'connection_unavailable' if type(error).__name__=='OperationalError' else type(error).__name__)
        print(json.dumps({'connected':False,'error':code},ensure_ascii=False))
        return 1
    finally:
        if database is not None: database.dispose()


if __name__=='__main__':
    raise SystemExit(main())
