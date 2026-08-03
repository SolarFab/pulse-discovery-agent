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
    return []
