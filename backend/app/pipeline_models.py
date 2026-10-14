"""Small, persistent relational warehouse marts for inspectable data processing."""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class PipelineRefreshRun(Base):
    __tablename__ = 'pipeline_refresh_run'
    id: Mapped[int] = mapped_column(primary_key=True)
    data_kind: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    input_count: Mapped[int] = mapped_column()
    aggregate_count: Mapped[int] = mapped_column()
    rule_count: Mapped[int] = mapped_column()
    actor_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class OpportunitySummary(Base):
    __tablename__ = 'dws_opportunity_summary'
    data_kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('pipeline_refresh_run.id'))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(40))
    summary: Mapped[dict] = mapped_column(JSON)
    aggregates: Mapped[dict] = mapped_column(JSON)
    lineage: Mapped[dict] = mapped_column(JSON)
    mining: Mapped[dict] = mapped_column(JSON)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SkillAssociation(Base):
    __tablename__ = 'ads_skill_association'
    __table_args__ = (UniqueConstraint('data_kind', 'antecedent', 'consequent', name='uq_ads_kind_skill_pair'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    data_kind: Mapped[str] = mapped_column(String(20), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('pipeline_refresh_run.id'))
    antecedent: Mapped[str] = mapped_column(String(100))
    consequent: Mapped[str] = mapped_column(String(100))
    pair_count: Mapped[int] = mapped_column()
    antecedent_count: Mapped[int] = mapped_column()
    population: Mapped[int] = mapped_column()
    support: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
