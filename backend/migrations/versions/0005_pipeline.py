"""Persist opportunity summaries, skill association rules and refresh lineage."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('pipeline_refresh_run',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('data_kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('source_fingerprint', sa.String(64), nullable=False),
        sa.Column('input_count', sa.Integer(), nullable=False),
        sa.Column('aggregate_count', sa.Integer(), nullable=False),
        sa.Column('rule_count', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('app_user.id'), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=False))
    op.create_index('ix_pipeline_refresh_run_data_kind', 'pipeline_refresh_run', ['data_kind'])
    op.create_table('dws_opportunity_summary',
        sa.Column('data_kind', sa.String(20), primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('pipeline_refresh_run.id'), nullable=False),
        sa.Column('source_fingerprint', sa.String(64), nullable=False),
        sa.Column('algorithm_version', sa.String(40), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('aggregates', sa.JSON(), nullable=False),
        sa.Column('lineage', sa.JSON(), nullable=False),
        sa.Column('mining', sa.JSON(), nullable=False),
        sa.Column('refreshed_at', sa.DateTime(), nullable=False))
    op.create_table('ads_skill_association',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('data_kind', sa.String(20), nullable=False),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('pipeline_refresh_run.id'), nullable=False),
        sa.Column('antecedent', sa.String(100), nullable=False),
        sa.Column('consequent', sa.String(100), nullable=False),
        sa.Column('pair_count', sa.Integer(), nullable=False),
        sa.Column('antecedent_count', sa.Integer(), nullable=False),
        sa.Column('population', sa.Integer(), nullable=False),
        sa.Column('support', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.UniqueConstraint('data_kind', 'antecedent', 'consequent', name='uq_ads_kind_skill_pair'))
    op.create_index('ix_ads_skill_association_data_kind', 'ads_skill_association', ['data_kind'])


def downgrade():
    op.drop_table('ads_skill_association')
    op.drop_table('dws_opportunity_summary')
    op.drop_table('pipeline_refresh_run')
