"""The eval harness: one table of end-to-end scenarios covering every
terminal state the DocGen agent's reflect/retry loop can reach, asserted
together so the *range* of behavior is visible in one place rather than
scattered across unit tests.

Deliberately mirrors the WealthOS prototype's eval suite: a tool that only
ever reports success is exactly as untrustworthy for an operator dashboard
as one that only ever reports failure. This table exists so a reviewer can
see, at a glance, that PASS / RETRY-then-PASS / FAIL-fast / NEEDS_REVIEW /
input-rejected are all real, exercised, distinguishable outcomes -- not
just a status enum that's never actually reached in the non-happy states.
"""
from __future__ import annotations

import pytest

from app import repository

SCENARIOS = [
    pytest.param(
        "https://example.com/funds",
        "succeeded", "pass", 0,
        id="clean-listing-passes-first-try",
    ),
    pytest.param(
        "https://example.com/funds?simulate-timeout=1",
        "succeeded", "pass", 1,
        id="transient-timeout-recovers-on-retry",
    ),
    pytest.param(
        "https://example.com/funds?simulate-permanent-fail=1",
        "failed", None, 0,
        id="permanent-provider-error-fails-fast-no-retry",
    ),
    pytest.param(
        "https://example.com/funds?simulate-thin-content=1",
        "needs_review", "needs_review", 0,
        id="thin-content-flagged-not-silently-passed-or-blindly-retried",
    ),
    pytest.param(
        "http://example.com/funds",
        "failed", None, 0,
        id="non-https-url-rejected-before-any-provider-call",
    ),
]


@pytest.mark.parametrize("url,expected_status,expected_verdict,expected_retries", SCENARIOS)
def test_scenario(db_session, docgen_agent, url, expected_status, expected_verdict, expected_retries):
    record = repository.create_request(db_session, label="eval", source_url=url)
    record = docgen_agent.run(db_session, record)

    assert record.status == expected_status, record.attempt_log
    assert record.reflection_verdict == expected_verdict
    assert record.retry_count == expected_retries


def test_scenario_table_covers_every_terminal_status():
    """Guards against the eval table silently losing coverage of a status
    if RequestStatus grows a new value without a matching scenario."""
    from app.models import RequestStatus

    covered = {"succeeded", "needs_review", "failed"}
    all_terminal = {
        s.value for s in RequestStatus if s not in (RequestStatus.PENDING, RequestStatus.IN_PROGRESS)
    }
    assert covered == all_terminal
