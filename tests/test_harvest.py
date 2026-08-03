"""Harvest parser tests — realistic fixtures, no network."""

from datetime import UTC, datetime

from discovery_agent.harvest import parse_html_selector, parse_ics, parse_jsonld, parse_rss
from discovery_agent.recipes import Recipe, SelectorParams, future_events

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Jazz Session im Keller
DTSTART:20990812T200000
DTEND:20990812T230000
LOCATION:Revaler Str. 99\\, Berlin
DESCRIPTION:Offene Session\\, alle willkommen
END:VEVENT
BEGIN:VEVENT
SUMMARY:Flohmarkt
DTSTART;VALUE=DATE:20990816
END:VEVENT
END:VCALENDAR"""

JSONLD_HTML = """<html><head>
<script type="application/ld+json" data-x="1">
{"@context":"https://schema.org","@graph":[{"@type":"MusicEvent",
"name":"Kantine Konzert: Indie Night","startDate":"2099-08-14T20:00:00+02:00",
"endDate":"2099-08-14T23:00:00+02:00",
"location":{"@type":"Place","name":"Kantine am Berghain",
"address":{"streetAddress":"Am Wriezener Bahnhof","addressLocality":"Berlin"}},
"offers":{"@type":"Offer","price":"15.00"},
"description":"<p>Live indie &amp; pop.</p>"}]}
</script></head><body>x</body></html>"""

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Venue</title>
<item><title>Neues Programm im August</title>
<pubDate>Mon, 04 Aug 2099 10:00:00 +0200</pubDate>
<link>https://venue.example/news/august</link>
<description>Unser Programm</description></item></channel></rss>"""

SELECTOR_HTML = """<html><body><div class="events">
<article class="event-card"><h3>Open Air Kino: Metropolis</h3>
<time datetime="2099-08-20T21:30:00+02:00">20.8.</time>
<a href="/events/metropolis">mehr</a></article>
<article class="event-card"><h3>Kiezkonzert</h3>
<time datetime="2099-08-22T19:00:00+02:00">22.8.</time>
<a href="/events/kiezkonzert">mehr</a></article>
<article class="event-card"><h3>Kaputt (kein Datum)</h3></article>
</div></body></html>"""


def test_ics_parses_timed_and_allday_events():
    evs = parse_ics(ICS)
    assert len(evs) == 2
    jazz = evs[0]
    assert jazz.title == "Jazz Session im Keller"
    assert jazz.start_time.tzinfo is not None  # naive ICS time -> Berlin tz
    assert jazz.address and "Revaler" in jazz.address
    assert evs[1].title == "Flohmarkt"  # all-day VALUE=DATE handled


def test_jsonld_graph_event_with_nested_location_and_offer():
    evs = parse_jsonld(JSONLD_HTML, base_url="https://kantine.example/programm")
    assert len(evs) == 1
    ev = evs[0]
    assert ev.title == "Kantine Konzert: Indie Night"
    assert ev.venue_name == "Kantine am Berghain"
    assert ev.price == "15.00"
    assert "Live indie & pop." == ev.description  # tags stripped, entities decoded
    assert ev.start_time.utcoffset() is not None


def test_rss_items_parse():
    evs = parse_rss(RSS)
    assert len(evs) == 1
    assert evs[0].title == "Neues Programm im August"
    assert evs[0].url == "https://venue.example/news/august"


def test_html_selector_with_time_datetime_default():
    recipe = Recipe(recipe_type="html_selector", url="https://venue.example/events",
                    confidence=0.9,
                    params=SelectorParams(item_selector="article.event-card",
                                          title_selector="h3"))
    evs = parse_html_selector(SELECTOR_HTML, recipe, "https://venue.example/events")
    assert [e.title for e in evs] == ["Open Air Kino: Metropolis", "Kiezkonzert"]
    assert evs[0].url == "https://venue.example/events/metropolis"
    # the dateless item is skipped, not fabricated


def test_future_events_gate():
    evs = parse_jsonld(JSONLD_HTML)
    assert future_events(evs, datetime(2099, 8, 13, tzinfo=UTC))  # before -> passes
    assert not future_events(evs, datetime(2099, 8, 15, tzinfo=UTC))  # after -> empty


def test_malformed_content_yields_empty_not_crash():
    assert parse_ics("not an ics") == []
    assert parse_rss("<broken") == []
    assert parse_jsonld("<script type='application/ld+json'>{bad json}</script>") == []
