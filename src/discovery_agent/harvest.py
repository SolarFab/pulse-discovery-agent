"""The harvest executor (publisher-discovery spec: Deterministic nightly harvest).

ONE generic program, a parser per recipe type. Parsers take CONTENT (already fetched
through the security wall) and return RawEvents — fully unit-testable without network.
The scout's verification gate calls execute_recipe() too: a recipe is only trusted if
THIS code, running it now, yields future dated events.

All parsed text is scraped, untrusted DATA (AGENTS.md rule 1).
"""

from __future__ import annotations

import html as ihtml
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from icalendar import Calendar

from .guards import FetchSession
from .recipes import BERLIN, RawEvent, Recipe

_TAGS = re.compile(r"<[^>]+>")
_LDJSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.DOTALL)


def _clean(text: str | None, limit: int = 2000) -> str | None:
    if not text:
        return None
    out = re.sub(r"\s+", " ", ihtml.unescape(_TAGS.sub(" ", str(text)))).strip()
    return out[:limit] or None


def _mk_event(**kw) -> RawEvent | None:
    try:
        return RawEvent(**{k: v for k, v in kw.items() if v is not None})
    except Exception:
        return None  # one malformed item never kills a harvest


# ── Parsers (content in, events out) ─────────────────────────────────────────

def parse_ics(text: str) -> list[RawEvent]:
    events: list[RawEvent] = []
    try:
        cal = Calendar.from_ical(text)
    except Exception:
        return []
    for comp in cal.walk("VEVENT"):
        start = comp.get("dtstart")
        if start is None:
            continue
        dt = start.dt
        if isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime(dt.year, dt.month, dt.day, tzinfo=BERLIN)
        end = comp.get("dtend")
        end_dt = None
        if end is not None:
            end_dt = end.dt
            if isinstance(end_dt, date) and not isinstance(end_dt, datetime):
                end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, tzinfo=BERLIN)
        ev = _mk_event(
            title=_clean(str(comp.get("summary") or ""), 300),
            start_time=dt, end_time=end_dt,
            description=_clean(str(comp.get("description") or "")),
            url=str(comp.get("url")) if comp.get("url") else None,
            address=_clean(str(comp.get("location") or ""), 300),
        )
        if ev:
            events.append(ev)
    return events


def parse_jsonld(html_text: str, base_url: str | None = None) -> list[RawEvent]:
    events: list[RawEvent] = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if "@graph" in node:
            walk(node["@graph"])
        types = node.get("@type") or ""
        types = types if isinstance(types, list) else [types]
        if any(str(t).endswith("Event") for t in types):
            start = node.get("startDate")
            if not start:
                return
            try:
                start_dt = dateparser.parse(start)
            except (ValueError, OverflowError):
                return
            end_raw = node.get("endDate")
            end_dt = None
            if end_raw:
                try:
                    end_dt = dateparser.parse(end_raw)
                except (ValueError, OverflowError):
                    end_dt = None
            loc = node.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = loc.get("address") if isinstance(loc, dict) else None
            if isinstance(addr, dict):
                addr = " ".join(str(v) for v in addr.values() if isinstance(v, str))
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price") if isinstance(offers, dict) else None
            ev = _mk_event(
                title=_clean(node.get("name"), 300),
                start_time=start_dt, end_time=end_dt,
                description=_clean(node.get("description")),
                url=node.get("url") or base_url,
                venue_name=_clean(loc.get("name") if isinstance(loc, dict) else None, 200),
                address=_clean(addr, 300),
                price=str(price) if price is not None else None,
            )
            if ev:
                events.append(ev)

    for block in _LDJSON.findall(html_text):
        try:
            walk(json.loads(block.strip()))
        except json.JSONDecodeError:
            continue
    return events


