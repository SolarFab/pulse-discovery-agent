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


class FetchRefused(Exception):
    """The wall said no. The reason is safe to show the model as data."""


def _resolve_public(host: str) -> None:
    """Reject hosts that resolve to any non-public address (SSRF wall)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchRefused(f"DNS failed for {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
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
                resp = httpx.get(f"https://{host}/robots.txt", timeout=10,
                                 headers={"User-Agent": UA}, follow_redirects=True)
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

    def guarded_fetch(self, url: str) -> httpx.Response:
        """Fetch under the full wall. Raises FetchRefused with a data-safe reason."""
        host = check_url(url)
        if host not in self.domains and len(self.domains) >= DOMAIN_BUDGET:
            raise FetchRefused(f"domain budget ({DOMAIN_BUDGET}) exhausted; refusing {host}")
        if not self._robots_ok(url, host):
            raise FetchRefused(f"robots.txt disallows {url}")
        self.domains.add(host)
        self._politeness(host)

        current = url
        for _ in range(MAX_REDIRECTS + 1):
            resp = httpx.get(current, timeout=20, headers={"User-Agent": UA},
                             follow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise FetchRefused("redirect without location")
                current = str(httpx.URL(current).join(location))
                # Every hop is re-checked for a public IP; an http hop may be
                # FOLLOWED but never read from (the final response must be https).
                check_url(current, allow_http_hop=True)
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
