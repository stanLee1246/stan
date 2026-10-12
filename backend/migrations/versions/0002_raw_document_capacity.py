"""Preserve original CSV batches up to the API's allowed size on MySQL."""
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'mysql':
        op.alter_column('ingestion_batch', 'raw_content', existing_type=sa.Text(), type_=LONGTEXT(), existing_nullable=False)


def downgrade():
    if op.get_bind().dialect.name == 'mysql':
        raise RuntimeError('Downgrade refused: narrowing raw_content could truncate preserved documents. Export and review data first.')
