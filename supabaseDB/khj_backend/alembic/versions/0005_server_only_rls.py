"""Supabase의 공개 API에서는 DB 직접 조회를 허용하지 않는다."""
from alembic import op

revision='0005_server_only_rls'
down_revision='0004_basic_source'
branch_labels=None
depends_on=None

TABLES=('menu_catalog','menu_alias','restaurant','menu','business_hours','place_detail_status','alembic_version')

def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        for name in TABLES:
            op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')

def downgrade():
    # 과거 버전으로 돌아가더라도 서버 전용 데이터의 접근 보호는 유지한다.
    pass
