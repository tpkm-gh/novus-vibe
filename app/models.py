"""The one table this app needs: a fund-screen PDF request/response record.

Every field here exists because some part of the pipeline (rules_engine-style
validation, the DocGen agent's reflect/retry loop, or the Controller agent's
dashboard views) reads or writes it. Nothing speculative.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ScreenRequest(Base):
    """One 'screen this fund listing page and give me a PDF' request."""

    __tablename__ = "screen_requests"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=RequestStatus.PENDING.value)

    # What the DocGen agent actually did, for the audit trail.
    provider_name: Mapped[str] = mapped_column(String(20), default="")
    adobe_asset_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    adobe_job_location: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Our own persisted copy. See docs/PLAYBOOK.md "Decisions worth
    # defending" #2 for why we never rely on Adobe's asset URL as the
    # system of record for retrieval.
    local_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Reflection / eval trail.
    reflection_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reflection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    attempt_log: Mapped[list] = mapped_column(JSON, default=list)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
