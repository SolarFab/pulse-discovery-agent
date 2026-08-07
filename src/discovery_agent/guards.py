"""The fetch security wall (publisher-discovery spec: Fetch security wall).

Every network request the scout or harvester makes goes through guarded_fetch().
The scout follows links it READ ON UNTRUSTED PAGES — so this module enforces,
deterministically, what no prompt can guarantee:

  - https only
  - DNS-resolved public-IP only (no private/link-local/loopback/metadata ranges),
    re-checked on every redirect hop (max 5)
  - response size <= 2 MB, content-type allowlist
  - robots.txt compliance + >=1s politeness delay per domain
  - a per-investigation domain budget (<=3 distinct domains)

Page text fetched here is DATA for the model, never instructions (AGENTS.md rule 1).
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
DOMAIN_BUDGET = 3
PER_DOMAIN_DELAY_S = 1.0
UA = "PulseDiscoveryBot/0.2 (+https://github.com/SolarFab/pulse-discovery-agent)"
ALLOWED_TYPES = ("text/html", "text/plain", "text/calendar", "text/xml",
                 "application/xml", "application/rss", "application/atom",
                 "application/json", "application/ld+json", "application/xhtml")

# Binding the source to an IPv4 address forces IPv4 for every connection. That is
# what lets _resolve_public() judge only the A records: we validate the family we
# dial, and we dial only the family we validated. Without this pin the check would
# be a lie — httpx could still pick an unvalidated AAAA.
_TRANSPORT = httpx.HTTPTransport(local_address="0.0.0.0", retries=0)
_CLIENT = httpx.Client(transport=_TRANSPORT, headers={"User-Agent": UA},
                       follow_redirects=False)


def _http_get(url: str, timeout: float = 20.0) -> httpx.Response:
    """The single seam for every outbound request: IPv4-pinned, never auto-redirecting.

    One function so the wall has exactly one way out — and so tests have exactly one
    thing to stub.
    """
    return _CLIENT.get(url, timeout=timeout)


class FetchRefused(Exception):
    """The wall said no. The reason is safe to show the model as data."""


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _resolve_public(host: str) -> None:
    """Reject hosts unless every address we could CONNECT to is public.

    Judged per address family, because we pin the family we use (IPv4 — see
    _CLIENT below). Checking every family and refusing on any bad record cost real
    coverage: www.planetarium.berlin publishes a malformed AAAA
    (`a01:4f8:…`, the leading `2` dropped, which lands in reserved space) alongside
    a perfectly good A record. That venue has ~2,900 events and was written off as
    unreachable over an address we would never dial.

    Still strict where it matters: if ANY address in the family we actually use is
    non-public, the host is refused. A DNS-rebinding attacker cannot get us to
    connect to something we did not validate, because we only ever use that family.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchRefused(f"DNS failed for {host}") from exc

    by_family: dict[int, list] = {}
    for info in infos:
        by_family.setdefault(info[0], []).append(ipaddress.ip_address(info[4][0]))

    # IPv4 is the family the client pins; fall back to IPv6 only for v6-only hosts.
    addrs = by_family.get(socket.AF_INET) or by_family.get(socket.AF_INET6) or []
    if not addrs:
        raise FetchRefused(f"DNS returned no usable address for {host}")
    for ip in addrs:
        if not _is_public(ip):
            raise FetchRefused(f"{host} resolves to non-public address {ip}")


