"""Provenance and normalized university/major aggregates from the supplied export."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('raw_school_dataset',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('file_name', sa.String(200), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=False, unique=True),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.String(40), nullable=False),
        sa.Column('exported_at', sa.String(40), nullable=False),
        sa.Column('verification_status', sa.String(30), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('quality', sa.JSON(), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
    )
    op.create_table('dim_university_snapshot',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('raw_school_dataset.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('city', sa.String(40), nullable=False),
        sa.Column('institution_type', sa.String(40), nullable=False),
        sa.Column('district', sa.String(40), nullable=False),
        sa.Column('students', sa.Integer(), nullable=False),
        sa.Column('staff', sa.Integer(), nullable=False),
        sa.Column('founded_year', sa.Integer(), nullable=False),
        sa.Column('dataset_focus', sa.Boolean(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.UniqueConstraint('dataset_id', 'name', name='uq_school_dataset_university'),
    )
    op.create_index('ix_dim_university_snapshot_dataset_id', 'dim_university_snapshot', ['dataset_id'])
    op.create_table('fact_university_major_snapshot',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('raw_school_dataset.id', ondelete='CASCADE'), nullable=False),
        sa.Column('university_id', sa.Integer(), sa.ForeignKey('dim_university_snapshot.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('discipline', sa.String(40), nullable=False),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('students', sa.Integer(), nullable=False),
        sa.Column('reported_student_share', sa.String(20), nullable=False),
        sa.Column('reported_employment_rate', sa.String(20), nullable=False),
        sa.UniqueConstraint('dataset_id', 'name', 'level', name='uq_school_dataset_major_level'),
    )
    op.create_index('ix_fact_university_major_snapshot_dataset_id', 'fact_university_major_snapshot', ['dataset_id'])


def downgrade():
    op.drop_table('fact_university_major_snapshot')
    op.drop_table('dim_university_snapshot')
    op.drop_table('raw_school_dataset')
