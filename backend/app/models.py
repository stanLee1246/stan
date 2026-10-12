from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import LONGTEXT

from .database import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'app_user'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    nickname: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(20), default='student')
    profile_revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LoginSession(Base):
    __tablename__ = 'login_session'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('app_user.id', ondelete='CASCADE'))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Profile(Base):
    __tablename__ = 'dim_student_profile'
    __table_args__ = (UniqueConstraint('user_id', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    version: Mapped[int] = mapped_column(Integer)
    major: Mapped[str] = mapped_column(String(100))
    graduation_year: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(30))
    degree: Mapped[str] = mapped_column(String(30), default='bachelor')
    english: Mapped[str | None] = mapped_column(String(30))
    internship_months: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text, default='')
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=now)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    tags: Mapped[list['ProfileTag']] = relationship(cascade='all, delete-orphan', lazy='selectin')


class ProfileTag(Base):
    __tablename__ = 'bridge_profile_tag'
    __table_args__ = (UniqueConstraint('profile_id', 'kind', 'value'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('dim_student_profile.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[str] = mapped_column(String(20), default='self_report')


class Opportunity(Base):
    __tablename__ = 'fact_opportunity_snapshot'
    __table_args__ = (UniqueConstraint('source_url', 'source_record_id', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(String(150))
    organization: Mapped[str] = mapped_column(String(150))
    path: Mapped[str] = mapped_column(String(30), index=True)
    organization_type: Mapped[str] = mapped_column(String(30), default='other')
    city: Mapped[str | None] = mapped_column(String(80))
    skills: Mapped[list] = mapped_column(JSON, default=list)
    majors: Mapped[list] = mapped_column(JSON, default=list)
    minimum_degree: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    deadline: Mapped[object | None] = mapped_column(Date)
    published_at: Mapped[object | None] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(String(255))
    data_kind: Mapped[str] = mapped_column(String(20), default='demo')
    requirements_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class IngestionBatch(Base):
    __tablename__ = 'ingestion_batch'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(120))
    data_kind: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    cleaning_version: Mapped[str] = mapped_column(String(30), default='outcome-v1')
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    imported_by: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Outcome(Base):
    __tablename__ = 'fact_outcome_snapshot'
    __table_args__ = (
        UniqueConstraint('source_name', 'student_key', 'observed_on'),
        Index('ix_outcome_kind_major_year', 'data_kind', 'major', 'graduation_year'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_key: Mapped[str] = mapped_column(String(64))
    major: Mapped[str] = mapped_column(String(100))
    graduation_year: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(30))
    city: Mapped[str | None] = mapped_column(String(80))
    observed_on: Mapped[object] = mapped_column(Date)
    confirmation_status: Mapped[str] = mapped_column(String(30))
    source_name: Mapped[str] = mapped_column(String(120))
    source_record_id: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(String(255))
    data_kind: Mapped[str] = mapped_column(String(20))
    batch_id: Mapped[int] = mapped_column(ForeignKey('ingestion_batch.id'))


class Recommendation(Base):
    __tablename__ = 'fact_recommendation_exposure'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    profile_id: Mapped[int] = mapped_column(ForeignKey('dim_student_profile.id'))
    profile_version: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(60), default='observed-rule-v1')
    data_kind: Mapped[str] = mapped_column(String(20))
    results: Mapped[list] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Experience(Base):
    __tablename__ = 'experience_post'
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    public_nickname: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text)
    graduation_year: Mapped[int] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(80))
    path: Mapped[str] = mapped_column(String(30))
    public_consent: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    moderation_note: Mapped[str] = mapped_column(String(300), default='')
    data_kind: Mapped[str] = mapped_column(String(20), default='self_report')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditEvent(Base):
    __tablename__ = 'audit_event'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
