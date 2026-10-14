"""Versioned, explicitly unverified school aggregates supplied by the project owner."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class SchoolDataset(Base):
    __tablename__ = 'raw_school_dataset'
    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(40))
    exported_at: Mapped[str] = mapped_column(String(40))
    verification_status: Mapped[str] = mapped_column(String(30), default='unverified')
    provenance: Mapped[dict] = mapped_column(JSON)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    quality: Mapped[dict] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class UniversitySnapshot(Base):
    __tablename__ = 'dim_university_snapshot'
    __table_args__ = (UniqueConstraint('dataset_id', 'name', name='uq_school_dataset_university'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('raw_school_dataset.id', ondelete='CASCADE'), index=True)
    source_order: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(40))
    institution_type: Mapped[str] = mapped_column(String(40))
    district: Mapped[str] = mapped_column(String(40))
    students: Mapped[int]
    staff: Mapped[int]
    founded_year: Mapped[int]
    dataset_focus: Mapped[bool]
    description: Mapped[str] = mapped_column(Text)


class UniversityMajorSnapshot(Base):
    __tablename__ = 'fact_university_major_snapshot'
    __table_args__ = (UniqueConstraint('dataset_id', 'name', 'level', name='uq_school_dataset_major_level'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('raw_school_dataset.id', ondelete='CASCADE'), index=True)
    university_id: Mapped[int] = mapped_column(ForeignKey('dim_university_snapshot.id', ondelete='CASCADE'))
    source_order: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    discipline: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(20))
    students: Mapped[int]
    # Preserve percentages exactly as printed; they are not verified outcome facts.
    reported_student_share: Mapped[str] = mapped_column(String(20))
    reported_employment_rate: Mapped[str] = mapped_column(String(20))
