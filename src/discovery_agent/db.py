"""Database access — the boundary between this agent and Pulse.

Reads `venues`, writes `venue_sources` (recipes) and `events`. Nothing here knows about the LLM.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from .config import settings


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def venues_needing_scout(limit: int) -> list[dict[str, Any]]:
    """Venues with no fresh `venue_sources` recipe — the ones worth spending the LLM on."""
    sql = """
        SELECT v.id, v.name, v.neighborhood, v.venue_type, v.website_url, v.instagram_handle
        FROM venues v
        LEFT JOIN venue_sources s
          ON s.venue_id = v.id
         AND s.last_checked > now() - make_interval(days => %(days)s)
        WHERE s.id IS NULL
        GROUP BY v.id
        LIMIT %(limit)s
    """
    with connect() as conn:
        return conn.execute(
            sql, {"days": settings.scout_rescout_days, "limit": limit}
        ).fetchall()


def upsert_venue_source(source: dict[str, Any]) -> None:
    """Record what the scout learned about where a venue publishes events."""
    sql = """
        INSERT INTO venue_sources
            (venue_id, channel_type, url, scrape_recipe, confidence, last_checked, is_active)
        VALUES
            (%(venue_id)s, %(channel_type)s, %(url)s, %(scrape_recipe)s, %(confidence)s, now(), TRUE)
        ON CONFLICT (venue_id, channel_type) DO UPDATE SET
            url = EXCLUDED.url,
            scrape_recipe = EXCLUDED.scrape_recipe,
            confidence = EXCLUDED.confidence,
            last_checked = now(),
            is_active = TRUE
    """
    with connect() as conn:
        conn.execute(sql, source)
        conn.commit()
