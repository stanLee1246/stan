"""Raw public-document provenance and repeatable crawl runs."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class CrawlRun(Base):
    __tablename__ = 'crawl_run'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(30), default='running')
    data_kind: Mapped[str] = mapped_column(String(20), default='public')
    requested_limit: Mapped[int] = mapped_column(default=5)
    accepted: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    imported_by: Mapped[int] = mapped_column(ForeignKey('app_user.id'))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RawCrawlDocument(Base):
    __tablename__ = 'raw_crawl_document'
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('crawl_run.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(60))
    source_url: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(150), default='')
    raw_content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(40), default='hengyang-notice-v1')
    parsed_status: Mapped[str] = mapped_column(String(30), default='requirements_review')
    parsed_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey('fact_opportunity_snapshot.id'))
    data_kind: Mapped[str] = mapped_column(String(20), default='public')
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)