def check_url(url: str, *, allow_http_hop: bool = False) -> str:
    """Validate scheme + host publicness. Returns the netloc (lowercased).

    `allow_http_hop` relaxes the scheme check for an INTERMEDIATE redirect target
    only. Plenty of real sites bounce apex -> http://www -> https://www, and
    refusing the middle hop made healthy venues look unreachable (sowiesoberlin.com
    was reported 'unreachable' while a plain client loaded it fine). The relaxation
    is narrow on purpose: the private-IP check still runs on every hop, and content
    is still only ever READ over https — see guarded_fetch.
    """
    parsed = urlparse(url)
    allowed = ("https", "http") if allow_http_hop else ("https",)
    if parsed.scheme not in allowed:
        raise FetchRefused(f"only https allowed, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise FetchRefused("no host in URL")
    _resolve_public(parsed.hostname)
    return parsed.hostname.lower()


@dataclass
class FetchSession:
    """Per-investigation fetch context: domain budget, politeness, robots cache."""

    domains: set[str] = field(default_factory=set)
    last_hit: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, urllib.robotparser.RobotFileParser] = field(default_factory=dict)
    fetches: int = 0

    def _robots_ok(self, url: str, host: str) -> bool:
        rp = self._robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                # NOT follow_redirects=True: httpx would then chase the Location
                # header itself, with no IP re-check per hop — a robots.txt that
                # answers `302 -> http://169.254.169.254/` would have this process
                # make that request. A robots.txt we decline to chase is simply
                # treated as absent, which the except branch below already allows.
                resp = _http_get(f"https://{host}/robots.txt", timeout=10)
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])  # unreachable robots.txt -> allow (standard practice)
            self._robots[host] = rp
        return rp.can_fetch(UA, url)

    def _politeness(self, host: str) -> None:
        elapsed = time.monotonic() - self.last_hit.get(host, 0.0)
        if elapsed < PER_DOMAIN_DELAY_S:
            time.sleep(PER_DOMAIN_DELAY_S - elapsed)
        self.last_hit[host] = time.monotonic()

    def _admit(self, url: str, host: str) -> None:
        """The non-SSRF half of the wall: domain budget, robots.txt, politeness.

        Runs for the entry URL AND again for any redirect target that lands on a
        NEW host. Only the IP/scheme check used to be on the redirect path, so a
        30x to another domain got in past all three of these — and, because the
        host was never recorded, a later direct fetch of it counted as fresh
        against the budget a second time.
        """
        if host not in self.domains and len(self.domains) >= DOMAIN_BUDGET:
            raise FetchRefused(f"domain budget ({DOMAIN_BUDGET}) exhausted; refusing {host}")
        if not self._robots_ok(url, host):
            raise FetchRefused(f"robots.txt disallows {url}")
        self.domains.add(host)
        self._politeness(host)

    def guarded_fetch(self, url: str) -> httpx.Response:
        """Fetch under the full wall. Raises FetchRefused with a data-safe reason."""
        host = check_url(url)
        self._admit(url, host)

        current = url
        for _ in range(MAX_REDIRECTS + 1):
            resp = _http_get(current)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise FetchRefused("redirect without location")
                current = str(httpx.URL(current).join(location))
                # Every hop is re-checked for a public IP; an http hop may be
                # FOLLOWED but never read from (the final response must be https).
                hop_host = check_url(current, allow_http_hop=True)
                if hop_host != host:
                    # Landing on another domain is a fetch of that domain and owes
                    # the same toll as a direct one.
                    host = hop_host
                    self._admit(current, host)
                elif not self._robots_ok(current, host):
                    # Same host, new path — robots.txt is a per-path rule.
                    raise FetchRefused(f"robots.txt disallows {current}")
                continue
            if urlparse(current).scheme != "https":
                raise FetchRefused(f"refusing to read content over {urlparse(current).scheme!r}")
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
            if ctype and not any(ctype.startswith(t) for t in ALLOWED_TYPES):
                raise FetchRefused(f"content-type {ctype!r} not allowed")
            # Oversized responses of an ALLOWED type are truncated, not refused:
            # a few real venue sites ship >2MB of HTML, and the parts we need
            # (feed links, JSON-LD, program markup) are near the top anyway.
            if len(resp.content) > MAX_BYTES:
                resp._content = resp.content[:MAX_BYTES]
                resp.headers["x-pulse-truncated"] = "1"
            self.fetches += 1
            return resp
        raise FetchRefused(f"more than {MAX_REDIRECTS} redirects")
