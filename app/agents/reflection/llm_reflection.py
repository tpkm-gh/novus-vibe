"""Optional live-model upgrade to the reflection step.

Deliberately layered, not standalone: this always runs the deterministic
RuleBasedReflectionProvider first as a hard structural gate (valid PDF,
non-zero pages, size floor). The model is only ever asked to look at
output that already passed that gate, and it can only *downgrade*
PASS -> NEEDS_REVIEW (e.g. "this rendered but the visible content doesn't
look like a fund listing") -- it can never override a structural FAIL, and
it can never turn a FAIL into a PASS. Same guardrail philosophy as the
WealthOS prototype's rules-engine/model split: the model adds judgment
about *content quality*, it does not get to invent or erase a verdict the
deterministic layer already reached.

Requires ANTHROPIC_API_KEY. If the call errors or times out, falls back to
the rule-based verdict rather than failing the whole request -- a flaky
reflection critique should never be why a generation job is lost.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from ..providers.base import GenerationOutcome
from .base import ReflectionOutcome, ReflectionVerdict
from .rule_based import RuleBasedReflectionProvider
from ...config import settings

_MAX_EXCERPT_CHARS = 2000


class LLMReflectionProvider:
    name = "llm"

    def __init__(self):
        self._structural = RuleBasedReflectionProvider()

    def review(self, outcome: GenerationOutcome, *, source_url: str) -> ReflectionOutcome:
        structural = self._structural.review(outcome, source_url=source_url)
        if structural.verdict != ReflectionVerdict.PASS:
            return structural  # LLM never gets a vote on a structural fail/flag

        if not settings.anthropic_api_key:
            return ReflectionOutcome(
                verdict=structural.verdict,
                notes=structural.notes + " (ANTHROPIC_API_KEY not set -- skipped LLM critique.)",
                page_count=structural.page_count,
            )

        try:
            excerpt = self._extract_excerpt(outcome.pdf_bytes)
            verdict, critique = self._critique(source_url, excerpt)
        except Exception as exc:  # noqa: BLE001 - reflection must never crash the pipeline
            return ReflectionOutcome(
                verdict=structural.verdict,
                notes=structural.notes + f" (LLM critique unavailable: {exc})",
                page_count=structural.page_count,
            )

        if verdict == "needs_review":
            return ReflectionOutcome(
                verdict=ReflectionVerdict.NEEDS_REVIEW,
                notes=f"{structural.notes} | LLM critique flagged it: {critique}",
                page_count=structural.page_count,
            )

        return ReflectionOutcome(
            verdict=ReflectionVerdict.PASS,
            notes=f"{structural.notes} | LLM critique: {critique}",
            page_count=structural.page_count,
        )

    def _extract_excerpt(self, pdf_bytes: bytes) -> str:
        reader = PdfReader(BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages[:3]:
            text += (page.extract_text() or "") + "\n"
            if len(text) >= _MAX_EXCERPT_CHARS:
                break
        return text[:_MAX_EXCERPT_CHARS]

    def _critique(self, source_url: str, excerpt: str) -> tuple[str, str]:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            "You are reviewing an automatically-generated PDF snapshot of a fund "
            "screening/listing webpage, produced for an advisor's compliance file. "
            f"Source URL: {source_url}\n\n"
            f"Extracted text from the first page(s):\n---\n{excerpt}\n---\n\n"
            "Does this look like a genuine fund listing/screening page (tickers, "
            "fund names, categories, returns, or similar)? Reply with exactly one "
            "line in the form: VERDICT: <pass|needs_review> | REASON: <one sentence>. "
            "Use needs_review only if the content clearly does NOT look like fund "
            "data (e.g. an error page, a login wall, unrelated content)."
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        verdict = "needs_review" if "needs_review" in text.lower() else "pass"
        return verdict, text
