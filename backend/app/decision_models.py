"""Persisted decision evidence and independently editable action progress."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class DecisionRun(Base):
    __tablename__ = 'fact_decision_run'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('dim_student_profile.id'))
    profile_version: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(60), default='observed-decision-v1')
    data_kind: Mapped[str] = mapped_column(String(20))
    # Exact request and selection limit are retained for reproducibility.
    configuration: Mapped[dict] = mapped_column(JSON)
    # Once created, this evidence snapshot is never modified by action updates.
    results: Mapped[dict] = mapped_column(JSON)
    action_states: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
