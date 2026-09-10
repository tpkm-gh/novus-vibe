"""CRUD layer. Every DB read/write in the app goes through here -- neither
agent touches SQLAlchemy sessions directly. That seam is what lets
tests swap in a throwaway SQLite session and what would let a future
version swap Postgres for something else without touching agent code.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RequestStatus, ScreenRequest


def new_request_id() -> str:
    return f"REQ-{secrets.token_hex(4)}"


def create_request(db: Session, *, label: str, source_url: str) -> ScreenRequest:
    record = ScreenRequest(
        id=new_request_id(),
        label=label,
        source_url=source_url,
        status=RequestStatus.PENDING.value,
        attempt_log=[],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_request(db: Session, request_id: str) -> ScreenRequest | None:
    return db.get(ScreenRequest, request_id)


def list_requests(db: Session, *, limit: int = 100) -> list[ScreenRequest]:
    stmt = select(ScreenRequest).order_by(ScreenRequest.requested_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def update_request(db: Session, record: ScreenRequest, **fields) -> ScreenRequest:
    for key, value in fields.items():
        setattr(record, key, value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def append_attempt(db: Session, record: ScreenRequest, entry: dict) -> ScreenRequest:
    log = list(record.attempt_log or [])
    log.append(entry)
    return update_request(db, record, attempt_log=log)


def mark_completed(db: Session, record: ScreenRequest, **fields) -> ScreenRequest:
    fields.setdefault("completed_at", datetime.now(timezone.utc))
    return update_request(db, record, **fields)


def compute_stats(db: Session) -> dict:
    rows = list(db.scalars(select(ScreenRequest)).all())
    total = len(rows)
    if total == 0:
        return {
            "total_requests": 0,
            "succeeded": 0,
            "needs_review": 0,
            "failed": 0,
            "in_progress": 0,
            "success_rate_pct": 0.0,
            "avg_retry_count": 0.0,
            "avg_latency_ms": None,
        }

    def count(status: RequestStatus) -> int:
        return sum(1 for r in rows if r.status == status.value)

    succeeded = count(RequestStatus.SUCCEEDED)
    needs_review = count(RequestStatus.NEEDS_REVIEW)
    failed = count(RequestStatus.FAILED)
    in_progress = count(RequestStatus.IN_PROGRESS) + count(RequestStatus.PENDING)

    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]

    return {
        "total_requests": total,
        "succeeded": succeeded,
        "needs_review": needs_review,
        "failed": failed,
        "in_progress": in_progress,
        "success_rate_pct": round(100 * succeeded / total, 1),
        "avg_retry_count": round(sum(r.retry_count for r in rows) / total, 2),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }
