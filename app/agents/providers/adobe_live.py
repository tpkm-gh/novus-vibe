"""Live Adobe PDF Services provider: real HTML-to-PDF-from-URL calls via the
official `pdfservices-sdk` (OAuth Server-to-Server / ServicePrincipalCredentials).

*** Verify before a live demo ***
This is written against the module layout and class names Adobe documents
and ships in its own `pdfservices-python-sdk-samples` repo as of Sept 2026
(see docs/PLAYBOOK.md, "Assumptions" -- sources linked there). Adobe has
changed this SDK's package layout across major versions before. Before
relying on this path in front of an interviewer:

    pip show pdfservices-sdk
    python -c "from adobe.pdfservices.operation.pdfjobs.jobs.html_to_pdf_job import HTMLToPDFJob"

If that import fails, open the installed package and fix the import paths
below -- the rest of this file (retry classification, output handling)
does not need to change.

This module is only imported when PDF_PROVIDER=live; the app never touches
it in the default (mock) configuration, so a stale SDK here cannot break
the demo path.
"""
from __future__ import annotations

import secrets

from .base import GenerationOutcome, PermanentProviderError, TransientProviderError
from ...config import settings


class AdobeLiveProvider:
    name = "live"

    def __init__(self):
        if not settings.pdf_services_client_id or not settings.pdf_services_client_secret:
            raise PermanentProviderError(
                "PDF_PROVIDER=live but PDF_SERVICES_CLIENT_ID / "
                "PDF_SERVICES_CLIENT_SECRET are not set. Get free-tier "
                "credentials at https://developer.adobe.com/document-services/"
                "docs/overview/pdf-services-api/gettingstarted/ (500 free "
                "document transactions/month) and put them in .env."
            )

    def generate(self, url: str, *, attempt: int) -> GenerationOutcome:
        try:
            from adobe.pdfservices.operation.auth.service_principal_credentials import (
                ServicePrincipalCredentials,
            )
            from adobe.pdfservices.operation.exception.exceptions import (
                SdkException,
                ServiceApiException,
                ServiceUsageException,
            )
            from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
            from adobe.pdfservices.operation.pdf_services import PDFServices
            from adobe.pdfservices.operation.pdfjobs.jobs.html_to_pdf_job import HTMLtoPDFJob
            from adobe.pdfservices.operation.pdfjobs.params.html_to_pdf.html_to_pdf_params import (
                HTMLtoPDFParams,
            )
            from adobe.pdfservices.operation.pdfjobs.result.html_to_pdf_result import (
                HTMLtoPDFResult,
            )
        except ImportError as exc:  # pragma: no cover - exercised only with PDF_PROVIDER=live
            raise PermanentProviderError(
                f"pdfservices-sdk import failed ({exc}). The SDK's module layout "
                "may have changed -- see the module docstring in "
                "app/agents/providers/adobe_live.py for how to fix this."
            ) from exc

        try:
            credentials = ServicePrincipalCredentials(
                client_id=settings.pdf_services_client_id,
                client_secret=settings.pdf_services_client_secret,
            )
            pdf_services = PDFServices(credentials=credentials)

            params = HTMLtoPDFParams(include_header_footer=True)
            job = HTMLtoPDFJob(input_url=url, html_to_pdf_params=params)

            location = pdf_services.submit(job)
            response = pdf_services.get_job_result(location, HTMLtoPDFResult)

            result_asset: CloudAsset = response.get_result().get_asset()
            stream = pdf_services.get_content(result_asset)
            pdf_bytes = stream.get_input_stream()

            return GenerationOutcome(
                pdf_bytes=pdf_bytes,
                provider_name=self.name,
                asset_id=result_asset.get_asset_id() or f"adobe-{secrets.token_hex(6)}",
                job_location=str(location),
            )

        except ServiceUsageException as exc:
            # Free-tier quota (500 transactions/month) exhausted, or plan limit hit.
            raise PermanentProviderError(f"Adobe usage limit reached: {exc}") from exc
        except ServiceApiException as exc:
            # Adobe validated the request and rejected it (bad URL, disallowed
            # host, malformed HTML at that URL) -- retrying won't help.
            raise PermanentProviderError(f"Adobe API rejected the request: {exc}") from exc
        except SdkException as exc:
            # Network hiccup, timeout, transient 5xx from Adobe -- worth a retry.
            raise TransientProviderError(f"Adobe SDK/network error: {exc}") from exc

    def retrieve(self, asset_id: str) -> bytes | None:
        # Adobe does not document a retention SLA for generated assets, and
        # the SDK's Asset handle isn't meaningfully re-resolvable from a bare
        # string ID after the originating job's process has ended. We treat
        # this as "not retrievable from Adobe" unconditionally and rely on
        # our own persisted copy -- see docs/PLAYBOOK.md, "Decisions worth
        # defending" #2. A production integration that needs re-download
        # from Adobe's side would need to keep the job's Asset object (or a
        # presigned external-asset URL) alive, not just an ID string.
        return None
