"""The discovery scout as a LangGraph state machine (spec: Hybrid scout).

    triage ──► sniff ──► verify ──► persist          (deterministic fast path)
       │          │         │
       │          └──► investigate ──► verify        (bounded LLM slow path)
       │                    ▲            │
       │                    └── retry ───┘           (one retry on failed verify)
       └──► persist                                  (no website / instagram-only)

Every run ends in persist: a publisher_sources row (or a `none` marker with
cooldown) plus a scout_runs audit row with the full trace and spend.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from . import db, observability
from .config import settings
from .guards import FetchSession
from .harvest import execute_recipe
from .investigator import investigate
from .recipes import BERLIN, Recipe, future_events
from .sniffers import MIN_PROGRAM_EVENTS, sniff

MAX_ATTEMPTS = 2  # sniff counts as attempt 0; investigate may run twice


class ScoutState(TypedDict, total=False):
    publisher: dict[str, Any]
    session: FetchSession          # shared budgets across sniff/investigate/verify
    candidate: Recipe | None
    candidate_from: str            # "triage" | "sniff" | "investigate"
    recipe: Recipe | None          # verified (or marker) recipe to persist
    verified_events: int
    attempts: int
    hints: list[str]               # failed candidates, fed back to the investigator
    trace: list[dict]
    tokens: int
    usd: float
    started: float
    outcome: str                   # scouted | instagram_lead | none | error
    dry_run: bool
    llm_enabled: bool


def _now():
    from datetime import datetime
    return datetime.now(tz=BERLIN)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def triage_node(state: ScoutState) -> ScoutState:
    p = state["publisher"]
    state.setdefault("trace", []).append(
        {"step": "triage", "publisher": p["name"], "website": p.get("website")})
    state["session"] = state.get("session") or FetchSession()
    state["attempts"] = 0
    state["hints"] = []
    state["tokens"] = 0
    state["usd"] = 0.0
    state["started"] = time.monotonic()

    if not p.get("website"):
        if p.get("instagram"):
            state["recipe"] = Recipe(recipe_type="instagram_lead", confidence=0.4,
                                     instagram_handle=p["instagram"],
                                     scope="no website; Instagram lead only")
            state["outcome"] = "instagram_lead"
        else:
            state["recipe"] = Recipe(recipe_type="none", confidence=0.9,
                                     scope="no website, no instagram")
            state["outcome"] = "none"
    return state


def sniff_node(state: ScoutState) -> ScoutState:
    candidate = sniff(state["publisher"]["website"], state["session"], state["trace"])
    if candidate is None and any(t.get("unreachable") for t in state["trace"]):
        # The homepage itself never loaded — a dead domain, not a venue without a
        # program. Marked distinctly so it isn't paid for as if it were unknown.
        state["outcome"] = "unreachable"
    state["candidate"] = candidate
    state["candidate_from"] = "sniff"
    if candidate:
        state["trace"].append({"step": "sniff_hit", "type": candidate.recipe_type,
                               "url": str(candidate.url)})
    return state


def investigate_node(state: ScoutState) -> ScoutState:
    state["attempts"] = state.get("attempts", 0) + 1
    if not state.get("llm_enabled", True):
        state["trace"].append({"step": "investigate_skipped", "reason": "llm disabled"})
        state["candidate"] = None
        state["outcome"] = "none"
        return state
    deadline = state.get("started", time.monotonic()) + settings.scout_max_seconds
    recipe, tokens, usd = investigate(state["publisher"], state["session"],
                                      state["trace"], hints=state.get("hints"),
                                      deadline=deadline)
    state["tokens"] = state.get("tokens", 0) + tokens
    state["usd"] = state.get("usd", 0.0) + usd
    state["candidate"] = recipe
    state["candidate_from"] = "investigate"
    if recipe is None:
        state["outcome"] = "none"
    return state


def verify_node(state: ScoutState) -> ScoutState:
    """The gate: a recipe is only real if the HARVEST CODE, run now, yields future
    events. Markers (instagram_lead/none/aggregator_covered) skip execution."""
    candidate = state.get("candidate")
    if candidate is None:
        state["outcome"] = state.get("outcome") or "none"
        return state
    if not candidate.needs_url():
        state["recipe"] = candidate
        state["outcome"] = "instagram_lead" if candidate.recipe_type == "instagram_lead" else "none"
        return state
    try:
        events = execute_recipe(candidate, state["session"])
    except Exception as exc:  # noqa: BLE001
        events = []
        state["trace"].append({"step": "verify_error", "error": f"{type(exc).__name__}: {exc}"})
    future = future_events(events, _now())
    # Same list-shaped bar as the sniffer: a page-embedded recipe that yields one
    # event is a detail page, not a program.
    needed = 1 if candidate.recipe_type in ("ics_feed", "rss") else MIN_PROGRAM_EVENTS
    state["trace"].append({"step": "verify", "type": candidate.recipe_type,
                           "url": str(candidate.url), "events": len(events),
                           "future_events": len(future), "needed": needed})
    if len(future) >= needed:
        state["recipe"] = candidate
        state["verified_events"] = len(future)
        state["outcome"] = "scouted"
    else:
        state.setdefault("hints", []).append(
            f"{candidate.recipe_type} at {candidate.url} yielded only {len(future)} "
            f"future events on execution (need {needed}) — not a full program")
        state["candidate"] = None
    return state


def persist_node(state: ScoutState) -> ScoutState:
    p = state["publisher"]
    recipe = state.get("recipe")
    outcome = state.get("outcome") or "none"
    if recipe is None and outcome in ("none", "unreachable"):
        recipe = Recipe(
            recipe_type="none",
            confidence=0.9 if outcome == "unreachable" else 0.7,
            scope="website unreachable (dead domain / blocked)" if outcome == "unreachable"
                  else "scout found no working channel")
        state["recipe"] = recipe   # what we persist must be visible in the final state
    state["outcome"] = outcome
    seconds = time.monotonic() - state.get("started", time.monotonic())
    state["trace"].append({"step": "persist", "outcome": outcome,
                           "fetches": state["session"].fetches if state.get("session") else 0,
                           "tokens": state.get("tokens", 0),
                           "usd": round(state.get("usd", 0.0), 4)})
    if state.get("dry_run"):
        return state
    if recipe is not None:
        db.upsert_publisher_source(p["id"], recipe)
    if outcome == "scouted" or outcome == "instagram_lead":
        db.set_publisher_status(p["id"], "scouted")
    else:
        db.set_publisher_status(p["id"], "none", cooldown_days=settings.none_cooldown_days)
    db.save_scout_run(p["id"], settings.scout_model, outcome, state["trace"],
                      state.get("tokens", 0), state.get("usd", 0.0), seconds)
    return state


# ── Wiring ────────────────────────────────────────────────────────────────────

def _after_triage(state: ScoutState) -> str:
    return "persist" if state.get("recipe") else "sniff"


def _after_sniff(state: ScoutState) -> str:
    if state.get("candidate"):
        return "verify"
    if state.get("outcome") == "unreachable":
        return "persist"   # the LLM can't fetch what the wall couldn't reach either
    return "investigate"


def _after_investigate(state: ScoutState) -> str:
    return "verify" if state.get("candidate") else "persist"


def _after_verify(state: ScoutState) -> str:
    if state.get("recipe"):
        return "persist"
    if state.get("attempts", 0) < MAX_ATTEMPTS and state.get("llm_enabled", True):
        return "investigate"   # one more try, now with failure hints
    state["outcome"] = "none"
    return "persist"


def build_graph():
    g = StateGraph(ScoutState)
    g.add_node("triage", triage_node)
    g.add_node("sniff", sniff_node)
    g.add_node("investigate", investigate_node)
    g.add_node("verify", verify_node)
    g.add_node("persist", persist_node)
    g.set_entry_point("triage")
    g.add_conditional_edges("triage", _after_triage, {"persist": "persist", "sniff": "sniff"})
    g.add_conditional_edges("sniff", _after_sniff,
                            {"verify": "verify", "investigate": "investigate",
                             "persist": "persist"})
    g.add_conditional_edges("investigate", _after_investigate,
                            {"verify": "verify", "persist": "persist"})
    g.add_conditional_edges("verify", _after_verify,
                            {"persist": "persist", "investigate": "investigate"})
    g.add_edge("persist", END)
    return g.compile()


class LiveTrace(list):
    """A trace list that reports each step the moment it is recorded.

    The nodes already append every decision here, so watching a run live needs no
    changes to node logic — only a list that calls back on append.
    """

    def __init__(self, on_step):
        super().__init__()
        self._on_step = on_step

    def append(self, step):
        super().append(step)
        try:
            self._on_step(step)
        except Exception:  # noqa: BLE001 — a display bug must not kill a scout run
            pass


def scout_publisher(publisher: dict[str, Any], *, dry_run: bool = False,
                    llm_enabled: bool = True, on_step=None) -> ScoutState:
    graph = build_graph()
    trace = LiveTrace(on_step) if on_step else []
    with observability.scout_span(publisher) as span:
        state = graph.invoke({"publisher": publisher, "trace": trace, "dry_run": dry_run,
                              "llm_enabled": llm_enabled},
                             {"recursion_limit": 15})
        recipe = state.get("recipe")
        span.update(output={
            "outcome": state.get("outcome"),
            "recipe_type": recipe.recipe_type if recipe else None,
            "recipe_url": str(recipe.url) if recipe and recipe.url else None,
            "verified_events": state.get("verified_events", 0),
            "fetches": state["session"].fetches if state.get("session") else 0,
            "tokens": state.get("tokens", 0),
            "usd": round(state.get("usd", 0.0), 6),
        })
        return state


def run(limit: int | None = None, *, dry_run: bool = False, llm_enabled: bool = True,
        categories: list[str] | None = None, on_result=None) -> list[ScoutState]:
    """Scout the queue. Returns final states (one per publisher).

    `on_result` is called as each publisher finishes so a long run can report
    progress instead of going silent for an hour.
    """
    publishers = db.scout_queue(limit or settings.run_max_publishers, categories)
    results = []
    for pub in publishers:
        try:
            state = scout_publisher(pub, dry_run=dry_run, llm_enabled=llm_enabled)
        except Exception as exc:  # noqa: BLE001 — one publisher never kills the run
            print(f"[scout] ERROR on {pub['name']}: {type(exc).__name__}: {exc}", flush=True)
            continue
        results.append(state)
        if on_result:
            on_result(state)
    return results
