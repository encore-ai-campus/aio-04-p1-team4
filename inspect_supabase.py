"""DB 구조만 읽는 진단 도구. 비밀값·실제 데이터는 출력하지 않는다."""
import json
import os
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from app.database.session import normalize_database_url


def main():
    values = dotenv_values(Path(__file__).resolve().parent / '.env')
    raw = (os.environ.get('DATABASE_URL') or os.environ.get('SUPABASE_DB_URL')
           or values.get('DATABASE_URL') or values.get('SUPABASE_DB_URL'))
    if not raw:
        print('Database URL not configured'); return 1
    url = normalize_database_url(raw)
    if url.get_backend_name() != 'postgresql':
        print('PostgreSQL URL required'); return 1
    engine = None
    try:
        engine = create_engine(url, connect_args={'connect_timeout': 10})
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            inspector = inspect(connection)
            tables = inspector.get_table_names(schema='Lunchrun')
            report = {'connected': True, 'schema': 'Lunchrun', 'tables': tables, 'structure': {}}
            allowed = {'restaurant', 'menu', 'menu_catalog', 'menu_alias',
                       'business_hours', 'place_detail_status', 'restaurant_match'}
            for table in sorted(allowed.intersection(tables)):
                report['structure'][table] = {
                    'rows': connection.scalar(text(f'SELECT count(*) FROM "Lunchrun"."{table}"')),
                    'columns': [{'name': c['name'], 'type': str(c['type']), 'nullable': c['nullable']}
                                for c in inspector.get_columns(table, schema='Lunchrun')],
                    'foreign_keys': inspector.get_foreign_keys(table, schema='Lunchrun'),
                }
            if 'alembic_version' in tables:
                report['alembic_versions'] = list(connection.scalars(text(
                    'SELECT version_num FROM "Lunchrun".alembic_version')))
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as error:
        print(json.dumps({'connected': False, 'error_type': type(error).__name__}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
