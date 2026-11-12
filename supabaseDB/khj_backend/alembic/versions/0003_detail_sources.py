"""항목별 수집 출처와 확인일을 보관한다."""
from alembic import op
import sqlalchemy as sa

revision = '0003_detail_sources'
down_revision = '0002_catalog_food_types'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('place_detail_status', sa.Column('menu_source_url',sa.String(1000),nullable=True))
    op.add_column('place_detail_status', sa.Column('hours_source_url',sa.String(1000),nullable=True))
    op.add_column('place_detail_status', sa.Column('menu_checked_at',sa.DateTime(timezone=True),nullable=True))
    op.add_column('place_detail_status', sa.Column('hours_checked_at',sa.DateTime(timezone=True),nullable=True))

def downgrade():
    with op.batch_alter_table('place_detail_status') as batch:
        for name in ['hours_checked_at','menu_checked_at','hours_source_url','menu_source_url']:
            batch.drop_column(name)
