"""Pydantic request/response shapes for the API layer. Kept separate from
the SQLAlchemy models (app/models.py) so the DB schema can evolve without
breaking the API contract, and vice versa."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class ScreenRequestCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=200, examples=["Q3 large-cap growth screen"])
    source_url: HttpUrl = Field(..., examples=["https://example.com/funds/large-cap-growth"])


class AttemptLogEntry(BaseModel):
    attempt: int
    action: str
    detail: str
    verdict: str | None = None


class ScreenRequestSummary(BaseModel):
    id: str
    label: str
    source_url: str
    status: str
    reflection_verdict: str | None
    retry_count: int
    file_size_bytes: int | None
    page_count: int | None
    requested_at: str
    completed_at: str | None


class ScreenRequestDetail(ScreenRequestSummary):
    provider_name: str
    adobe_asset_id: str | None
    reflection_notes: str | None
    attempt_log: list[dict]
    error_message: str | None
    latency_ms: float | None
    download_url: str | None


class DashboardStats(BaseModel):
    total_requests: int
    succeeded: int
    needs_review: int
    failed: int
    in_progress: int
    success_rate_pct: float
    avg_retry_count: float
    avg_latency_ms: float | None
