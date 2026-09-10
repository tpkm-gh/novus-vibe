"""Deterministic reflection: structural + content-depth checks, no model call.

This is the default and, per docs/PLAYBOOK.md, the recommended steady-state
choice even when an LLM key is available -- it's what lets the eval suite
assert exact verdicts without flaking against sampling variance. See
`LLMReflectionProvider` for the optional richer critique layered on top.

Deliberately measures *extracted text content*, not raw PDF byte size, to
decide whether a document looks "thin". Byte size is a poor proxy -- fonts,
compression, and embedded structure dominate it far more than visible
content does, so two structurally-valid PDFs with wildly different amounts
of real content can be nearly the same size. Extracted character count is
what actually tracks "did this page have anything on it."
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..providers.base import GenerationOutcome
from .base import ReflectionOutcome, ReflectionVerdict

_BLANK_CONTENT_CHARS = 40
_THIN_CONTENT_CHARS = 300


class RuleBasedReflectionProvider:
    name = "rule_based"

    def review(self, outcome: GenerationOutcome, *, source_url: str) -> ReflectionOutcome:
        pdf_bytes = outcome.pdf_bytes

        if not pdf_bytes.startswith(b"%PDF"):
            return ReflectionOutcome(
                verdict=ReflectionVerdict.FAIL,
                notes="Output does not start with a %PDF header -- not a valid PDF file.",
            )

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            page_count = len(reader.pages)
            content_chars = sum(len((p.extract_text() or "").strip()) for p in reader.pages)
        except PdfReadError as exc:
            return ReflectionOutcome(
                verdict=ReflectionVerdict.FAIL,
                notes=f"PDF failed to parse structurally: {exc}",
            )

        if page_count == 0:
            return ReflectionOutcome(
                verdict=ReflectionVerdict.FAIL,
                notes="Parsed PDF has zero pages.",
                page_count=0,
            )

        if content_chars < _BLANK_CONTENT_CHARS:
            return ReflectionOutcome(
                verdict=ReflectionVerdict.NEEDS_REVIEW,
                notes=(
                    f"Only {content_chars} extracted character(s) across {page_count} page(s) "
                    "-- looks blank (source page may not have rendered, or the screen "
                    "returned no results). Flagged for advisor review rather than "
                    "auto-retried, since a repeat generation of the same URL would "
                    "likely produce the same result."
                ),
                page_count=page_count,
            )

        if content_chars < _THIN_CONTENT_CHARS and page_count == 1:
            return ReflectionOutcome(
                verdict=ReflectionVerdict.NEEDS_REVIEW,
                notes=(
                    f"{content_chars} extracted characters on a single page -- thinner "
                    "than a typical fund listing snapshot. Not necessarily wrong (a "
                    "tightly filtered screen can legitimately return one fund), so "
                    "flagged rather than failed."
                ),
                page_count=page_count,
            )

        return ReflectionOutcome(
            verdict=ReflectionVerdict.PASS,
            notes=(
                f"{page_count} page(s), {content_chars} extracted characters, "
                f"{len(pdf_bytes)} bytes. Structurally valid, content depth in expected range."
            ),
            page_count=page_count,
        )
