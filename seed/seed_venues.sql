-- Sample venues so the demo runs standalone (no real data needed).
-- A deliberately mixed set: website-with-events, Instagram-only, RA-listed, and an unknown.

INSERT INTO venues (name, neighborhood, venue_type, website_url, instagram_handle) VALUES
  ('Klunkerkranich',  'Neukölln',    'bar',     'https://klunkerkranich.org',        'klunkerkranich'),
  ('SchwuZ',          'Neukölln',    'club',    'https://schwuz.de',                 'schwuz'),
  ('Markthalle Neun', 'Kreuzberg',   'market',  'https://markthalleneun.de',         'markthalleneun'),
  ('Sameheads',       'Neukölln',    'bar',     NULL,                                'sameheads'),
  ('About Blank',     'Friedrichsh.','club',    'https://aboutparty.net',            'aboutblank_berlin')
ON CONFLICT (name) DO NOTHING;
