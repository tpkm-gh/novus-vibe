"""Agent 2: the dashboard controller agent.

Its whole job is fetching request/response state from Postgres (via the
repository layer) and shaping it into view-models the UI can render
directly -- it never talks to the Adobe provider or the reflection layer,
and it never mutates a ScreenRequest. That asymmetry with DocGenAgent is
deliberate: see docs/PLAYBOOK.md, "Why only one of the two agents 'reasons'".
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import repository
from ..models import ScreenRequest


class ControllerAgent:
    def list_summaries(self, db: Session, *, limit: int = 100) -> list[dict]:
        return [self._to_summary(r) for r in repository.list_requests(db, limit=limit)]

    def get_detail(self, db: Session, request_id: str) -> dict | None:
        record = repository.get_request(db, request_id)
        if record is None:
            return None
        return self._to_detail(record)

    def get_stats(self, db: Session) -> dict:
        return repository.compute_stats(db)

    # ---- shaping -----------------------------------------------------

    def _to_summary(self, r: ScreenRequest) -> dict:
        return {
            "id": r.id,
            "label": r.label,
            "source_url": r.source_url,
            "status": r.status,
            "reflection_verdict": r.reflection_verdict,
            "retry_count": r.retry_count,
            "file_size_bytes": r.file_size_bytes,
            "page_count": r.page_count,
            "requested_at": r.requested_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }

    def _to_detail(self, r: ScreenRequest) -> dict:
        summary = self._to_summary(r)
        summary.update(
            {
                "provider_name": r.provider_name,
                "adobe_asset_id": r.adobe_asset_id,
                "reflection_notes": r.reflection_notes,
                "attempt_log": r.attempt_log or [],
                "error_message": r.error_message,
                "latency_ms": r.latency_ms,
                "download_url": f"/api/screen-requests/{r.id}/download" if r.local_pdf_path else None,
            }
        )
        return summary
