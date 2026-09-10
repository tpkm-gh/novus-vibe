from app import repository
from app.models import RequestStatus


def test_create_and_get_request(db_session):
    record = repository.create_request(
        db_session, label="Q3 screen", source_url="https://example.com/funds"
    )
    assert record.id.startswith("REQ-")
    assert record.status == RequestStatus.PENDING.value
    assert record.attempt_log == []

    fetched = repository.get_request(db_session, record.id)
    assert fetched is not None
    assert fetched.label == "Q3 screen"


def test_get_request_missing_returns_none(db_session):
    assert repository.get_request(db_session, "REQ-doesnotexist") is None


def test_list_requests_orders_newest_first(db_session):
    first = repository.create_request(db_session, label="first", source_url="https://example.com/a")
    second = repository.create_request(db_session, label="second", source_url="https://example.com/b")

    rows = repository.list_requests(db_session)
    assert [r.id for r in rows] == [second.id, first.id]


def test_append_attempt_accumulates(db_session):
    record = repository.create_request(db_session, label="x", source_url="https://example.com/a")
    record = repository.append_attempt(db_session, record, {"attempt": 1, "action": "generate", "detail": "ok"})
    record = repository.append_attempt(db_session, record, {"attempt": 2, "action": "reflect", "detail": "pass"})
    assert len(record.attempt_log) == 2
    assert record.attempt_log[0]["action"] == "generate"
    assert record.attempt_log[1]["action"] == "reflect"


def test_mark_completed_sets_completed_at(db_session):
    record = repository.create_request(db_session, label="x", source_url="https://example.com/a")
    assert record.completed_at is None
    record = repository.mark_completed(db_session, record, status=RequestStatus.SUCCEEDED.value)
    assert record.completed_at is not None
    assert record.status == RequestStatus.SUCCEEDED.value


def test_compute_stats_empty(db_session):
    stats = repository.compute_stats(db_session)
    assert stats["total_requests"] == 0
    assert stats["success_rate_pct"] == 0.0
    assert stats["avg_latency_ms"] is None


def test_compute_stats_mixed(db_session):
    a = repository.create_request(db_session, label="a", source_url="https://example.com/a")
    repository.mark_completed(db_session, a, status=RequestStatus.SUCCEEDED.value, retry_count=0, latency_ms=100.0)

    b = repository.create_request(db_session, label="b", source_url="https://example.com/b")
    repository.mark_completed(db_session, b, status=RequestStatus.FAILED.value, retry_count=2, latency_ms=50.0)

    stats = repository.compute_stats(db_session)
    assert stats["total_requests"] == 2
    assert stats["succeeded"] == 1
    assert stats["failed"] == 1
    assert stats["success_rate_pct"] == 50.0
    assert stats["avg_retry_count"] == 1.0
    assert stats["avg_latency_ms"] == 75.0
