"""URL security / SSRF protection tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.url_security import validate_url


def test_valid_public_url():
    safe, reason = validate_url("https://www.linkedin.com/jobs/view/123")
    assert safe, f"Should allow public URL: {reason}"
    safe, reason = validate_url("https://boards.greenhouse.io/airbnb")
    assert safe, f"Should allow ATS URL: {reason}"
    safe, reason = validate_url("http://example.com/jobs")
    assert safe, f"Should allow http: {reason}"


def test_localhost():
    safe, reason = validate_url("http://localhost:8080")
    assert not safe, f"Should block localhost: {reason}"
    safe, _ = validate_url("http://127.0.0.1/admin")
    assert not safe
    safe, _ = validate_url("http://[::1]:8080")
    assert not safe
    safe, _ = validate_url("http://0.0.0.0/test")
    assert not safe


def test_private_ip():
    safe, _ = validate_url("http://192.168.1.1/admin")
    assert not safe
    safe, _ = validate_url("http://10.0.0.1/secret")
    assert not safe
    safe, _ = validate_url("http://172.16.0.1/internal")
    assert not safe


def test_link_local():
    safe, _ = validate_url("http://169.254.1.1/meta")
    assert not safe


def test_unsupported_scheme():
    safe, reason = validate_url("ftp://example.com/file")
    assert not safe, f"Should block ftp: {reason}"
    safe, _ = validate_url("file:///etc/passwd")
    assert not safe
    safe, _ = validate_url("javascript:alert(1)")
    assert not safe


def test_empty_invalid():
    safe, _ = validate_url("")
    assert not safe
    safe, _ = validate_url("not-a-url")
    assert not safe
    safe, _ = validate_url(None)
    assert not safe
