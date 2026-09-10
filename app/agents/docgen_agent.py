"""Agent 1: the Adobe PDF API client agent.

Given a request already persisted by the Controller/API layer, this agent
owns the whole plan -> act -> observe -> reflect -> (retry|finish) loop for
turning a fund-listing webpage URL into a stored PDF, plus a separate
`retrieve()` path for handing back a previously generated document.

This is intentionally the one place in the app that is genuinely agentic in
the ReAct sense (it plans, acts via a tool, observes the result, reflects
on whether that result is acceptable, and decides whether to act again) --
see docs/PLAYBOOK.md, "Why only one of the two agents 'reasons'".
"""
from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy.orm import Session

from .. import repository
from ..config import settings
from ..models import RequestStatus, ScreenRequest
from .providers import PermanentProviderError, TransientProviderError, get_provider
from .reflection import ReflectionVerdict, get_reflection_provider
from .url_validation import InvalidSourceUrlError, validate_source_url


class DocGenAgent:
    def __init__(self, provider_name: str | None = None, reflection_name: str | None = None):
        self.provider = get_provider(provider_name or settings.pdf_provider)
        self.reflector = get_reflection_provider(reflection_name or settings.reflection_provider)
        self.max_retries = settings.max_generation_retries

    # ---- generation ----------------------------------------------------

    def run(self, db: Session, record: ScreenRequest) -> ScreenRequest:
        """Executes the full loop for one request and returns the updated record."""
        start = time.perf_counter()
        record = repository.update_request(db, record, status=RequestStatus.IN_PROGRESS.value)

        # PLAN: validate before spending a single provider call on a URL
        # that can never succeed.
        try:
            validate_source_url(record.source_url)
        except InvalidSourceUrlError as exc:
            record = repository.append_attempt(
                db, record, {"attempt": 0, "action": "plan", "detail": str(exc), "verdict": "rejected"}
            )
            return self._finish_failed(db, record, error=str(exc), start=start)

        attempt = 0
        last_error = ""
        while attempt < self.max_retries + 1:
            attempt += 1

            # ACT
            try:
                outcome = self.provider.generate(record.source_url, attempt=attempt)
            except TransientProviderError as exc:
                last_error = str(exc)
                record = repository.append_attempt(
                    db,
                    record,
                    {"attempt": attempt, "action": "generate", "detail": last_error, "verdict": "retry"},
                )
                continue  # OBSERVE/REFLECT is moot with no output; loop to next attempt
            except PermanentProviderError as exc:
                last_error = str(exc)
                record = repository.append_attempt(
                    db,
                    record,
                    {"attempt": attempt, "action": "generate", "detail": last_error, "verdict": "permanent_fail"},
                )
                return self._finish_failed(db, record, error=last_error, start=start, retry_count=attempt - 1)

            # OBSERVE + REFLECT
            reflection = self.reflector.review(outcome, source_url=record.source_url)
            record = repository.append_attempt(
                db,
                record,
                {
                    "attempt": attempt,
                    "action": "reflect",
                    "detail": reflection.notes,
                    "verdict": reflection.verdict.value,
                },
            )

            if reflection.verdict == ReflectionVerdict.FAIL and attempt <= self.max_retries:
                last_error = reflection.notes
                continue  # discard this attempt's output, try again

            # Either PASS, NEEDS_REVIEW, or FAIL-with-no-retries-left: persist
            # what we have (even a flagged doc is useful for a human to see)
            # and stop.
            local_path = self._persist(record.id, outcome.pdf_bytes)
            latency_ms = round((time.perf_counter() - start) * 1000, 1)

            final_status = {
                ReflectionVerdict.PASS: RequestStatus.SUCCEEDED,
                ReflectionVerdict.NEEDS_REVIEW: RequestStatus.NEEDS_REVIEW,
                ReflectionVerdict.FAIL: RequestStatus.FAILED,
            }[reflection.verdict]

            return repository.mark_completed(
                db,
                record,
                status=final_status.value,
                provider_name=outcome.provider_name,
                adobe_asset_id=outcome.asset_id,
                adobe_job_location=outcome.job_location,
                local_pdf_path=str(local_path),
                file_size_bytes=len(outcome.pdf_bytes),
                page_count=reflection.page_count,
                reflection_verdict=reflection.verdict.value,
                reflection_notes=reflection.notes,
                retry_count=attempt - 1,
                latency_ms=latency_ms,
                error_message=None if reflection.verdict != ReflectionVerdict.FAIL else reflection.notes,
            )

        # Exhausted all retries on FAIL verdicts.
        return self._finish_failed(db, record, error=last_error, start=start, retry_count=self.max_retries)

    def _finish_failed(
        self, db: Session, record: ScreenRequest, *, error: str, start: float, retry_count: int = 0
    ) -> ScreenRequest:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return repository.mark_completed(
            db,
            record,
            status=RequestStatus.FAILED.value,
            retry_count=retry_count,
            error_message=error,
            latency_ms=latency_ms,
        )

    def _persist(self, request_id: str, pdf_bytes: bytes) -> Path:
        target = settings.storage_path / f"{request_id}.pdf"
        target.write_bytes(pdf_bytes)
        return target

    # ---- retrieval -------------------------------------------------------

    def retrieve(self, record: ScreenRequest) -> bytes | None:
        """Prior-document retrieval. Our own persisted copy is always the
        system of record (see docs/PLAYBOOK.md, "Decisions worth defending"
        #2) -- we only fall back to asking the provider if that copy is
        somehow missing, and even then, don't expect it to work."""
        if record.local_pdf_path:
            path = Path(record.local_pdf_path)
            if path.exists():
                return path.read_bytes()

        if record.adobe_asset_id:
            return self.provider.retrieve(record.adobe_asset_id)

        return None
