-- Workshop repair F3: exact/partial TITLE matches rank first, before vector ranking.
-- Evidence: "Meanwhile in Berlin" — a user asked for an event BY NAME; vector-only
-- ranking cannot do lexical lookup (and an unembedded event is unreachable by query
-- entirely). This is the light remedy reserved by the Experiment-2 decision log for
-- exactly this failure ("name misses in prod"); full BM25 fusion stays unnecessary.

DROP FUNCTION IF EXISTS match_events;

CREATE OR REPLACE FUNCTION match_events(
    query_embedding  TEXT DEFAULT NULL,
    p_query_text     TEXT DEFAULT NULL,           -- raw query for lexical title boost
    p_category       TEXT DEFAULT NULL,
    p_subcategory    TEXT DEFAULT NULL,
    p_date_from      TIMESTAMPTZ DEFAULT now(),
    p_date_to        TIMESTAMPTZ DEFAULT now() + INTERVAL '14 days',
    p_neighborhood   TEXT DEFAULT NULL,
    p_venue          TEXT DEFAULT NULL,
    p_family         BOOLEAN DEFAULT FALSE,
    p_outdoor        BOOLEAN DEFAULT FALSE,
    p_free           BOOLEAN DEFAULT FALSE,
    p_max_price_cents INTEGER DEFAULT NULL,
    p_lat            DOUBLE PRECISION DEFAULT NULL,
    p_lng            DOUBLE PRECISION DEFAULT NULL,
    p_radius_km      DOUBLE PRECISION DEFAULT 1.5,
    p_limit          INTEGER DEFAULT 10
)
RETURNS TABLE (
    id UUID, title TEXT, venue_name TEXT, start_time TIMESTAMPTZ,
    category TEXT, subcategory TEXT, price TEXT, neighborhood TEXT,
    distance_km DOUBLE PRECISION
)
LANGUAGE sql STABLE AS $$
    WITH base AS (
        SELECT e.*,
            CASE WHEN p_lat IS NOT NULL AND e.lat IS NOT NULL THEN
                6371 * acos(least(1.0,
                    cos(radians(p_lat)) * cos(radians(e.lat::float8)) *
                    cos(radians(e.lng::float8) - radians(p_lng)) +
                    sin(radians(p_lat)) * sin(radians(e.lat::float8))))
            END AS dist_km
        FROM events e
        WHERE e.is_active
          AND e.start_time >= p_date_from
          AND e.start_time <= p_date_to
          AND (p_category     IS NULL OR e.category = p_category)
          AND (p_subcategory  IS NULL OR e.subcategory = p_subcategory)
          AND (p_neighborhood IS NULL OR e.neighborhood ILIKE '%' || p_neighborhood || '%')
          AND (p_venue        IS NULL OR e.venue_name ILIKE '%' || p_venue || '%')
          AND (NOT p_family  OR e.family_friendly)
          AND (NOT p_outdoor OR e.outdoor)
          AND (NOT p_free    OR e.free_entry)
          AND (p_max_price_cents IS NULL OR e.price_cents IS NULL
               OR e.price_cents <= p_max_price_cents)
    )
    SELECT b.id, b.title, b.venue_name, b.start_time, b.category, b.subcategory,
           b.price, b.neighborhood, b.dist_km
    FROM base b
    WHERE (p_lat IS NULL OR (b.dist_km IS NOT NULL AND b.dist_km <= p_radius_km))
    ORDER BY
        -- lexical title hit trumps everything (works even for unembedded events)
        CASE WHEN p_query_text IS NOT NULL AND length(p_query_text) >= 4
                  AND b.title ILIKE '%' || p_query_text || '%' THEN 0 ELSE 1 END,
        CASE WHEN query_embedding IS NOT NULL
             THEN b.embedding <=> query_embedding::vector(1536) END ASC NULLS LAST,
        CASE WHEN query_embedding IS NULL AND p_lat IS NOT NULL THEN b.dist_km END ASC NULLS LAST,
        b.start_time ASC
    LIMIT least(greatest(p_limit, 1), 20)
$$;

GRANT EXECUTE ON FUNCTION match_events TO anon, authenticated;
