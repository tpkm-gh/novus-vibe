"""Provider abstraction for "turn this webpage URL into a PDF".

Same pattern the WealthOS prototype used for its write-up step, applied
here to the Adobe call: one interface, two implementations, a deterministic
one that never depends on network/credentials and a live one that does.
The DocGen agent (app/agents/docgen_agent.py) only ever talks to this
interface -- it does not know or care which provider is behind it.

TransientProviderError vs PermanentProviderError is the signal the agent's
reflect/retry loop keys off: transient means "try again, maybe with
different params"; permanent means "stop now, this will never succeed"
(e.g. the URL doesn't resolve, or isn't HTTPS).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TransientProviderError(Exception):
    """Retryable: timeouts, rate limits, momentary service hiccups."""


class PermanentProviderError(Exception):
    """Not retryable: bad URL, disallowed host, invalid credentials."""


@dataclass
class GenerationOutcome:
    pdf_bytes: bytes
    provider_name: str
    asset_id: str
    job_location: str | None = None


class PDFProvider(Protocol):
    name: str

    def generate(self, url: str, *, attempt: int) -> GenerationOutcome:
        """Convert `url` to a PDF. `attempt` (1-based) lets a provider vary
        its behavior on retry, e.g. drop a param that caused a prior failure."""
        ...

    def retrieve(self, asset_id: str) -> bytes | None:
        """Best-effort re-fetch from the provider's own storage. May return
        None -- callers should treat the app's own persisted copy
        (ScreenRequest.local_pdf_path) as the real system of record; see
        docs/PLAYBOOK.md, "Decisions worth defending" #2."""
        ...
