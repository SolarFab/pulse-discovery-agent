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
