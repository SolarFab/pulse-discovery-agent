"""Task 4.1 — give publishers a website to scout, from OpenStreetMap.

The seeded publishers carry names only, so the scout has nothing to investigate.
Overpass knows `website` / `contact:instagram` for a large share of Berlin's venues.

Matching is deliberately CONSERVATIVE: normalized-exact only. A wrong website costs
a wasted (paid) scout run and pollutes the contract, so ambiguity is dropped, counted,
and reported rather than guessed.

    uv run python scripts/enrich_publishers_overpass.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discovery_agent.store_supabase import _client  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"

# Venue-ish OSM tags. Restaurants/cafes are excluded: they rarely run event programs
# and would dominate the match set.
QUERY = """
[out:json][timeout:180];
area["name"="Berlin"]["admin_level"="4"]->.berlin;
(
  nwr["amenity"~"^(nightclub|theatre|cinema|arts_centre|community_centre|bar|pub|music_venue|events_venue|social_facility|library)$"](area.berlin);
  nwr["leisure"~"^(dance|hackerspace|sports_centre|club)$"](area.berlin);
  nwr["tourism"~"^(museum|gallery|artwork)$"](area.berlin);
  nwr["club"](area.berlin);
  nwr["amenity"="exhibition_centre"](area.berlin);
);
out tags center;
"""

_NOISE = re.compile(
    r"\b(e\.?\s?v\.?|gmbh|ug|ggmbh|mbh|kg|ohg|inh\.?|berlin|club|bar|cafe|café|"
    r"restaurant|gallery|galerie|theater|theatre|kino)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Aggressive but reversible-in-spirit: lowercase, drop punctuation and generic
    words, collapse space. Two venues normalizing to the same key are ambiguous."""
    s = (name or "").lower().replace("ß", "ss")
    s = _PUNCT.sub(" ", s)
    s = _NOISE.sub(" ", s)
    return _SPACE.sub(" ", s).strip()


def fetch_osm() -> list[dict]:
    print("[overpass] querying Berlin venues (this takes ~30-90s)...")
    resp = httpx.post(OVERPASS, data={"data": QUERY}, timeout=240.0,
                      headers={"User-Agent": "PulseDiscoveryBot/0.2 (+github.com/SolarFab)"})
    resp.raise_for_status()
    elements = resp.json().get("elements", [])
    print(f"[overpass] {len(elements)} elements returned")
    return elements


def osm_index(elements: list[dict]) -> tuple[dict[str, dict], int]:
    """normalized name -> {website, instagram}. Ambiguous keys are dropped."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        website = (tags.get("website") or tags.get("contact:website")
                   or tags.get("url") or "").strip()
        insta = (tags.get("contact:instagram") or tags.get("instagram") or "").strip()
        if not website and not insta:
            continue
        if website and not website.startswith("http"):
            website = "https://" + website
        if website.startswith("http://"):
            website = "https://" + website[7:]   # the fetch wall is https-only
        if insta.startswith("http"):
            insta = "@" + insta.rstrip("/").rsplit("/", 1)[-1]
        elif insta and not insta.startswith("@"):
            insta = "@" + insta
        key = normalize(name)
        if key:
            by_key[key].append({"website": website or None, "instagram": insta or None,
                                "osm_name": name})
    index, ambiguous = {}, 0
    for key, hits in by_key.items():
        sites = {h["website"] for h in hits if h["website"]}
        if len(hits) > 1 and len(sites) > 1:
            ambiguous += 1          # same name, different sites -> refuse to guess
            continue
        index[key] = hits[0]
    return index, ambiguous


def fetch_publishers(sb) -> list[dict]:
    """Page through every publisher lacking a channel (PostgREST caps at 1000/page)."""
    out, page = [], 0
    while True:
        rows = (sb.table("publishers").select("id,name,website,instagram")
                .is_("website", "null").is_("instagram", "null")
                .order("created_at").range(page * 1000, page * 1000 + 999)
                .execute().data or [])
        out.extend(rows)
        if len(rows) < 1000:
            return out
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap updates (0 = no cap)")
    args = ap.parse_args()

    sb = _client()
    index, ambiguous = osm_index(fetch_osm())
    print(f"[overpass] {len(index)} unique named venues with a channel "
          f"({ambiguous} ambiguous names dropped)")

    publishers = fetch_publishers(sb)
    print(f"[db] {len(publishers)} publishers currently have no channel")

    matched, updated, skipped_blank = [], 0, 0
    for pub in publishers:
        key = normalize(pub["name"])
        if not key or len(key) < 3:
            skipped_blank += 1
            continue
        hit = index.get(key)
        if hit:
            matched.append((pub, hit))

    print(f"[match] {len(matched)} publishers matched OSM "
          f"({skipped_blank} unusable names skipped)")
    for pub, hit in matched[:15]:
        print(f"    {pub['name'][:38]:38s} -> {hit['website'] or hit['instagram']}")
    if len(matched) > 15:
        print(f"    ... and {len(matched) - 15} more")

    if args.dry_run:
        print("[dry-run] no writes")
        return

    for pub, hit in matched:
        if args.limit and updated >= args.limit:
            break
        patch = {k: v for k, v in (("website", hit["website"]),
                                   ("instagram", hit["instagram"])) if v}
        sb.table("publishers").update(patch).eq("id", pub["id"]).execute()
        updated += 1
        if updated % 50 == 0:
            print(f"    ...{updated} updated")
            time.sleep(0.2)
    print(f"[done] {updated} publishers now have a channel to scout")


if __name__ == "__main__":
    main()
