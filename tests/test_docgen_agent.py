"""Unit tests for the DocGen agent's plan -> act -> observe -> reflect loop.

Each test pins one specific path through that loop using the mock
provider's `simulate-*` keyword hooks (see app/agents/providers/adobe_mock.py)
so the assertions are exact and never flaky.
"""
from app import repository
from app.models import RequestStatus


def _run(db_session, docgen_agent, url, label="test"):
    record = repository.create_request(db_session, label=label, source_url=url)
    return docgen_agent.run(db_session, record)


def test_happy_path_succeeds_on_first_attempt(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://example.com/funds")
    assert record.status == RequestStatus.SUCCEEDED.value
    assert record.reflection_verdict == "pass"
    assert record.retry_count == 0
    assert record.local_pdf_path is not None
    assert record.page_count == 1
    assert len(record.attempt_log) == 1  # one reflect entry, no retries


def test_transient_error_then_success_is_retried_and_recorded(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://example.com/funds?simulate-timeout=1")
    assert record.status == RequestStatus.SUCCEEDED.value
    assert record.retry_count == 1
    verdicts = [a["verdict"] for a in record.attempt_log]
    assert verdicts == ["retry", "pass"]


def test_permanent_error_fails_fast_without_retrying(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://example.com/funds?simulate-permanent-fail=1")
    assert record.status == RequestStatus.FAILED.value
    assert record.retry_count == 0
    assert "DNS resolution failure" in record.error_message
    assert len(record.attempt_log) == 1
    assert record.attempt_log[0]["verdict"] == "permanent_fail"


def test_thin_content_is_flagged_for_review_not_silently_passed(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://example.com/funds?simulate-thin-content=1")
    assert record.status == RequestStatus.NEEDS_REVIEW.value
    assert record.reflection_verdict == "needs_review"
    # A flagged doc is still persisted -- an advisor needs to be able to look at it.
    assert record.local_pdf_path is not None


def test_invalid_scheme_is_rejected_before_any_provider_call(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "http://example.com/funds")
    assert record.status == RequestStatus.FAILED.value
    assert "https" in record.error_message
    assert record.attempt_log[0]["action"] == "plan"
    assert record.local_pdf_path is None


def test_private_ip_literal_is_rejected(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://127.0.0.1/funds")
    assert record.status == RequestStatus.FAILED.value
    assert "non-routable" in record.error_message


def test_retrieve_returns_persisted_bytes(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "https://example.com/funds")
    pdf_bytes = docgen_agent.retrieve(record)
    assert pdf_bytes is not None
    assert pdf_bytes.startswith(b"%PDF")


def test_retrieve_returns_none_when_nothing_was_ever_generated(db_session, docgen_agent):
    record = _run(db_session, docgen_agent, "http://example.com/funds")  # rejected at PLAN
    assert docgen_agent.retrieve(record) is None
