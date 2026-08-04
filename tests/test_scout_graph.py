"""Scout graph tests — no DB, no network, no LLM. Nodes are exercised through the
compiled LangGraph with monkeypatched boundaries (sniff, investigate, execute)."""

from datetime import UTC, datetime, timedelta

import pytest

from discovery_agent import graph as G
from discovery_agent.recipes import RawEvent, Recipe

FUTURE = datetime.now(tz=UTC) + timedelta(days=30)
PUB = {"id": "00000000-0000-0000-0000-000000000001", "kind": "venue",
       "name": "Testvenue", "website": "https://venue.example", "instagram": None}


def _ev(label="1"):
    # RawEvent enforces a minimum title length, so build valid titles by construction.
    return RawEvent(title=f"Konzert {label}", start_time=FUTURE)


def _program(n=3):
    """A list-shaped result: enough events to count as a full program."""
    return [_ev(i) for i in range(n)]


def test_single_event_page_is_rejected_as_program(monkeypatch):
    """A detail page carries valid Event JSON-LD but is not a program. Accepting it
    would pin the venue to one event forever."""
    detail = Recipe(recipe_type="jsonld", url="https://venue.example/events/one-show",
                    confidence=0.9)
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [detail])
    monkeypatch.setattr(G, "execute_recipe", lambda r, s: [_ev("Solo")])
    monkeypatch.setattr(G, "investigate",
                        lambda p, s, t, hints=None, deadline=None: (None, 0, 0.0))
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "none"
    assert any("not a full program" in h for h in st["hints"])


def test_unreachable_site_skips_the_llm(monkeypatch):
    """A dead domain is not a venue without a program — paying a model to retry
    a site that never loaded is pure waste."""
    def dead_sniff(website, session, trace):
        trace.append({"step": "sniff", "unreachable": True, "note": "homepage unreachable"})
        return []

    monkeypatch.setattr(G, "sniff_candidates", dead_sniff)
    monkeypatch.setattr(G, "investigate",
                        lambda *a, **k: pytest.fail("LLM called for an unreachable site"))
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "unreachable"
    assert st["recipe"].recipe_type == "none"


def test_sniff_hit_verifies_and_scouts(monkeypatch):
    recipe = Recipe(recipe_type="ics_feed", url="https://venue.example/e.ics", confidence=0.9)
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [recipe])
    monkeypatch.setattr(G, "execute_recipe", lambda r, s: [_ev("Jazz"), _ev("Kino")])
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "scouted"
    assert st["recipe"].recipe_type == "ics_feed"
    assert st["verified_events"] == 2
    assert st["usd"] == 0.0  # fast path spends no tokens


def test_failed_verify_falls_through_to_investigator_with_hint(monkeypatch):
    sniffed = Recipe(recipe_type="rss", url="https://venue.example/feed", confidence=0.9)
    investigated = Recipe(recipe_type="jsonld", url="https://venue.example/programm",
                          confidence=0.8)
    seen_hints = {}

    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [sniffed])

    def fake_investigate(publisher, session, trace, hints=None, deadline=None):
        seen_hints["hints"] = hints
        return investigated, 1000, 0.01

    monkeypatch.setattr(G, "investigate", fake_investigate)
    # rss verifies empty (publish dates in past), jsonld yields future events
    monkeypatch.setattr(G, "execute_recipe",
                        lambda r, s: _program() if r.recipe_type == "jsonld" else [])
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "scouted"
    assert st["recipe"].recipe_type == "jsonld"
    assert any("rss" in h for h in seen_hints["hints"])  # failure was fed back


def test_investigator_none_persists_none(monkeypatch):
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [])
    monkeypatch.setattr(G, "investigate", lambda p, s, t, hints=None, deadline=None: (None, 500, 0.005))
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "none"
    assert st["tokens"] == 500


def test_retry_is_bounded(monkeypatch):
    """Investigator keeps proposing a recipe that never verifies -> exactly MAX_ATTEMPTS
    investigations, then outcome none. No infinite loop."""
    calls = {"n": 0}
    bad = Recipe(recipe_type="jsonld", url="https://venue.example/x", confidence=0.9)

    def fake_investigate(publisher, session, trace, hints=None, deadline=None):
        calls["n"] += 1
        return bad, 100, 0.001

    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [])
    monkeypatch.setattr(G, "investigate", fake_investigate)
    monkeypatch.setattr(G, "execute_recipe", lambda r, s: [])
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "none"
    assert calls["n"] == G.MAX_ATTEMPTS


def test_no_website_instagram_becomes_lead():
    pub = {**PUB, "website": None, "instagram": "@testvenue"}
    st = G.scout_publisher(pub, dry_run=True)
    assert st["outcome"] == "instagram_lead"
    assert st["recipe"].recipe_type == "instagram_lead"
    assert st["recipe"].instagram_handle == "@testvenue"


def test_no_llm_mode_never_investigates(monkeypatch):
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [])
    monkeypatch.setattr(G, "investigate",
                        lambda *a, **k: pytest.fail("LLM called in --no-llm mode"))
    st = G.scout_publisher(PUB, dry_run=True, llm_enabled=False)
    assert st["outcome"] == "none"


def test_graph_compiles():
    assert G.build_graph() is not None


def test_rejected_free_candidate_falls_through_to_the_next_free_one(monkeypatch):
    """The cost bug this fixes: a stale RSS feed was the only candidate considered,
    so its rejection sent the run to the paid model even though a working
    embedded_json program sat one rung lower on the same free ladder."""
    stale_rss = Recipe(recipe_type="rss", url="https://venue.example/rss", confidence=0.9)
    payload = Recipe(recipe_type="embedded_json", url="https://venue.example/",
                     confidence=0.9)
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [stale_rss, payload])
    monkeypatch.setattr(G, "execute_recipe",
                        lambda r, s: _program() if r.recipe_type == "embedded_json" else [])
    monkeypatch.setattr(G, "investigate",
                        lambda *a, **k: pytest.fail("paid model used while a free "
                                                    "candidate was still untried"))
    st = G.scout_publisher(PUB, dry_run=True)
    assert st["outcome"] == "scouted"
    assert st["recipe"].recipe_type == "embedded_json"
    assert st["usd"] == 0.0
