"""End-to-end tests through the real FastAPI app (routing, dependency
injection, response schemas) -- not just the agents/repository directly.
Uses the app's own default sqlite-fallback DB (a single shared engine, like
production), rows wiped between tests for isolation via the ORM rather than
deleting the underlying file -- SQLite doesn't tolerate its file being
unlinked out from under an already-open connection pool. Forces the global
DocGen agent onto a no-network mock provider so this suite passes
identically online or offline."""
import pytest
from fastapi.testclient import TestClient

from app.agents.providers.adobe_mock import AdobeMockProvider
from app.db import get_session
from app.main import app, docgen_agent
from app.models import ScreenRequest


@pytest.fixture(autouse=True)
def _isolated_db_and_offline_provider():
    docgen_agent.provider = AdobeMockProvider(fetch_fn=lambda url: None)
    yield
    db = get_session()
    try:
        db.query(ScreenRequest).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Fund Screen PDF Copilot" in resp.text


def test_create_list_get_download_roundtrip(client):
    created = client.post(
        "/api/screen-requests",
        json={"label": "API test", "source_url": "https://example.com/funds"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "succeeded"
    assert body["download_url"] is not None
    request_id = body["id"]

    listed = client.get("/api/screen-requests")
    assert listed.status_code == 200
    assert any(r["id"] == request_id for r in listed.json())

    detail = client.get(f"/api/screen-requests/{request_id}")
    assert detail.status_code == 200
    assert detail.json()["label"] == "API test"

    download = client.get(f"/api/screen-requests/{request_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")


def test_get_unknown_request_is_404(client):
    resp = client.get("/api/screen-requests/REQ-doesnotexist")
    assert resp.status_code == 404


def test_download_unknown_request_is_404(client):
    resp = client.get("/api/screen-requests/REQ-doesnotexist/download")
    assert resp.status_code == 404


def test_invalid_url_is_rejected_by_pydantic_before_reaching_the_agent(client):
    resp = client.post("/api/screen-requests", json={"label": "bad", "source_url": "not-a-url"})
    assert resp.status_code == 422


def test_stats_reflect_created_requests(client):
    client.post("/api/screen-requests", json={"label": "a", "source_url": "https://example.com/funds"})
    stats = client.get("/api/stats").json()
    assert stats["total_requests"] == 1
    assert stats["succeeded"] == 1
