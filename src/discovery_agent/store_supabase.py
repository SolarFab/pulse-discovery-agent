"""Supabase (PostgREST) store — the hosted contract, no Postgres password required.

Same public surface as store_postgres, expressed in PostgREST calls. The service key
already grants table access, so the agent needs no additional secret to run against
the real publisher set. Queries that Postgres would express as one JOIN are split
here and merged in Python; `discovery_requests` is small enough that this is cheap.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from supabase import Client, create_client

from .config import settings
from .recipes import RawEvent, Recipe

EXECUTABLE_TYPES = ("ics_feed", "jsonld", "rss", "html_selector")
MAX_FAILURES = 5


def _client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


# ── Scout queue ───────────────────────────────────────────────────────────────

def _eligible(query):
    """status = unscouted, or a `none` verdict whose cooldown has expired."""
    return query.or_(f"status.eq.unscouted,and(status.eq.none,cooldown_until.lt.{_now_iso()})")


def _has_channel(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("website") or r.get("instagram")]


def _backlog(sb, cols: str, need: int, category: str | None = None) -> list[dict]:
    """Eligible publishers that actually have something to scout.

    The channel filter must run in the DATABASE: most publishers still have no
    website, so filtering a page in Python returns nothing but empty rows.
    PostgREST allows one `or` per request, which the status filter already uses —
    hence two passes, websites first (the scoutable ones).
    """
    def q():
        query = _eligible(sb.table("publishers").select(cols))
        return query.eq("category", category) if category else query

    rows = (q().not_.is_("website", "null")
            .order("created_at").order("id").limit(need).execute().data or [])
    if len(rows) < need and not category:
        rows += (q().is_("website", "null").not_.is_("instagram", "null")
                 .order("created_at").order("id").limit(need - len(rows))
                 .execute().data or [])
    return rows


def stratified_queue(limit: int, categories: list[str]) -> list[dict[str, Any]]:
    """Draw an even sample across categories — the workshop's '50 MIXED venues'.

    An alphabetical queue over-samples corner bars, which have no event program by
    nature; measuring the scout on those understates it and teaches nothing.
    """
    sb = _client()
    cols = "id,kind,name,website,instagram,status,category,created_at"
    per = max(1, limit // len(categories))
    picked: dict[str, dict] = {}
    for category in categories:
        for row in _backlog(sb, cols, per, category=category):
            picked.setdefault(row["id"], {**row, "demand": 0})
    return sorted(picked.values(), key=lambda r: (r.get("category") or "", r["id"]))[:limit]


def scout_queue(limit: int) -> list[dict[str, Any]]:
    """Demand-queue matches first (chat misses), then the oldest unscouted publishers."""
    sb = _client()
    cols = "id,kind,name,website,instagram,status,created_at"

    demand: dict[str, int] = {}
    requests = (sb.table("discovery_requests").select("venue,misses")
                .eq("status", "open").not_.is_("venue", "null").execute().data or [])
    for row in requests:
        name = (row.get("venue") or "").strip().lower()
        if name:
            demand[name] = demand.get(name, 0) + (row.get("misses") or 1)

    picked: dict[str, dict] = {}
    # 1. Publishers people actually asked for, most-missed first.
    for name, misses in sorted(demand.items(), key=lambda kv: -kv[1]):
        if len(picked) >= limit:
            break
        rows = _eligible(sb.table("publishers").select(cols)).ilike("name", name).limit(3)
        for row in _has_channel(rows.execute().data or []):
            picked.setdefault(row["id"], {**row, "demand": misses})

    # 2. Fill the rest from the backlog.
    if len(picked) < limit:
        for row in _backlog(sb, cols, limit - len(picked) + 5):
            if len(picked) >= limit:
                break
            picked.setdefault(row["id"], {**row, "demand": 0})

    # created_at ties are common (the seed inserted in one transaction), so id breaks
    # them — batches must be reproducible for the pilot to be resumable.
    return sorted(picked.values(),
                  key=lambda r: (-r["demand"], r.get("created_at") or "", r["id"]))[:limit]


def save_scout_run(publisher_id: str, model: str, outcome: str, trace: list[dict],
                   tokens: int, usd: float, seconds: float) -> None:
    _client().table("scout_runs").insert({
        "publisher_id": publisher_id, "model": model, "outcome": outcome,
        "trace": json.loads(json.dumps(trace, default=str)),
        "tokens": tokens, "usd": round(usd, 6), "seconds": round(seconds, 1),
    }).execute()


def upsert_publisher_source(publisher_id: str, recipe: Recipe) -> None:
    row = {
        "publisher_id": publisher_id,
        "recipe_type": recipe.recipe_type,
        "url": str(recipe.url) if recipe.url else None,
        "recipe": json.loads(recipe.model_dump_json()),
        "scope": recipe.scope,
        "confidence": recipe.confidence,
        "is_active": True,
        "consecutive_failures": 0,
    }
    if recipe.recipe_type in EXECUTABLE_TYPES:
        row["last_success"] = _now_iso()
    _client().table("publisher_sources").upsert(
        row, on_conflict="publisher_id,recipe_type,url").execute()


def set_publisher_status(publisher_id: str, status: str,
                         cooldown_days: int | None = None) -> None:
    patch: dict[str, Any] = {"status": status, "cooldown_until": None}
    if cooldown_days is not None:
        from datetime import timedelta
        patch["cooldown_until"] = (datetime.now(tz=UTC)
                                   + timedelta(days=cooldown_days)).isoformat()
    _client().table("publishers").update(patch).eq("id", publisher_id).execute()


# ── Harvest ───────────────────────────────────────────────────────────────────

def active_recipes() -> list[dict[str, Any]]:
    sb = _client()
    rows = (sb.table("publisher_sources")
            .select("id,publisher_id,recipe,consecutive_failures,last_success,"
                    "publishers(name)")
            .eq("is_active", True).in_("recipe_type", list(EXECUTABLE_TYPES))
            .order("consecutive_failures").execute().data or [])
    return [{
        "source_id": r["id"],
        "publisher_id": r["publisher_id"],
        "recipe": r["recipe"],
        "consecutive_failures": r["consecutive_failures"],
        "publisher_name": (r.get("publishers") or {}).get("name", "?"),
    } for r in rows if r.get("recipe")]


def stage_events(publisher_id: str, events: list[RawEvent]) -> int:
    """Insert into discovered_events (the IP boundary), ignoring duplicates.

    PostgREST returns only the rows it actually wrote, so its length IS the new count.
    """
    if not events:
        return 0
    rows = []
    for e in events:
        rows.append({
            "publisher_id": publisher_id,
            "title": e.title,
            "start_time": e.start_time.isoformat(),
            "end_time": e.end_time.isoformat() if e.end_time else None,
            "venue_name": e.venue_name, "address": e.address, "url": e.url,
            "description": e.description, "price": e.price,
            "raw": json.loads(e.model_dump_json()),
        })
    res = (_client().table("discovered_events")
           .upsert(rows, on_conflict="publisher_id,title,start_time",
                   ignore_duplicates=True).execute())
    return len(res.data or [])


def record_source_result(source_id: str, ok: bool) -> None:
    sb = _client()
    if ok:
        sb.table("publisher_sources").update(
            {"last_success": _now_iso(), "consecutive_failures": 0}
        ).eq("id", source_id).execute()
        return
    current = (sb.table("publisher_sources").select("consecutive_failures")
               .eq("id", source_id).single().execute().data or {})
    failures = (current.get("consecutive_failures") or 0) + 1
    sb.table("publisher_sources").update(
        {"consecutive_failures": failures, "is_active": failures < MAX_FAILURES}
    ).eq("id", source_id).execute()
