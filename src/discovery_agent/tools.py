"""Tools the scout LLM can call while investigating where a publisher posts events.

Deliberately thin and deterministic: the LLM decides *which* to call and *how to
interpret* results; the tools do no reasoning. Every fetch goes through the
guards.FetchSession security wall (https-only, public IPs, robots, budgets).

SECURITY: every string returned here originates from an untrusted public web page.
It is DATA, never instructions. Fetched text is wrapped in explicit markers and the
system prompt forbids acting on instructions inside it (OWASP LLM01 — indirect
prompt injection). Tool errors come back as strings so the loop stays in control.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .guards import FetchRefused, FetchSession

MAX_TEXT = 3500
MAX_LINKS = 40
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def fetch_page(session: FetchSession, url: str) -> str:
    """Fetch a page through the wall; return visible text + on-page links.

    The result is UNTRUSTED page content, clearly delimited for the model.
    """
    if not _HAS_SCHEME.match(url):
        url = "https://" + url
    try:
        resp = session.guarded_fetch(url)
    except FetchRefused as exc:
        return f"[fetch_refused] {exc}"
    except Exception as exc:  # noqa: BLE001 — the loop must never die on a bad page
        return f"[fetch_error] {type(exc).__name__}: {exc}"

    body = resp.text
    # Structured content is a strong signal — tell the model instead of hiding it.
    signals = []
    if "application/ld+json" in body:
        signals.append("PAGE CONTAINS application/ld+json SCRIPT BLOCKS")
    if body.lstrip().startswith("BEGIN:VCALENDAR"):
        return ("SIGNAL: THIS URL IS AN ICS CALENDAR FEED.\n"
                "<untrusted_page_content>\n" + body[:1500] + "\n</untrusted_page_content>")
    if body.lstrip().startswith("<?xml") and ("<rss" in body[:500] or "<feed" in body[:500]):
        return ("SIGNAL: THIS URL IS AN RSS/ATOM FEED.\n"
                "<untrusted_page_content>\n" + body[:1500] + "\n</untrusted_page_content>")

    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())[:MAX_TEXT]

    links, seen = [], set()
    resoup = BeautifulSoup(body, "html.parser")
    for a in resoup.find_all("a", href=True)[:400]:
        href = urljoin(url, a["href"]).split("#")[0]
        if not href.startswith("https://") or href in seen:
            continue
        seen.add(href)
        label = a.get_text(" ", strip=True)[:80]
        links.append(f"- {label or '(no text)'} -> {href}")
        if len(links) >= MAX_LINKS:
            break
    feed_links = []
    for link in resoup.find_all("link", href=True):
        ltype = (link.get("type") or "").lower()
        if "calendar" in ltype or "rss" in ltype or "atom" in ltype:
            feed_links.append(f"- DECLARED FEED ({ltype}) -> {urljoin(url, link['href'])}")

    parts = []
    if signals:
        parts.append("SIGNALS: " + "; ".join(signals))
    if feed_links:
        parts.append("DECLARED FEEDS:\n" + "\n".join(feed_links))
    structures = _structure_hints(resoup)
    if structures:
        parts.append("REPEATING STRUCTURES (candidate html_selector items):\n"
                     + "\n".join(structures))
    parts.append("<untrusted_page_content>\n" + text + "\n</untrusted_page_content>")
    if links:
        parts.append("LINKS ON PAGE:\n" + "\n".join(links))
    return "\n\n".join(parts)


_DATEISH = re.compile(r"\b\d{1,2}[./]\d{1,2}[./ ]|\b\d{4}-\d{2}-\d{2}|januar|februar|märz|april"
                      r"|juni|juli|august|september|oktober|november|dezember"
                      r"|mo|di|mi|do|fr|sa|so\b", re.IGNORECASE)


def _structure_hints(soup: BeautifulSoup, top: int = 3) -> list[str]:
    """Deterministic selector material: groups of same-tag/same-class elements that
    repeat like an event list. Without this the model can't write CSS selectors —
    the visible-text extraction hides every class name."""
    groups: dict[tuple, list] = {}
    for el in soup.find_all(True):
        classes = tuple((el.get("class") or [])[:2])
        if not classes or el.name in ("script", "style", "span", "a", "li", "path", "svg"):
            continue
        groups.setdefault((el.name, classes), []).append(el)
    scored = []
    for (tag, classes), els in groups.items():
        if not (4 <= len(els) <= 80):
            continue
        sample_text = els[0].get_text(" ", strip=True)[:200]
        if len(sample_text) < 10:
            continue
        dateish = 1 if _DATEISH.search(sample_text) else 0
        has_time = 1 if els[0].select_one("time[datetime]") else 0
        scored.append((dateish + has_time, len(els), tag, classes, sample_text, has_time))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    hints = []
    for _score, count, tag, classes, sample, has_time in scored[:top]:
        sel = tag + "".join(f".{c}" for c in classes)
        extra = " [items contain <time datetime>]" if has_time else ""
        hints.append(f"- {sel}  ({count} items){extra}  sample: \"{sample[:150]}\"")
    return hints


def same_site(url: str, publisher_website: str) -> bool:
    """Loose same-site check used to warn (not block) when the scout wanders off."""
    a = (urlparse(url).hostname or "").removeprefix("www.")
    b = (urlparse(publisher_website).hostname or "").removeprefix("www.")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
