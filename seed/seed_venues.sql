-- Sample venues so the demo runs standalone (no real data needed).
-- A deliberately mixed set: website-with-events, Instagram-only, RA-listed, and an unknown.

INSERT INTO venues (name, neighborhood, venue_type, website_url, instagram_handle) VALUES
  ('Klunkerkranich',  'Neukölln',    'bar',     'https://klunkerkranich.org',        'klunkerkranich'),
  ('SchwuZ',          'Neukölln',    'club',    'https://schwuz.de',                 'schwuz'),
  ('Markthalle Neun', 'Kreuzberg',   'market',  'https://markthalleneun.de',         'markthalleneun'),
  ('Sameheads',       'Neukölln',    'bar',     NULL,                                'sameheads'),
  ('About Blank',     'Friedrichsh.','club',    'https://aboutparty.net',            'aboutblank_berlin')
ON CONFLICT (name) DO NOTHING;

-- Publishers for the demo: every sample venue + one wandering organizer + a demand entry.
INSERT INTO publishers (kind, name, venue_id, website)
SELECT 'venue', v.name, v.id, v.website_url FROM venues v
ON CONFLICT (kind, name) DO NOTHING;

INSERT INTO publishers (kind, name, website)
VALUES ('organizer', 'Nachtflohmarkt Kollektiv', 'https://example-kollektiv.de')
ON CONFLICT (kind, name) DO NOTHING;

INSERT INTO discovery_requests (kind, venue, query)
VALUES ('chat_miss', 'Sameheads', 'electronic music')
ON CONFLICT (kind, venue, query) DO NOTHING;
