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
import warnings
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from . import observability
from .guards import FetchRefused, FetchSession

# We deliberately parse whatever a URL returns with one lenient parser: a page that
# turns out to be a feed is a *finding*, not an error, and the scout's own signal
# checks handle it. Suppressed so the warning does not drown the run log.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

MAX_TEXT = 3500
MAX_LINKS = 40
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def fetch_page(session: FetchSession, url: str) -> str:
    """Fetch a page through the wall; return visible text + on-page links.

    The result is UNTRUSTED page content, clearly delimited for the model.
    """
    if not _HAS_SCHEME.match(url):
        url = "https://" + url
    with observability.fetch_span(url, "model") as span:
        try:
            resp = session.guarded_fetch(url)
            span.update(output={"ok": True, "status": resp.status_code})
        except FetchRefused as exc:
            span.update(output={"ok": False, "reason": str(exc)[:200]})
            return f"[fetch_refused] {exc}"
        except Exception as exc:  # noqa: BLE001 — the loop must never die on a bad page
            span.update(output={"ok": False, "reason": str(exc)[:200]})
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


# This drives the `dateish` score below, i.e. which repeating container the model is
# shown as an html_selector candidate — so both directions of error hurt. Two bugs
# lived here: "mai" and the English month names were missing (a real programme whose
# only signal was "Mai 15" scored ZERO and got flagged unusable), and in
# `mo|di|…|so\b` an alternation binds `\b` to the LAST branch only, so "moment",
# "Doors", "friendly" and "sample" all counted as dates. Every word alternative is
# anchored on both sides now: unanchored, "mai"/"may" would fire on "main" and
# "e-mail" — the exact noise the score exists to filter out.
_DATEISH = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./ ]"
    r"|\b\d{4}-\d{2}-\d{2}"
    r"|\b(?:januar|january|februar|february|märz|march|april|mai|may"
    r"|juni|june|juli|july|august|september|oktober|october"
    r"|november|dezember|december)\b"
    r"|\b(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(?:mo|di|mi|do|fr|sa|so)\b",
    re.IGNORECASE,
)


def _skeleton(el, limit: int = 6) -> str:
    """The child markup of one sample item, so the model can write date/title
    selectors instead of guessing. Text alone is not enough: an item whose text
    reads like an event may contain no date element at all, and a recipe built on
    it silently yields zero events."""
    parts = []
    for child in el.find_all(True, recursive=True)[:limit]:
        sel = child.name + "".join(f".{c}" for c in (child.get("class") or [])[:2])
        if child.name == "time" and child.get("datetime"):
            sel += f"[datetime={child['datetime'][:24]}]"
        text = child.get_text(" ", strip=True)[:40]
        parts.append(f"{sel}: {text!r}" if text else sel)
    return " | ".join(parts) or "(no child elements)"


def _structure_hints(soup: BeautifulSoup, top: int = 3) -> list[str]:
    """Deterministic selector material: groups of same-tag/same-class elements that
    repeat like an event list. Without this the model can't write CSS selectors —
    the visible-text extraction hides every class name."""
    groups: dict[tuple, list] = {}
    for el in soup.find_all(True):
        classes = tuple((el.get("class") or [])[:2])
        # `li` and `tr` are the most common event-list containers; excluding them to
        # suppress nav-menu noise threw away the signal along with it. Scoring
        # (below) demotes the dateless ones instead.
        if not classes or el.name in ("script", "style", "span", "a", "path", "svg"):
            continue
        groups.setdefault((el.name, classes), []).append(el)
    scored = []
    for (tag, classes), els in groups.items():
        if not (4 <= len(els) <= 200):
            continue
        sample_text = els[0].get_text(" ", strip=True)[:200]
        if len(sample_text) < 10:
            continue
        has_time = 1 if els[0].select_one("time[datetime]") else 0
        # A container with no date ANYWHERE inside it cannot produce events, no
        # matter how convincingly it repeats — rank those last.
        dateish = 2 if _DATEISH.search(sample_text) else 0
        scored.append((dateish + has_time * 2, len(els), tag, classes,
                       sample_text, has_time, els[0]))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    hints = []
    for score, count, tag, classes, sample, has_time, el in scored[:top]:
        sel = tag + "".join(f".{c}" for c in classes)
        flag = " [contains <time datetime>]" if has_time else (
            "" if score else " [NO DATE FOUND INSIDE — unusable alone]")
        hints.append(f"- {sel}  ({count} items){flag}\n"
                     f"    text: \"{sample[:120]}\"\n"
                     f"    markup: {_skeleton(el)}")
    return hints


def same_site(url: str, publisher_website: str) -> bool:
    """Loose same-site check used to warn (not block) when the scout wanders off."""
    a = (urlparse(url).hostname or "").removeprefix("www.")
    b = (urlparse(publisher_website).hostname or "").removeprefix("www.")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
