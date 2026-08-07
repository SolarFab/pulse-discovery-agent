"""Mine venue websites out of data we already have (task 4.1b).

The scout can only work on publishers whose URL we know — 608 of 2,770. The other
78% are not silent, they are unaddressed: we never learned where they live.

Before paying anyone to search for those URLs, check whether we already hold them.
Every event carries a `source_url`. For events at a venue with no website on file,
a NON-aggregator domain in that URL is very likely the venue's own site. This is
pure SQL and string matching — no LLM, no fetching.

Read-only by default. `--apply` is what writes.

    uv run python scripts/mine_websites.py            # report only
    uv run python scripts/mine_websites.py --apply    # write publishers.website
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discovery_agent.store_supabase import _client  # noqa: E402

# Domains that host MANY venues' events. A source_url on one of these tells us where
# the event was scraped, not who runs the room — the exact distinction that makes
# this mining safe.
AGGREGATORS = {
    "kulturdaten.berlin", "berlin.de", "rausgegangen.de", "berlinmitkind.de",
    "ra.co", "residentadvisor.net", "lu.ma", "eventbrite.de", "eventbrite.com",
    "eventbrite.co.uk", "meetup.com", "bandsintown.com", "tip-berlin.de",
    "startbahn.berlin", "dice.fm", "songkick.com", "facebook.com", "instagram.com",
    "app.cituro.com", "voebb.de", "eventim.de", "ticketmaster.de",
}
# Generic words that carry no identity — matching on them would pair every
# "Stadtteilbibliothek X" with any library domain.
STOPWORDS = {
    "berlin", "das", "der", "die", "und", "im", "am", "zum", "zur", "cafe", "bar",
    "club", "kultur", "haus", "zentrum", "galerie", "theater", "museum", "buehne",
    "stadtteilbibliothek", "bibliothek", "volkshochschule", "kirche", "e", "v",
}


def norm(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", text)


def tokens(name: str) -> list[str]:
    parts = re.split(r"[^a-zA-ZäöüÄÖÜß0-9]+", name.lower())
    return [norm(p) for p in parts if len(norm(p)) > 2 and norm(p) not in STOPWORDS]


def confidence(venue: str, domain: str) -> tuple[str, str]:
    """How much do the venue name and the domain agree? Returns (level, why)."""
    stem = norm(domain.rsplit(".", 1)[0].split(".")[-1])   # strip TLD and subdomain
    vn = norm(venue)
    if not stem:
        return "low", "no usable domain stem"
    if stem in vn or vn in stem:
        return "high", "domain stem contained in venue name"
    toks = tokens(venue)
    if any(t in stem for t in toks if len(t) > 4):
        return "high", "distinctive word from the name in the domain"
    ratio = difflib.SequenceMatcher(None, vn, stem).ratio()
    if ratio >= 0.62:
        return "medium", f"fuzzy similarity {ratio:.2f}"
    return "low", f"fuzzy similarity {ratio:.2f}"


def fetch_all(sb, table: str, cols: str) -> list[dict]:
    out, page = [], 0
    while True:
        rows = sb.table(table).select(cols).range(page * 1000, page * 1000 + 999).execute().data or []
        out += rows
        if len(rows) < 1000:
            return out
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write publishers.website")
    ap.add_argument("--min-events", type=int, default=2,
                    help="ignore a domain seen fewer times (default 2)")
    args = ap.parse_args()
    sb = _client()

    publishers = fetch_all(sb, "publishers", "id,name,website")
    missing = {(p["name"] or "").strip().lower(): p for p in publishers if not p.get("website")}
    print(f"publishers: {len(publishers)}  ·  without a website: {len(missing)}")

    events = fetch_all(sb, "events", "venue_name,source_url")
    seen: dict[str, Counter] = {}
    for e in events:
        vn = (e.get("venue_name") or "").strip().lower()
        url = e.get("source_url")
        if vn not in missing or not url:
            continue
        host = (urlparse(url).hostname or "").removeprefix("www.").lower()
        if not host or host in AGGREGATORS:
            continue
        seen.setdefault(vn, Counter())[host] += 1

    buckets: dict[str, list] = {"high": [], "medium": [], "low": []}
    for vn, counter in seen.items():
        host, n = counter.most_common(1)[0]
        if n < args.min_events:
            continue
        level, why = confidence(missing[vn]["name"], host)
        buckets[level].append((missing[vn], host, n, why))

    for level in ("high", "medium", "low"):
        rows = sorted(buckets[level], key=lambda r: -r[2])
        print(f"\n{level.upper():6s} confidence: {len(rows)}")
        for pub, host, n, why in rows[:8]:
            print(f"    {pub['name'][:34]:34s} -> {host:32s} {n:5d} events   ({why})")
        if len(rows) > 8:
            print(f"    … {len(rows) - 8} more")

    total = len(buckets["high"])
    print(f"\nWould set a website on {total} publishers (high confidence only).")
    if not args.apply:
        print("Read-only. Re-run with --apply to write.")
        return

    for pub, host, _n, _why in buckets["high"]:
        sb.table("publishers").update({"website": f"https://{host}"}).eq("id", pub["id"]).execute()
    print(f"Applied: {total} publishers now have a website and are scoutable.")


if __name__ == "__main__":
    main()
