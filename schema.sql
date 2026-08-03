-- Shared contract between the Pulse product and this discovery agent.
-- The agent READS `venues`, and WRITES `events` + `venue_sources`.
-- (This mirrors the relevant subset of Pulse's schema; keep it in sync.)

CREATE TABLE IF NOT EXISTS venues (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    lat              DECIMAL(10, 7),
    lng              DECIMAL(10, 7),
    neighborhood     TEXT,
    address          TEXT,
    venue_type       TEXT,             -- club, bar, gallery, market, ...
    website_url      TEXT,
    instagram_handle TEXT,
    created_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (name)
);

-- The agent's memory: how (and where) to find a venue's events. One row per channel.
CREATE TABLE IF NOT EXISTS venue_sources (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id      UUID NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    channel_type  TEXT NOT NULL,       -- website | events_page | instagram | resident_advisor | eventbrite | telegram | none
    url           TEXT,                -- where to look
    scrape_recipe JSONB,               -- how to extract (selectors / api ids / notes) for the cheap re-scraper
    confidence    DECIMAL(3,2),        -- 0.0–1.0 the agent's confidence this channel works
    last_checked  TIMESTAMPTZ,         -- when it was last (re)scouted / scraped
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (venue_id, channel_type)
);
CREATE INDEX IF NOT EXISTS venue_sources_venue_idx ON venue_sources (venue_id);

CREATE TABLE IF NOT EXISTS events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    venue_id     UUID REFERENCES venues(id) ON DELETE SET NULL,
    venue_name   TEXT NOT NULL,
    start_time   TIMESTAMPTZ NOT NULL,
    end_time     TIMESTAMPTZ,
    description  TEXT,
    price        TEXT,
    category     TEXT,
    source       TEXT NOT NULL,        -- which venue_source / channel produced it
    source_url   TEXT,
    fingerprint  TEXT UNIQUE,          -- dedup: hash(lower(title)+venue+date)
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_venue_idx ON events (venue_id);
CREATE INDEX IF NOT EXISTS events_time_idx  ON events (start_time);

-- ── Publisher-discovery contract v2 (discovery-agent change) ─────────────────
-- Mirrors the production migration `publisher_discovery_contract` (2026-08-02).

CREATE TABLE IF NOT EXISTS publishers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           TEXT NOT NULL CHECK (kind IN ('venue','organizer','curator')),
    name           TEXT NOT NULL,
    venue_id       UUID REFERENCES venues(id) ON DELETE SET NULL,
    website        TEXT,
    instagram      TEXT,
    category       TEXT,             -- OSM-derived: nightclub, theatre, museum, bar, ...
    status         TEXT NOT NULL DEFAULT 'unscouted'
                   CHECK (status IN ('unscouted','scouted','none','closed')),
    cooldown_until TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS publisher_sources (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_id          UUID NOT NULL REFERENCES publishers(id) ON DELETE CASCADE,
    recipe_type           TEXT NOT NULL CHECK (recipe_type IN
                          ('ics_feed','jsonld','rss','html_selector',
                           'aggregator_covered','instagram_lead','none')),
    url                   TEXT,
    recipe                JSONB,
    scope                 TEXT,
    confidence            DECIMAL(3,2),
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    last_success          TIMESTAMPTZ,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (publisher_id, recipe_type, url)
);

CREATE TABLE IF NOT EXISTS scout_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_id UUID REFERENCES publishers(id) ON DELETE CASCADE,
    model        TEXT,
    outcome      TEXT,
    trace        JSONB,
    tokens       INTEGER,
    usd          NUMERIC(10,6),
    seconds      NUMERIC(8,1),
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS discovered_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_id UUID REFERENCES publishers(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    start_time   TIMESTAMPTZ,
    end_time     TIMESTAMPTZ,
    venue_name   TEXT,
    address      TEXT,
    url          TEXT,
    description  TEXT,
    price        TEXT,
    raw          JSONB,
    ingested     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (publisher_id, title, start_time)
);

CREATE TABLE IF NOT EXISTS discovery_requests (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind         TEXT NOT NULL DEFAULT 'chat_miss',
    query        TEXT,
    venue        TEXT,
    neighborhood TEXT,
    misses       INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'open',
    first_seen   TIMESTAMPTZ DEFAULT now(),
    last_seen    TIMESTAMPTZ DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (kind, venue, query)
);
