"""Database access — the boundary between this agent and Pulse (contract: schema.sql).

Reads `publishers` + `discovery_requests`, writes `publisher_sources`, `scout_runs`,
and stages harvested events into `discovered_events`. Nothing here knows about the LLM.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings
from .recipes import RawEvent, Recipe

EXECUTABLE_TYPES = ("ics_feed", "jsonld", "rss", "html_selector", "embedded_json")


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


# ── Scout queue ───────────────────────────────────────────────────────────────

def scout_queue(limit: int) -> list[dict[str, Any]]:
    """Publishers worth scouting now: demand-queue matches first, then unscouted.

    A publisher qualifies if it is unscouted (or its cooldown expired) and has a
    website to look at. Instagram-only publishers are handled by triage.
    """
    sql = """
        SELECT p.id, p.kind, p.name, p.website, p.instagram, p.status,
               COALESCE(d.misses, 0) AS demand
        FROM publishers p
        LEFT JOIN (
            SELECT lower(venue) AS venue, sum(misses) AS misses
            FROM discovery_requests
            WHERE status = 'open' AND venue IS NOT NULL
            GROUP BY lower(venue)
        ) d ON d.venue = lower(p.name)
        WHERE (p.status = 'unscouted'
               OR (p.status = 'none' AND p.cooldown_until < now()))
          AND (p.website IS NOT NULL OR p.instagram IS NOT NULL)
        ORDER BY COALESCE(d.misses, 0) DESC, p.created_at
        LIMIT %(limit)s
    """
    with connect() as conn:
        return conn.execute(sql, {"limit": limit}).fetchall()


def save_scout_run(publisher_id: str, model: str, outcome: str, trace: list[dict],
                   tokens: int, usd: float, seconds: float) -> None:
    sql = """
        INSERT INTO scout_runs (publisher_id, model, outcome, trace, tokens, usd, seconds)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with connect() as conn:
        conn.execute(sql, (publisher_id, model, outcome,
                           Jsonb(json.loads(json.dumps(trace, default=str))),
                           tokens, round(usd, 6), round(seconds, 1)))
        conn.commit()


def upsert_publisher_source(publisher_id: str, recipe: Recipe) -> None:
    sql = """
        INSERT INTO publisher_sources
            (publisher_id, recipe_type, url, recipe, scope, confidence,
             is_active, last_success)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE,
                CASE WHEN %s THEN now() ELSE NULL END)
        ON CONFLICT (publisher_id, recipe_type, url) DO UPDATE SET
            recipe = EXCLUDED.recipe,
            scope = EXCLUDED.scope,
            confidence = EXCLUDED.confidence,
            is_active = TRUE,
            consecutive_failures = 0
    """
    executable = recipe.recipe_type in EXECUTABLE_TYPES
    with connect() as conn:
        conn.execute(sql, (publisher_id, recipe.recipe_type,
                           str(recipe.url) if recipe.url else None,
                           Jsonb(json.loads(recipe.model_dump_json())),
                           recipe.scope, recipe.confidence, executable))
        conn.commit()


def set_publisher_status(publisher_id: str, status: str,
                         cooldown_days: int | None = None) -> None:
    sql = """
        UPDATE publishers
        SET status = %s,
            cooldown_until = CASE WHEN %s::int IS NULL THEN NULL
                                  ELSE now() + make_interval(days => %s::int) END
        WHERE id = %s
    """
    with connect() as conn:
        conn.execute(sql, (status, cooldown_days, cooldown_days, publisher_id))
        conn.commit()


# ── Harvest ───────────────────────────────────────────────────────────────────

def active_recipes() -> list[dict[str, Any]]:
    """Executable recipes for the nightly harvest, healthiest first."""
    sql = """
        SELECT s.id AS source_id, s.publisher_id, s.recipe, s.consecutive_failures,
               p.name AS publisher_name
        FROM publisher_sources s
        JOIN publishers p ON p.id = s.publisher_id
        WHERE s.is_active AND s.recipe_type = ANY(%s)
        ORDER BY s.consecutive_failures, s.last_success DESC NULLS LAST
    """
    with connect() as conn:
        return conn.execute(sql, (list(EXECUTABLE_TYPES),)).fetchall()


def stage_events(publisher_id: str, events: list[RawEvent]) -> int:
    """Insert into the discovered_events staging table (the IP boundary). Dedup by
    (publisher, title, start_time); returns rows actually inserted."""
    sql = """
        INSERT INTO discovered_events
            (publisher_id, title, start_time, end_time, venue_name, address,
             url, description, price, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (publisher_id, title, start_time) DO NOTHING
    """
    inserted = 0
    with connect() as conn:
        for e in events:
            cur = conn.execute(sql, (
                publisher_id, e.title, e.start_time, e.end_time, e.venue_name,
                e.address, e.url, e.description, e.price,
                Jsonb(json.loads(e.model_dump_json())),
            ))
            inserted += cur.rowcount
        conn.commit()
    return inserted


def record_source_result(source_id: str, ok: bool) -> None:
    sql_ok = """UPDATE publisher_sources
                SET last_success = now(), consecutive_failures = 0 WHERE id = %s"""
    sql_fail = """UPDATE publisher_sources
                  SET consecutive_failures = consecutive_failures + 1,
                      is_active = (consecutive_failures + 1) < 5
                  WHERE id = %s"""
    with connect() as conn:
        conn.execute(sql_ok if ok else sql_fail, (source_id,))
        conn.commit()
