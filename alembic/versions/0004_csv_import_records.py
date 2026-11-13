"""CSV review metadata, exclusively in Lunchrun."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0004_csv_import_records'
down_revision = '0003_db_first_schema'
branch_labels = depends_on = None


def upgrade():
    op.create_table('csv_import_record',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('batch_id', sa.String(64), nullable=False),
        sa.Column('record_kind', sa.String(40), nullable=False),
        sa.Column('record_key', sa.Text(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        schema='Lunchrun')
    op.execute('ALTER TABLE "Lunchrun".csv_import_record ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON "Lunchrun".csv_import_record FROM anon, authenticated')


def downgrade():
    raise RuntimeError('Import review records must be preserved; explicit reverse migration required.')
