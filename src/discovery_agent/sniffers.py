"""Deterministic channel sniffers — the zero-token fast path (spec: Hybrid scout).

Before ANY LLM call, probe the obvious: declared feeds, well-known calendar paths,
JSON-LD on the homepage and on likely program pages. My bet (the pilot measures it):
a large share of venues resolve right here, for the cost of a few polite fetches.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .guards import FetchRefused, FetchSession
from .harvest import parse_ics, parse_jsonld, parse_rss
from .recipes import Recipe

PROGRAM_LINK = re.compile(
    r"veranstalt|events?\b|programm|kalender|calendar|termine|whats.?on|line.?up|agenda",
    re.IGNORECASE,
)
COMMON_FEED_PATHS = ["/events.ics", "/calendar.ics", "/?ical=1", "/events/feed",
                     "/feed", "/rss", "/events.xml"]
FEED_TYPES = {
    "text/calendar": "ics_feed",
    "application/rss+xml": "rss",
    "application/atom+xml": "rss",
}
_PARSERS = {"ics_feed": parse_ics, "jsonld": parse_jsonld, "rss": parse_rss}


def _try(session: FetchSession, url: str) -> str | None:
    try:
        return session.guarded_fetch(url).text
    except (FetchRefused, Exception):
        return None


def _candidate_if_parses(recipe_type: str, url: str, text: str, trace: list) -> Recipe | None:
    events = _PARSERS[recipe_type](text)
    trace.append({"step": "sniff_parse", "type": recipe_type, "url": url,
                  "events_found": len(events)})
    if events:
        return Recipe(recipe_type=recipe_type, url=url, confidence=0.9,  # type: ignore[arg-type]
                      scope="full program (sniffed)")
    return None


def find_program_links(html_text: str, base_url: str, limit: int = 3) -> list[str]:
    """Likely program-page links on a page, same-ish domain, deduped, best first."""
    soup = BeautifulSoup(html_text, "html.parser")
    base_host = urlparse(base_url).hostname or ""
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        label = f"{a.get_text(' ', strip=True)} {a['href']}"
        if not PROGRAM_LINK.search(label):
            continue
        url = urljoin(base_url, a["href"]).split("#")[0]
        host = urlparse(url).hostname or ""
        if not url.startswith("https://") or base_host not in host:
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= limit:
            break
    return out


def declared_feeds(html_text: str, base_url: str) -> list[tuple[str, str]]:
    """(recipe_type, url) for <link rel=alternate> feed declarations."""
    soup = BeautifulSoup(html_text, "html.parser")
    out = []
    for link in soup.find_all("link", href=True):
        ltype = (link.get("type") or "").lower().split(";")[0]
        if ltype in FEED_TYPES:
            out.append((FEED_TYPES[ltype], urljoin(base_url, link["href"])))
    return out


def sniff(website: str, session: FetchSession, trace: list) -> Recipe | None:
    """Run the whole deterministic ladder. Returns the first recipe whose content
    parses to events — final verification still happens in the verify node."""
    home = _try(session, website)
    if home is None:
        trace.append({"step": "sniff", "note": f"homepage unreachable: {website}"})
        return None

    # 1. Declared feeds beat everything.
    for rtype, url in declared_feeds(home, website):
        text = _try(session, url)
        if text:
            r = _candidate_if_parses(rtype, url, text, trace)
            if r:
                return r

    # 2. JSON-LD on the homepage itself.
    r = _candidate_if_parses("jsonld", website, home, trace)
    if r:
        return r

    # 3. Program pages: JSON-LD there, plus feed declarations one level deep.
    program_pages: list[tuple[str, str]] = []
    for url in find_program_links(home, website):
        text = _try(session, url)
        if not text:
            continue
        program_pages.append((url, text))
        r = _candidate_if_parses("jsonld", url, text, trace)
        if r:
            return r
        for rtype, feed_url in declared_feeds(text, url):
            feed_text = _try(session, feed_url)
            if feed_text:
                r = _candidate_if_parses(rtype, feed_url, feed_text, trace)
                if r:
                    return r

    # 4. Well-known calendar paths (cheap guesses, only while budget allows).
    origin = f"https://{urlparse(website).hostname}"
    for path in COMMON_FEED_PATHS:
        if session.fetches >= 12:  # sniffing stays cheap; the LLM path has its own budget
            break
        text = _try(session, origin + path)
        if not text:
            continue
        rtype = "ics_feed" if text.lstrip().startswith("BEGIN:VCALENDAR") else \
                "rss" if text.lstrip().startswith("<?xml") else None
        if rtype:
            r = _candidate_if_parses(rtype, origin + path, text, trace)
            if r:
                return r

    trace.append({"step": "sniff", "note": "no structured channel found",
                  "program_pages_seen": [u for u, _ in program_pages]})
    return None
