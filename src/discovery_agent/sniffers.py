"""Deterministic channel sniffers — the zero-token fast path (spec: Hybrid scout).

Before ANY LLM call, probe the obvious: declared feeds, well-known calendar paths,
JSON-LD on the homepage and on likely program pages. My bet (the pilot measures it):
a large share of venues resolve right here, for the cost of a few polite fetches.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import settings
from .guards import FetchRefused, FetchSession
from .harvest import parse_embedded_json, parse_ics, parse_jsonld, parse_rss
from .recipes import Recipe

PROGRAM_LINK = re.compile(
    r"veranstalt|events?\b|programm|kalender|calendar|termine|whats.?on|line.?up|agenda",
    re.IGNORECASE,
)
# A single event's detail page also carries Event JSON-LD, and its URL also says
# "events" — accepting one would pin the venue to exactly one event forever. A
# program must look like a LIST.
MIN_PROGRAM_EVENTS = 3
COMMON_FEED_PATHS = ["/events.ics", "/calendar.ics", "/?ical=1", "/events/feed",
                     "/feed", "/rss", "/events.xml"]
FEED_TYPES = {
    "text/calendar": "ics_feed",
    "application/rss+xml": "rss",
    "application/atom+xml": "rss",
}
_PARSERS = {"ics_feed": parse_ics, "jsonld": parse_jsonld, "rss": parse_rss,
            "embedded_json": parse_embedded_json}


def _try(session: FetchSession, url: str, seen: set[str] | None = None) -> str | None:
    """Fetch once per URL per run. The ladder legitimately arrives at the same URL
    from two directions (a declared /feed/ is also a well-known path), and each
    repeat spent a fetch from a budget that exists to be spent on new ground."""
    key = url.rstrip("/")
    if seen is not None:
        if key in seen:
            return None
        seen.add(key)
    try:
        return session.guarded_fetch(url).text
    except (FetchRefused, Exception):
        return None


def _candidate_if_parses(recipe_type: str, url: str, text: str, trace: list,
                         min_events: int = MIN_PROGRAM_EVENTS) -> Recipe | None:
    """A candidate must parse to a LIST of events, not a single one.

    Feeds (ICS/RSS) are list-shaped by construction, so one event there is still a
    feed; page-embedded JSON-LD is the trap — hence the higher bar for it.
    """
    events = _PARSERS[recipe_type](text)
    trace.append({"step": "sniff_parse", "type": recipe_type, "url": url,
                  "events_found": len(events)})
    threshold = 1 if recipe_type in ("ics_feed", "rss") else min_events
    if len(events) >= threshold:
        return Recipe(recipe_type=recipe_type, url=url, confidence=0.9,  # type: ignore[arg-type]
                      scope=f"sniffed: {len(events)} events listed")
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
    # Shallow paths first: /programm is an index, /events/2026-08-08-some-show is one
    # event. Sorting by depth spends the fetch budget on list pages.
    out.sort(key=lambda u: (urlparse(u).path.strip("/").count("/"), len(u)))
    return out[:limit]


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
    """First deterministic candidate, or None. See sniff_candidates for the rest."""
    found = sniff_candidates(website, session, trace, stop_after=1)
    return found[0] if found else None


def sniff_candidates(website: str, session: FetchSession, trace: list,
                     stop_after: int = 3) -> list[Recipe]:
    """EVERY deterministic candidate, best first.

    Returning only the first one was a real cost bug: a venue whose RSS feed is a
    stale blog (Klunkerkranich, Sowieso) had that single candidate rejected by
    verification and went straight to the paid model — even though a perfectly good
    embedded_json program sat one rung further down the same free ladder.
    """
    found: list[Recipe] = []
    seen: set[str] = set()
    home = _try(session, website, seen)
    if home is None:
        # Seeded URLs carry stale paths (OSM had columbiahalle.berlin/de/, a 404,
        # while the site itself is fine). One retry at the origin root turns a
        # written-off venue back into a scoutable one.
        origin = f"https://{urlparse(website).hostname}"
        if origin.rstrip("/") != website.rstrip("/"):
            home = _try(session, origin, seen)
            if home is not None:
                trace.append({"step": "sniff", "note": f"fell back to origin {origin}"})
                website = origin
    if home is None:
        # Explicit marker: callers must distinguish "site is dead" from "site has no
        # program". Only the latter is worth spending a model on.
        trace.append({"step": "sniff", "unreachable": True,
                      "note": f"homepage unreachable: {website}"})
        return []

    # 1. Declared feeds beat everything.
    for rtype, url in declared_feeds(home, website):
        text = _try(session, url, seen)
        if text:
            r = _candidate_if_parses(rtype, url, text, trace)
            if r:
                found.append(r)
                if len(found) >= stop_after:
                    return found

    # 2. JSON-LD on the homepage itself, then the site's own JSON payload.
    r = _candidate_if_parses("jsonld", website, home, trace)
    if r:
        found.append(r)
        if len(found) >= stop_after:
            return found
    r = _candidate_if_parses("embedded_json", website, home, trace)
    if r:
        found.append(r)
        if len(found) >= stop_after:
            return found

    # 3. Program pages: JSON-LD there, plus feed declarations one level deep.
    program_pages: list[tuple[str, str]] = []
    for url in find_program_links(home, website):
        text = _try(session, url, seen)
        if not text:
            continue
        program_pages.append((url, text))
        r = _candidate_if_parses("jsonld", url, text, trace)
        if r:
            found.append(r)
            if len(found) >= stop_after:
                return found
        # A page that ships a shell and fills itself from a script blob has no
        # markup to select — the payload is the only way in (see FINDINGS).
        r = _candidate_if_parses("embedded_json", url, text, trace)
        if r:
            found.append(r)
            if len(found) >= stop_after:
                return found
        for rtype, feed_url in declared_feeds(text, url):
            feed_text = _try(session, feed_url, seen)
            if feed_text:
                r = _candidate_if_parses(rtype, feed_url, feed_text, trace)
                if r:
                    found.append(r)
                    if len(found) >= stop_after:
                        return found

    # 4. Well-known calendar paths (cheap guesses, only while budget allows).
    origin = f"https://{urlparse(website).hostname}"
    for path in COMMON_FEED_PATHS:
        if session.fetches >= settings.scout_max_sniff_fetches:
            trace.append({"step": "abort", "reason": "sniff fetch budget"})
            break
        text = _try(session, origin + path, seen)
        if not text:
            continue
        rtype = "ics_feed" if text.lstrip().startswith("BEGIN:VCALENDAR") else \
                "rss" if text.lstrip().startswith("<?xml") else None
        if rtype:
            r = _candidate_if_parses(rtype, origin + path, text, trace)
            if r:
                found.append(r)
                if len(found) >= stop_after:
                    return found

    if not found:
        trace.append({"step": "sniff", "note": "no structured channel found",
                      "program_pages_seen": [u for u, _ in program_pages]})
    return found
