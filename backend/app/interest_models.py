"""Private activity-interest answers and presentation preferences.

Import this module when building Alembic's Base.metadata. External survey
records deliberately have no account mapping.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class InterestResponse(Base):
    __tablename__ = 'interest_response'
    __table_args__ = (
        UniqueConstraint('source_name', 'data_kind', 'response_key', name='uq_interest_source_kind_response'),
        Index('ix_interest_owner_created', 'owner_user_id', 'created_at'),
        Index('ix_interest_source_kind', 'source_name', 'data_kind'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey('app_user.id', ondelete='CASCADE'))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey('dim_student_profile.id'))
    profile_version: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(120))
    data_kind: Mapped[str] = mapped_column(String(20))
    response_key: Mapped[str] = mapped_column(String(100))
    student_key: Mapped[str | None] = mapped_column(String(64))
    instrument_version: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str] = mapped_column(String(40))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey('ingestion_batch.id'))
    answer_hash: Mapped[str] = mapped_column(String(64))
    raw_record: Mapped[dict] = mapped_column(JSON)
    normalized_record: Mapped[dict] = mapped_column(JSON)
    scores: Mapped[dict] = mapped_column(JSON)
    coverage: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40))
    primary_role: Mapped[str | None] = mapped_column(String(1))
    secondary_role: Mapped[str | None] = mapped_column(String(1))
    reasons: Mapped[list] = mapped_column(JSON)
    actions: Mapped[list] = mapped_column(JSON)
    consent: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RoleDisplay(Base):
    __tablename__ = 'profile_role_display'
    user_id: Mapped[int] = mapped_column(ForeignKey('app_user.id', ondelete='CASCADE'), primary_key=True)
    display_role: Mapped[str | None] = mapped_column(String(1))
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
