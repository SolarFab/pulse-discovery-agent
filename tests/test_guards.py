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


def test_http_redirect_hop_is_followed_but_never_read(monkeypatch):
    """apex -> http://www -> https://www is extremely common. The middle hop may be
    followed (its IP is still checked); content is only ever read over https."""
    monkeypatch.setattr(guards.socket, "getaddrinfo", _fake_resolver({
        "venue.example": "93.184.216.34",
        "www.venue.example": "93.184.216.34",
    }))
    hops = ["http://www.venue.example/", "https://www.venue.example/"]

    class Resp:
        def __init__(self, code, loc=None):
            self.status_code = code
            self.headers = {"location": loc} if loc else {"content-type": "text/html"}
            self.content = b"<html>ok</html>"
            self.text = "<html>ok</html>"

        def raise_for_status(self):
            pass

    seen = []

    def fake_get(url, **_kw):
        seen.append(url)
        if url == "https://venue.example/":
            return Resp(301, hops[0])
        if url == hops[0]:
            return Resp(301, hops[1])
        return Resp(200)

    monkeypatch.setattr(guards.httpx, "get", fake_get)
    s = FetchSession()
    s._robots_ok = lambda url, host: True
    resp = s.guarded_fetch("https://venue.example/")
    assert resp.status_code == 200
    assert seen[-1].startswith("https://")   # content read over https only


def test_http_final_response_is_refused(monkeypatch):
    """A redirect chain that ENDS on http must not have its content read."""
    monkeypatch.setattr(guards.socket, "getaddrinfo",
                        _fake_resolver({"venue.example": "93.184.216.34"}))

    class Resp:
        def __init__(self, code, loc=None):
            self.status_code = code
            self.headers = {"location": loc} if loc else {"content-type": "text/html"}
            self.content = b"x"
            self.text = "x"

        def raise_for_status(self):
            pass

    def fake_get(url, **_kw):
        if url == "https://venue.example/":
            return Resp(301, "http://venue.example/insecure")
        return Resp(200)

    monkeypatch.setattr(guards.httpx, "get", fake_get)
    s = FetchSession()
    s._robots_ok = lambda url, host: True
    with pytest.raises(FetchRefused, match="refusing to read content"):
        s.guarded_fetch("https://venue.example/")
