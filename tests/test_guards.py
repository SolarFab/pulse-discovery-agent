"""SSRF wall tests — no live network: DNS + HTTP are monkeypatched."""

import pytest

from discovery_agent import guards
from discovery_agent.guards import FetchRefused, FetchSession, check_url


def _fake_resolver(mapping):
    def fake_getaddrinfo(host, *_a, **_k):
        ip = mapping.get(host)
        if ip is None:
            raise OSError("no dns")
        return [(2, 1, 6, "", (ip, 0))]
    return fake_getaddrinfo


def test_http_scheme_refused():
    with pytest.raises(FetchRefused, match="only https"):
        check_url("http://example.com/events")


def test_private_and_metadata_ips_refused(monkeypatch):
    monkeypatch.setattr(guards.socket, "getaddrinfo", _fake_resolver({
        "internal.example": "10.0.0.5",
        "metadata.example": "169.254.169.254",
        "localhost.example": "127.0.0.1",
    }))
    for host in ("internal.example", "metadata.example", "localhost.example"):
        with pytest.raises(FetchRefused, match="non-public"):
            check_url(f"https://{host}/x")


def test_public_ip_allowed(monkeypatch):
    monkeypatch.setattr(guards.socket, "getaddrinfo",
                        _fake_resolver({"venue.example": "93.184.216.34"}))
    assert check_url("https://venue.example/programm") == "venue.example"


def test_domain_budget(monkeypatch):
    monkeypatch.setattr(guards.socket, "getaddrinfo", _fake_resolver(
        {f"d{i}.example": "93.184.216.34" for i in range(5)}))
    s = FetchSession()
    s.domains = {"d0.example", "d1.example", "d2.example"}
    with pytest.raises(FetchRefused, match="domain budget"):
        s.guarded_fetch("https://d3.example/")


def test_redirect_to_private_refused(monkeypatch):
    monkeypatch.setattr(guards.socket, "getaddrinfo", _fake_resolver({
        "venue.example": "93.184.216.34",
        "internal.example": "10.1.2.3",
    }))

    class FakeResp:
        status_code = 302
        headers = {"location": "https://internal.example/secrets"}
        content = b""
        text = ""

    monkeypatch.setattr(guards.httpx, "get", lambda *a, **k: FakeResp())
    s = FetchSession()
    s._robots_ok = lambda url, host: True  # isolate the redirect check
    with pytest.raises(FetchRefused, match="non-public"):
        s.guarded_fetch("https://venue.example/linktree")