def parse_rss(xml_text: str) -> list[RawEvent]:
    """RSS 2.0 + Atom, stdlib only. Feed dates are publish dates — many event feeds
    put the event date in the title/description; those need jsonld/selector instead."""
    events: list[RawEvent] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)
    for item in items:
        def _t(*names):
            for n in names:
                el = item.find(n, ns)
                if el is not None and (el.text or el.get("href")):
                    return el.text or el.get("href")
            return None
        raw_date = _t("pubDate", "atom:published", "atom:updated")
        if not raw_date:
            continue
        try:
            start_dt = dateparser.parse(raw_date)
        except (ValueError, OverflowError):
            continue
        ev = _mk_event(
            title=_clean(_t("title", "atom:title"), 300),
            start_time=start_dt,
            description=_clean(_t("description", "atom:summary")),
            url=_t("link", "atom:link"),
        )
        if ev:
            events.append(ev)
    return events


def parse_html_selector(html_text: str, recipe: Recipe, base_url: str) -> list[RawEvent]:
    if not recipe.params:
        return []
    p = recipe.params
    soup = BeautifulSoup(html_text, "html.parser")
    events: list[RawEvent] = []
    for item in soup.select(p.item_selector)[:100]:
        title_el = item.select_one(p.title_selector) if p.title_selector else item
        title = _clean(title_el.get_text() if title_el else None, 300)

        date_text = None
        if p.date_selector:
            date_el = item.select_one(p.date_selector)
            if date_el is not None:
                date_text = (date_el.get(p.date_attr) if p.date_attr else None) \
                    or date_el.get_text()
        else:
            time_el = item.select_one("time[datetime]")
            date_text = time_el.get("datetime") if time_el else None
        if not date_text:
            continue
        try:
            start_dt = dateparser.parse(str(date_text), dayfirst=True, fuzzy=True)
        except (ValueError, OverflowError):
            continue

        url = None
        link_el = item.select_one(p.url_selector) if p.url_selector else item.select_one("a[href]")
        if link_el is not None and link_el.get("href"):
            url = str(__import__("httpx").URL(base_url).join(link_el["href"]))

        ev = _mk_event(title=title, start_time=start_dt, url=url)
        if ev:
            events.append(ev)
    return events


# ── Date-prefixed lines ──────────────────────────────────────────────────────
# Small venues often publish a program as flat text separated by <br>, with no
# per-event container at all: "Aug 8  Band Name  (instruments)". No selector can
# address those, so the line itself is the unit.

_MONTHS = ("jan", "feb", "mar", "mär", "apr", "may", "mai", "jun", "jul", "aug",
           "sep", "oct", "okt", "nov", "dec", "dez")
_LINE_DATE = re.compile(
    r"^\s*(?:"
    r"(?P<d1>\d{1,2})[.\s]+(?P<m1>" + "|".join(_MONTHS) + r")[a-zä]*\.?"      # 8. Aug
    r"|(?P<m2>" + "|".join(_MONTHS) + r")[a-zä]*\.?\s+(?P<d2>\d{1,2})"        # Aug 8
    r"|(?P<d3>\d{1,2})\.(?P<mo3>\d{1,2})\.(?P<y3>\d{2,4})?"                   # 08.08.26
    r")\s*(?P<rest>.*)$", re.IGNORECASE)
_MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "mär": 3, "apr": 4, "may": 5, "mai": 5,
              "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "okt": 10,
              "nov": 11, "dec": 12, "dez": 12}


def _roll_year(month: int, day: int, now: datetime) -> int:
    """Undated listings mean the NEXT occurrence. A month already well past is
    next year's; a slightly-past date is this year's (a listing lingering a few
    days after the show is normal)."""
    year = now.year
    try:
        candidate = datetime(year, month, day, tzinfo=BERLIN)
    except ValueError:
        return year
    if (now - candidate).days > 60:
        year += 1
    return year


