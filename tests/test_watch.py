"""The live-narration path: steps must stream as they happen, not at the end."""

from datetime import UTC, datetime, timedelta

from discovery_agent import graph as G
from discovery_agent.main import _render
from discovery_agent.recipes import RawEvent, Recipe

FUTURE = datetime.now(tz=UTC) + timedelta(days=30)
PUB = {"id": "00000000-0000-0000-0000-000000000001", "kind": "venue",
       "name": "Testvenue", "website": "https://venue.example", "instagram": None}


def test_steps_stream_during_the_run_not_after(monkeypatch):
    """The callback must fire while the graph is still running — a progress
    display that only appears at the end is not progress."""
    seen = []
    recipe = Recipe(recipe_type="ics_feed", url="https://venue.example/e.ics", confidence=0.9)

    def sniff_and_check(website, session, trace):
        trace.append({"step": "sniff_hit", "type": "ics_feed", "url": str(recipe.url)})
        # by now the callback must already have received triage AND this step
        assert [s.get("step") for s in seen] == ["triage", "sniff_hit"]
        return [recipe]

    monkeypatch.setattr(G, "sniff_candidates", sniff_and_check)
    monkeypatch.setattr(G, "execute_recipe",
                        lambda r, s: [RawEvent(title=f"Show {i}", start_time=FUTURE)
                                      for i in range(3)])
    state = G.scout_publisher(PUB, dry_run=True, on_step=seen.append)
    assert state["outcome"] == "scouted"
    assert [s.get("step") for s in seen][-1] == "persist"


def test_a_broken_renderer_cannot_kill_a_run(monkeypatch):
    """Display is not allowed to cost a paid scout run."""
    monkeypatch.setattr(G, "sniff_candidates", lambda w, s, t: [])
    monkeypatch.setattr(G, "investigate",
                        lambda p, s, t, hints=None, deadline=None: (None, 0, 0.0))

    def exploding(_step):
        raise RuntimeError("render bug")

    state = G.scout_publisher(PUB, dry_run=True, llm_enabled=False, on_step=exploding)
    assert state["outcome"] == "none"


def test_render_handles_every_step_kind():
    """_render must never raise on a trace step, including unknown ones."""
    for step in [
        {"step": "triage", "publisher": "V", "website": None},
        {"step": "sniff_parse", "type": "rss", "url": "u", "events_found": 0},
        {"step": "sniff_hit", "type": "jsonld", "url": "u"},
        {"step": "sniff", "note": "homepage unreachable", "unreachable": True},
        {"step": "fetch", "url": "u", "ok": False},
        {"step": "propose", "args": {"recipe_type": "rss", "confidence": 0.5}},
        {"step": "propose_invalid", "error": "bad"},
        {"step": "verify", "events": 3, "future_events": 3, "needed": 3},
        {"step": "verify_error", "error": "boom"},
        {"step": "abort", "reason": "usd budget"},
        {"step": "llm_error", "error": "429"},
        {"step": "persist", "outcome": "none", "fetches": 1, "tokens": 0, "usd": 0.0},
        {"step": "something_new_later"},
    ]:
        _render(step)
