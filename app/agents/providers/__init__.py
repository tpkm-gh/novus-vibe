from .base import GenerationOutcome, PDFProvider, PermanentProviderError, TransientProviderError
from .adobe_live import AdobeLiveProvider
from .adobe_mock import AdobeMockProvider


def get_provider(name: str) -> PDFProvider:
    if name == "live":
        return AdobeLiveProvider()
    return AdobeMockProvider()


__all__ = [
    "GenerationOutcome",
    "PDFProvider",
    "PermanentProviderError",
    "TransientProviderError",
    "AdobeLiveProvider",
    "AdobeMockProvider",
    "get_provider",
]
