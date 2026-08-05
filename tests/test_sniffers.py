"""Sniffer tests — fake FetchSession, no network."""

from discovery_agent.guards import FetchRefused
from discovery_agent.sniffers import declared_feeds, find_program_links, sniff

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Konzert im Hof
DTSTART:20990901T200000
END:VEVENT
END:VCALENDAR"""

HOME_WITH_FEED = """<html><head>
<link rel="alternate" type="text/calendar" href="/events.ics">
</head><body><a href="/programm">Programm</a></body></html>"""

HOME_PLAIN = """<html><body>
<a href="/ueber-uns">Über uns</a>
<a href="https://venue.example/programm">Programm</a>
<a href="https://other.example/x">Partner</a>
</body></html>"""

# A real program page lists several events; one event alone is a DETAIL page.
PROGRAM_JSONLD = """<html><body>
<script type="application/ld+json">
[{"@type":"MusicEvent","name":"Late Night Jazz","startDate":"2099-09-05T21:00:00+02:00"},
 {"@type":"MusicEvent","name":"Soul Sunday","startDate":"2099-09-07T20:00:00+02:00"},
 {"@type":"Event","name":"Lesung","startDate":"2099-09-09T19:00:00+02:00"}]
</script></body></html>"""

DETAIL_JSONLD = """<html><body>
<script type="application/ld+json">
{"@type":"MusicEvent","name":"Nur ein Konzert","startDate":"2099-09-05T21:00:00+02:00"}
</script></body></html>"""


class FakeSession:
    """Serves a canned url->content map through the guarded_fetch interface."""

    def __init__(self, pages):
        self.pages = pages
        self.fetches = 0

    def guarded_fetch(self, url):
        self.fetches += 1
        if url not in self.pages:
            raise FetchRefused(f"404 {url}")

        class R:
            text = self.pages[url]
        return R()


def test_declared_feed_wins():
    session = FakeSession({
        "https://venue.example": HOME_WITH_FEED,
        "https://venue.example/events.ics": ICS,
    })
    trace = []
    recipe = sniff("https://venue.example", session, trace)
    assert recipe is not None
    assert recipe.recipe_type == "ics_feed"
    assert str(recipe.url) == "https://venue.example/events.ics"


def test_program_page_jsonld_found():
    session = FakeSession({
        "https://venue.example": HOME_PLAIN,
        "https://venue.example/programm": PROGRAM_JSONLD,
    })
    trace = []
    recipe = sniff("https://venue.example", session, trace)
    assert recipe is not None
    assert recipe.recipe_type == "jsonld"
    assert str(recipe.url) == "https://venue.example/programm"


def test_single_event_detail_page_is_not_a_program():
    session = FakeSession({
        "https://venue.example": HOME_PLAIN,
        "https://venue.example/programm": DETAIL_JSONLD,
    })
    trace = []
    assert sniff("https://venue.example", session, trace) is None
    assert any(s.get("events_found") == 1 for s in trace)  # seen, but rejected


def test_no_channel_returns_none_with_trace():
    session = FakeSession({"https://venue.example": "<html><body>nur Bilder</body></html>"})
    trace = []
    assert sniff("https://venue.example", session, trace) is None
    assert any(s.get("note", "").startswith("no structured channel") for s in trace)


def test_program_links_stay_on_site_and_https():
    links = find_program_links(HOME_PLAIN, "https://venue.example")
    assert links == ["https://venue.example/programm"]  # off-site + non-matching dropped


def test_program_links_reject_lookalike_hosts():
    """The old check was `base_host in host`, a substring test: both of these
    passed it and got fetched as if they were the venue's own program page."""
    html = """<html><body>
    <a href="https://notvenue.example/programm">Programm</a>
    <a href="https://venue.example.attacker.com/programm">Programm</a>
    <a href="https://www.venue.example/programm">Programm</a>
    </body></html>"""
    assert find_program_links(html, "https://venue.example") == [
        "https://www.venue.example/programm",  # a real subdomain still qualifies
    ]


def test_declared_feeds_parses_link_tags():
    feeds = declared_feeds(HOME_WITH_FEED, "https://venue.example")
    assert feeds == [("ics_feed", "https://venue.example/events.ics")]
