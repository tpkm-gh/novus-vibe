"""Deterministic, fully offline stand-in for the Adobe PDF Services call.

Three things this provider does, on purpose:

1. Recognizes a handful of `simulate-*` keywords in the URL so the eval
   harness (tests/test_eval_scenarios.py) can exercise the DocGen agent's
   retry/reflect logic deterministically, with no network at all -- the
   same trick the WealthOS prototype used to keep its eval suite
   non-flaky against a live model.
2. For anything else, makes a best-effort real HTTP fetch of the page and
   renders its visible text into an actual multi-page PDF, so a demo
   against a real fund-listing URL still produces a real, relevant-looking
   document -- not a canned placeholder -- with zero Adobe account needed.
3. Falls back to synthetic fund-listing content if the fetch fails for any
   reason (network unreachable in a sandboxed environment, page blocks
   bots, etc.) so the mock provider itself never raises for an ordinary
   valid URL -- only the `simulate-*` hooks and PermanentProviderError-
   worthy cases (checked upstream by url_validation) do.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from io import BytesIO

import httpx
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .base import GenerationOutcome, PermanentProviderError, TransientProviderError

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


class AdobeMockProvider:
    name = "mock"

    def __init__(self, fetch_fn=None):
        # Injectable for tests; defaults to a real (best-effort) HTTP GET.
        self._fetch_fn = fetch_fn or self._http_fetch

    # ---- public interface -------------------------------------------------

    def generate(self, url: str, *, attempt: int) -> GenerationOutcome:
        lower = url.lower()

        if "simulate-timeout" in lower and attempt == 1:
            raise TransientProviderError(
                "Mock: simulated timeout contacting source page (attempt 1)"
            )
        if "simulate-permanent-fail" in lower:
            raise PermanentProviderError("Mock: simulated DNS resolution failure, host not found")
        if "simulate-thin-content" in lower:
            lines = ["(No funds matched the current screen criteria.)"]
            return self._render(url, title="Fund Screen Snapshot", lines=lines)

        lines = self._fetch_fn(url) or self._synthetic_fund_listing(url)
        return self._render(url, title="Fund Screen Snapshot", lines=lines)

    def retrieve(self, asset_id: str) -> bytes | None:
        # The mock provider never holds a second copy anywhere -- by
        # design, the app's own persisted file is the only copy. Returning
        # None here forces callers onto that path, which is also what a
        # real Adobe asset does once its retention window has passed.
        return None

    # ---- helpers ------------------------------------------------------

    def _http_fetch(self, url: str) -> list[str] | None:
        try:
            resp = httpx.get(url, timeout=6.0, follow_redirects=True, headers={
                "User-Agent": "novus-vibe-fund-screen-copilot/0.1 (+demo)"
            })
            resp.raise_for_status()
        except Exception:
            return None

        text = _TAG_RE.sub(" ", resp.text)
        text = _WS_RE.sub(" ", text)
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        return lines[:200] if lines else None

    # Deterministic on purpose (not randomized) -- this is what the mock
    # provider renders whenever a real fetch of `url` isn't possible (no
    # network in this sandbox, or a site that blocks bots), and its output
    # feeds size/page-count thresholds that tests and the eval harness
    # assert exact verdicts against. Random content length would make those
    # assertions flaky for no benefit.
    _SYNTHETIC_FUNDS = [
        ("NVFX", "Novus Growth Equity Fund", "Large-Cap Growth", "14.2%"),
        ("NVBD", "Novus Core Bond Fund", "Intermediate Bond", "3.1%"),
        ("NVIX", "Novus International Equity Fund", "Foreign Large Blend", "9.8%"),
        ("NVSC", "Novus Small-Cap Value Fund", "Small-Cap Value", "11.6%"),
        ("NVDV", "Novus Dividend Income Fund", "Equity Income", "7.4%"),
        ("NVEM", "Novus Emerging Markets Fund", "Diversified Emerging Mkts", "5.9%"),
        ("NVRE", "Novus Real Estate Fund", "Real Estate", "6.2%"),
        ("NVHY", "Novus High Yield Bond Fund", "High Yield Bond", "4.8%"),
        ("NVTX", "Novus Technology Sector Fund", "Technology", "22.1%"),
        ("NVBL", "Novus Balanced Allocation Fund", "Moderate Allocation", "8.0%"),
        ("NVMM", "Novus Money Market Fund", "Money Market", "4.9%"),
        ("NVIN", "Novus Infrastructure Fund", "Infrastructure", "8.7%"),
        ("NVHC", "Novus Healthcare Sector Fund", "Health", "13.5%"),
        ("NVES", "Novus ESG Equity Fund", "Large Blend", "10.1%"),
        ("NVSH", "Novus Short-Term Bond Fund", "Short-Term Bond", "3.6%"),
        ("NVGL", "Novus Global Allocation Fund", "World Allocation", "7.7%"),
    ]

    def _synthetic_fund_listing(self, url: str) -> list[str]:
        lines = [
            "(Live fetch of the source page was not possible from this environment --",
            " rendering synthetic fallback content so the pipeline stays demoable.)",
            f"Source URL: {url}",
            "",
            "Ticker   Fund Name                          Category                    1Y Return",
            "-" * 82,
        ]
        for ticker, name, category, ret in self._SYNTHETIC_FUNDS:
            lines.append(f"{ticker:<8} {name:<35} {category:<27} {ret:>8}")
        lines.append("-" * 82)
        lines.append(f"{len(self._SYNTHETIC_FUNDS)} funds matched the screen criteria.")
        return lines

    def _render(self, url: str, *, title: str, lines: list[str]) -> GenerationOutcome:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, 6, f"Source: {url}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.multi_cell(
            0,
            6,
            f"Generated: {datetime.now(timezone.utc).isoformat()} (mock provider)",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(4)
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("Courier", "", 9)
        for line in lines:
            safe = line.encode("latin-1", "replace").decode("latin-1") or " "
            pdf.multi_cell(0, 5, safe, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        buf = BytesIO()
        pdf.output(buf)
        pdf_bytes = bytes(buf.getvalue())

        return GenerationOutcome(
            pdf_bytes=pdf_bytes,
            provider_name=self.name,
            asset_id=f"mock-asset-{secrets.token_hex(6)}",
            job_location=None,
        )
