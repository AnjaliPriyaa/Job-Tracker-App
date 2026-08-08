"""
SSRF / URL security — validate URLs before any HTTP request.

The LLM may provide URLs to tools like fetch_job or search_ats.
This module ensures only safe, public URLs are accessed.
"""

import ipaddress
import re
from urllib.parse import urlparse


def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate a URL is safe to fetch. Returns (is_safe, reason).

    Allowed: public http/https URLs
    Blocked: localhost, private IPs, loopback, link-local, non-http schemes
    """
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL"

    url = url.strip()

    # Scheme check
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported scheme: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname in URL"

    # Hostname blocklist
    hostname_lower = hostname.lower()

    # Localhost variants
    if hostname_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, f"Blocked: localhost ({hostname})"

    # Internal hostnames
    blocked_domains = (
        "local", "internal", "corp", "localhost.localdomain",
        ".local", ".internal",
    )
    for bd in blocked_domains:
        if hostname_lower == bd or hostname_lower.endswith(bd):
            return False, f"Blocked: internal hostname ({hostname})"

    # Try parsing as IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback:
            return False, f"Blocked: loopback address ({hostname})"
        if ip.is_private:
            return False, f"Blocked: private IP ({hostname})"
        if ip.is_link_local:
            return False, f"Blocked: link-local IP ({hostname})"
        if ip.is_multicast:
            return False, f"Blocked: multicast IP ({hostname})"
        if ip.is_reserved:
            return False, f"Blocked: reserved IP ({hostname})"
    except ValueError:
        pass  # Not an IP address, hostname — OK

    return True, "OK"
