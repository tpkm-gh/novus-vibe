"""Shared fixtures.

Every fixture here that touches the DocGen agent forces the mock provider's
`fetch_fn` to a no-op (returns None) so tests exercise the deterministic
synthetic-fallback / `simulate-*` paths only -- never a real HTTP call.
That's what keeps this suite fast and identical in CI, on a laptop with no
network, and on a laptop with full internet access.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import ControllerAgent, DocGenAgent
from app.agents.providers.adobe_mock import AdobeMockProvider
from app.db import Base


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def docgen_agent(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    agent = DocGenAgent(provider_name="mock", reflection_name="rule_based")
    agent.provider = AdobeMockProvider(fetch_fn=lambda url: None)
    return agent


@pytest.fixture()
def controller_agent():
    return ControllerAgent()
