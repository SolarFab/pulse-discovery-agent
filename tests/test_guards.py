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


def test_robots_fetch_does_not_follow_redirects(monkeypatch):
    """The one hole in the wall: with follow_redirects=True, httpx chased the
    Location header itself and no IP re-check ran, so a robots.txt answering
    `302 -> http://169.254.169.254/` made this process issue that request."""
    monkeypatch.setattr(guards.socket, "getaddrinfo",
                        _fake_resolver({"venue.example": "93.184.216.34"}))
    calls = []

    class Resp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        text = ""

    def fake_get(url, **kw):
        calls.append((url, kw.get("follow_redirects")))
        return Resp()

    monkeypatch.setattr(guards.httpx, "get", fake_get)
    s = FetchSession()
    # a robots.txt we decline to chase counts as absent, i.e. allowed
    assert s._robots_ok("https://venue.example/programm", "venue.example")
    assert calls == [("https://venue.example/robots.txt", False)]


def _redirecting_client(monkeypatch, target):
    """venue.example/tickets -> `target`, everything else 200 text/html."""
    class Resp:
        def __init__(self, code, loc=None):
            self.status_code = code
            self.headers = {"location": loc} if loc else {"content-type": "text/html"}
            self.content = b"<html>ok</html>"
            self.text = "<html>ok</html>"

        def raise_for_status(self):
            pass

    def fake_get(url, **_kw):
        return Resp(302, target) if url == "https://venue.example/tickets" else Resp(200)

    monkeypatch.setattr(guards.httpx, "get", fake_get)
    monkeypatch.setattr(guards.socket, "getaddrinfo", _fake_resolver({
        "venue.example": "93.184.216.34",
        "elsewhere.example": "93.184.216.34",
    }))


def test_cross_host_redirect_pays_the_full_toll(monkeypatch):
    """Only the IP check used to run per hop, so a 30x onto another domain got in
    past the budget, robots.txt and politeness — and, never being recorded, that
    domain counted as fresh again on the next direct fetch."""
    _redirecting_client(monkeypatch, "https://elsewhere.example/programm")
    asked = []
    s = FetchSession()
    s._robots_ok = lambda url, host: asked.append(host) or True
    s.guarded_fetch("https://venue.example/tickets")
    assert asked == ["venue.example", "elsewhere.example"]      # robots asked per host
    assert s.domains == {"venue.example", "elsewhere.example"}  # both spend budget
    assert "elsewhere.example" in s.last_hit                    # politeness clock set


def test_cross_host_redirect_cannot_exceed_domain_budget(monkeypatch):
    _redirecting_client(monkeypatch, "https://elsewhere.example/programm")
    s = FetchSession()
    s._robots_ok = lambda url, host: True
    s.domains = {"a.example", "b.example"}  # venue.example is the 3rd, elsewhere a 4th
    with pytest.raises(FetchRefused, match="domain budget"):
        s.guarded_fetch("https://venue.example/tickets")


def test_redirect_to_robots_disallowed_path_is_refused(monkeypatch):
    _redirecting_client(monkeypatch, "https://elsewhere.example/private")
    s = FetchSession()
    s._robots_ok = lambda url, host: not url.endswith("/private")
    with pytest.raises(FetchRefused, match="robots.txt disallows"):
        s.guarded_fetch("https://venue.example/tickets")


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
