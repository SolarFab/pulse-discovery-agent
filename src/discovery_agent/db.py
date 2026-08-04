"""The data boundary between this agent and Pulse (contract: schema.sql).

Two interchangeable backends behind one API:

  * store_postgres — psycopg against any Postgres, incl. the repo's docker demo DB.
    This is the default and keeps the project independently runnable.
  * store_supabase — PostgREST via the service key, used when SUPABASE_URL and
    SUPABASE_SERVICE_KEY are set. Needed for the hosted contract, where no Postgres
    password exists.

Backend choice is config, never a call-site concern: graph.py and main.py import
these functions and stay ignorant of where the rows live.
"""

from __future__ import annotations

from typing import Any

from . import store_postgres
from .config import settings
from .recipes import RawEvent, Recipe

EXECUTABLE_TYPES = store_postgres.EXECUTABLE_TYPES


def _store():
    if settings.use_supabase:
        from . import store_supabase
        return store_supabase
    return store_postgres


def backend_name() -> str:
    return "supabase" if settings.use_supabase else "postgres"


# The workshop's "50 mixed venues": event-likely categories first, plus bars/pubs
# to measure the low end honestly rather than quietly excluding it.
PILOT_MIX = ["nightclub", "theatre", "music_venue", "events_venue", "arts_centre",
             "cinema", "gallery", "museum", "community_centre", "bar", "pub"]


def scout_queue(limit: int, categories: list[str] | None = None) -> list[dict[str, Any]]:
    if categories:
        store = _store()
        if not hasattr(store, "stratified_queue"):
            raise NotImplementedError(
                "category-stratified sampling needs the Supabase store "
                "(publishers.category is not populated in the local demo DB)")
        return store.stratified_queue(limit, categories)
    return _store().scout_queue(limit)


def find_publishers(name: str, limit: int = 8) -> list[dict[str, Any]]:
    store = _store()
    if not hasattr(store, "find_publishers"):
        raise NotImplementedError("name search needs the Supabase store")
    return store.find_publishers(name, limit)


def save_scout_run(publisher_id: str, model: str, outcome: str, trace: list[dict],
                   tokens: int, usd: float, seconds: float) -> None:
    _store().save_scout_run(publisher_id, model, outcome, trace, tokens, usd, seconds)


def upsert_publisher_source(publisher_id: str, recipe: Recipe) -> None:
    _store().upsert_publisher_source(publisher_id, recipe)


def set_publisher_status(publisher_id: str, status: str,
                         cooldown_days: int | None = None) -> None:
    _store().set_publisher_status(publisher_id, status, cooldown_days)


def active_recipes() -> list[dict[str, Any]]:
    return _store().active_recipes()


def stage_events(publisher_id: str, events: list[RawEvent]) -> int:
    return _store().stage_events(publisher_id, events)


def record_source_result(source_id: str, ok: bool) -> None:
    _store().record_source_result(source_id, ok)
