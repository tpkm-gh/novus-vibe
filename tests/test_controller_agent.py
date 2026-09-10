"""Unit tests for the Controller agent -- it only ever reads what the
DocGen agent already wrote, so these tests seed the DB directly through
the repository layer rather than running full generations."""
from app import repository
from app.models import RequestStatus


def test_list_summaries_shape(db_session, controller_agent):
    repository.create_request(db_session, label="a", source_url="https://example.com/a")
    summaries = controller_agent.list_summaries(db_session)
    assert len(summaries) == 1
    row = summaries[0]
    assert set(row.keys()) == {
        "id", "label", "source_url", "status", "reflection_verdict", "retry_count",
        "file_size_bytes", "page_count", "requested_at", "completed_at",
    }


def test_get_detail_includes_attempt_log_and_download_url(db_session, controller_agent):
    record = repository.create_request(db_session, label="a", source_url="https://example.com/a")
    record = repository.append_attempt(db_session, record, {"attempt": 1, "action": "generate", "detail": "ok"})
    record = repository.mark_completed(
        db_session, record, status=RequestStatus.SUCCEEDED.value, local_pdf_path="/tmp/x.pdf"
    )

    detail = controller_agent.get_detail(db_session, record.id)
    assert detail["attempt_log"] == [{"attempt": 1, "action": "generate", "detail": "ok"}]
    assert detail["download_url"] == f"/api/screen-requests/{record.id}/download"


def test_get_detail_no_download_url_when_nothing_persisted(db_session, controller_agent):
    record = repository.create_request(db_session, label="a", source_url="https://example.com/a")
    detail = controller_agent.get_detail(db_session, record.id)
    assert detail["download_url"] is None


def test_get_detail_missing_returns_none(db_session, controller_agent):
    assert controller_agent.get_detail(db_session, "REQ-nope") is None


def test_get_stats_delegates_to_repository(db_session, controller_agent):
    repository.create_request(db_session, label="a", source_url="https://example.com/a")
    stats = controller_agent.get_stats(db_session)
    assert stats["total_requests"] == 1
