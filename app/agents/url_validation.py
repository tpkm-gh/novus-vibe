"""Shared URL validation, used by the DocGen agent's PLAN step before any
provider is ever called.

Mirrors Adobe PDF Services' own documented constraint for HTML-to-PDF-from-URL
("URL scheme must be HTTPS; hostname must not resolve to a non-routable IP")
plus a basic literal-IP check to block the obvious SSRF cases (localhost,
RFC1918 ranges, link-local).

Named limitation, not hidden: this does NOT do DNS resolution + re-check
(so it won't catch DNS-rebinding, where a public hostname resolves to a
private IP only at request time). A production version needs that --
see docs/PLAYBOOK.md, "Limitations & restrictions".
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class InvalidSourceUrlError(ValueError):
    pass


_BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0"}


def validate_source_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise InvalidSourceUrlError(f"URL must use https:// (got {parsed.scheme!r})")

    hostname = parsed.hostname or ""
    if not hostname:
        raise InvalidSourceUrlError("URL has no hostname")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise InvalidSourceUrlError(f"Host {hostname!r} is not a valid fund-listing source")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None  # it's a domain name, not a literal IP -- fine

    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise InvalidSourceUrlError(f"Host {hostname!r} resolves to a non-routable address")

    return url
