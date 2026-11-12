"""기존 파일 자료와 카카오 API에서 확인한 식당 기본정보를 구분한다."""
from alembic import op
import sqlalchemy as sa

revision='0004_basic_source'
down_revision='0003_detail_sources'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('restaurant',sa.Column('basic_source',sa.String(30),nullable=True))

def downgrade():
    with op.batch_alter_table('restaurant') as batch:
        batch.drop_column('basic_source')
