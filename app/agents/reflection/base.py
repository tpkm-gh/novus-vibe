"""Reflection = the DocGen agent's self-review step. It runs *after* a
provider has already produced PDF bytes for a given attempt, and decides
whether that output is good enough to hand to the advisor, needs a human
to look at it, or should be discarded and retried.

Same provider-abstraction shape as app/agents/providers/base.py, and for
the same reason: the deterministic implementation is what makes the eval
suite reproducible, and it's always available; a live-LLM implementation
is an optional upgrade, not a requirement to run the app at all.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from ..providers.base import GenerationOutcome


class ReflectionVerdict(str, enum.Enum):
    PASS = "pass"
    NEEDS_REVIEW = "needs_review"
    FAIL = "fail"


@dataclass
class ReflectionOutcome:
    verdict: ReflectionVerdict
    notes: str
    page_count: int | None = None


class ReflectionProvider(Protocol):
    name: str

    def review(self, outcome: GenerationOutcome, *, source_url: str) -> ReflectionOutcome: ...