def parse_date_lines(html_fragment: str, base_url: str | None = None,
                     now: datetime | None = None) -> list[RawEvent]:
    """Events from <br>-separated, date-prefixed lines of text."""
    now = now or datetime.now(tz=BERLIN)
    soup = BeautifulSoup(html_fragment, "html.parser")
    # Line breaks come ONLY from <br> and block elements. Using get_text("\n")
    # instead would split inline tags too, tearing "Aug 8" away from the <b>title</b>
    # that follows it and leaving a dateless fragment behind.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4"]):
        block.append("\n")
    text = ihtml.unescape(soup.get_text("")).replace("\xa0", " ")

    events: list[RawEvent] = []
    for raw_line in text.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 6:
            continue
        m = _LINE_DATE.match(line)
        if not m:
            continue
        g = m.groupdict()
        if g["m1"] or g["m2"]:
            month = _MONTH_NUM[(g["m1"] or g["m2"]).lower()[:3]
                               if (g["m1"] or g["m2"]).lower()[:3] in _MONTH_NUM
                               else (g["m1"] or g["m2"]).lower()]
            day = int(g["d1"] or g["d2"])
            year = _roll_year(month, day, now)
        else:
            day, month = int(g["d3"]), int(g["mo3"])
            year = int(g["y3"]) if g["y3"] else _roll_year(month, day, now)
            if year < 100:
                year += 2000
        title = (g["rest"] or "").strip(" –—-·|,")
        if len(title) < 3:
            continue
        try:
            start = datetime(year, month, day, 20, 0, tzinfo=BERLIN)
        except ValueError:
            continue
        ev = _mk_event(title=_clean(title, 300), start_time=start, url=base_url)
        if ev:
            events.append(ev)
    return events


def parse_embedded_json(html_text: str, base_url: str | None = None) -> list[RawEvent]:
    """Events from a site's OWN JSON payload embedded in a <script> tag.

    Distinct from JSON-LD: no schema, just a page-builder blob (Cargo, Squarespace,
    Wix …) whose string values hold the rendered HTML. Measured at ~7% of publisher
    sites — small, but it is the only way in when the page ships a shell and fills
    itself from a script (sowiesoberlin.com serves its whole program this way).
    """
    events: list[RawEvent] = []
    seen: set[tuple] = set()
    soup = BeautifulSoup(html_text, "html.parser")

    def harvest_strings(node, depth=0):
        if depth > 8:
            return
        if isinstance(node, str):
            if "<" in node and len(node) > 120:      # a string carrying markup
                for ev in parse_date_lines(node, base_url):
                    key = (ev.title, ev.start_time)
                    if key not in seen:
                        seen.add(key)
                        events.append(ev)
            return
        if isinstance(node, dict):
            for v in node.values():
                harvest_strings(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:200]:
                harvest_strings(v, depth + 1)

    for script in soup.find_all("script"):
        body = (script.string or "").strip()
        if len(body) < 100 or not body.startswith(("{", "[")):
            continue
        if "ld+json" in (script.get("type") or ""):
            continue                                  # JSON-LD has its own parser
        try:
            harvest_strings(json.loads(body))
        except json.JSONDecodeError:
            continue
    return events


# ── The executor ─────────────────────────────────────────────────────────────

def execute_recipe(recipe: Recipe, session: FetchSession | None = None) -> list[RawEvent]:
    """Run one recipe through the wall and the right parser. Markers yield []."""
    if recipe.recipe_type in ("aggregator_covered", "instagram_lead", "none"):
        return []
    if not recipe.url:
        return []
    session = session or FetchSession()
    resp = session.guarded_fetch(str(recipe.url))
    text = resp.text
    if recipe.recipe_type == "ics_feed":
        return parse_ics(text)
    if recipe.recipe_type == "jsonld":
        return parse_jsonld(text, base_url=str(recipe.url))
    if recipe.recipe_type == "rss":
        return parse_rss(text)
    if recipe.recipe_type == "html_selector":
        return parse_html_selector(text, recipe, base_url=str(recipe.url))
    if recipe.recipe_type == "embedded_json":
        return parse_embedded_json(text, base_url=str(recipe.url))
    return []
