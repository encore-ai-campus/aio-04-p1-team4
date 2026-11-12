"""LunchRun SQLAlchemy 모델을 SQLite와 PostgreSQL 마이그레이션에 연결한다."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool, make_url

from app.config import DEFAULT_DATABASE_URL, ENV_FILE
from app.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 운영 환경변수가 로컬 .env보다 우선하며 API 키 설정은 마이그레이션에 필요 없다.
load_dotenv(ENV_FILE, override=False)
x_arguments = context.get_x_argument(as_dictionary=True)
database_url = str(
    config.attributes.get("database_url")
    or x_arguments.get("database_url")
    or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
).strip()
parsed_url=make_url(database_url)
if parsed_url.get_backend_name() == 'postgresql':
    parsed_url=parsed_url.set(drivername='postgresql+psycopg').update_query_dict({
        'sslmode':parsed_url.query.get('sslmode') or 'require','connect_timeout':'8'})
    database_url=parsed_url.render_as_string(hide_password=False)
# ConfigParser에서 URL의 퍼센트 문자가 보간식으로 처리되지 않게 이스케이프한다.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DB 연결 없이 SQL 스크립트를 생성할 때 사용하는 경로."""

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """실제 DB 연결에서 트랜잭션 단위로 마이그레이션을 실행한다."""

    provided_connection=config.attributes.get('connection')
    if provided_connection is not None:
        context.configure(connection=provided_connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={'prepare_threshold':None} if parsed_url.get_backend_name()=='postgresql' else {},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
