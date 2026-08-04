"""CLI entry point.

    discovery-agent scout   [--limit N] [--mix] [--dry-run] [--no-llm]  # batch
    discovery-agent watch   "Berghain" | --url https://...       # scout ONE, live
    discovery-agent harvest                                       # run saved recipes
    discovery-agent queue                                         # show who's next
"""

from __future__ import annotations

import argparse
from datetime import datetime

from . import db, graph, observability
from .config import settings
from .guards import FetchRefused, FetchSession
from .harvest import execute_recipe
from .recipes import BERLIN, Recipe, future_events


def _say(msg: str) -> None:
    """Progress must appear as it happens: a scout run takes minutes per publisher,
    and Python block-buffers stdout when it is piped or redirected."""
    print(msg, flush=True)


# ── watch: point the scout at ONE publisher and narrate it ───────────────────

def _render(step: dict) -> None:
    """One trace step -> one readable line. The scout already records every
    decision it makes; this only makes that record legible as it happens."""
    kind = step.get("step")
    if kind == "triage":
        _say(f"  · looking at {step.get('publisher')}  ({step.get('website') or 'no website'})")
    elif kind == "sniff_parse":
        n = step.get("events_found", 0)
        verdict = "no events" if not n else f"{n} event(s)"
        _say(f"  · probing {step.get('type'):<13} {step.get('url')}  -> {verdict}")
    elif kind == "sniff_hit":
        _say(f"  ✓ deterministic hit: {step.get('type')} at {step.get('url')}  (0 tokens)")
    elif kind == "sniff":
        note = step.get("note", "")
        if step.get("unreachable"):
            _say(f"  ✗ {note} — skipping the model, it cannot fetch what the wall could not")
        elif note:
            _say(f"  · {note}")
    elif kind == "fetch":
        _say(f"  · [model] fetched {step.get('url')}"
             + ("" if step.get("ok") else "   (failed)"))
    elif kind == "propose":
        args_ = step.get("args") or {}
        _say(f"  · [model] proposes {args_.get('recipe_type')} "
             f"{args_.get('url') or args_.get('instagram_handle') or ''} "
             f"(confidence {args_.get('confidence')})")
    elif kind == "propose_invalid":
        _say(f"  ✗ rejected by the schema: {str(step.get('error'))[:90]}")
    elif kind == "verify":
        n, need = step.get("future_events", 0), step.get("needed", 1)
        ok = n >= need
        _say(f"  {'✓' if ok else '✗'} verification: executed the recipe now -> "
             f"{step.get('events', 0)} event(s), {n} in the future (needs {need})")
    elif kind == "verify_error":
        _say(f"  ✗ verification error: {str(step.get('error'))[:90]}")
    elif kind == "abort":
        _say(f"  ! budget stop: {step.get('reason')}")
    elif kind == "llm_error":
        _say(f"  ! model error: {str(step.get('error'))[:90]}")
    elif kind == "persist":
        _say(f"  · done: {step.get('outcome')}  "
             f"({step.get('fetches')} fetches, {step.get('tokens')} tokens, "
             f"${step.get('usd')})")


def cmd_watch(args: argparse.Namespace) -> None:
    if args.url:
        url = args.url if "://" in args.url else "https://" + args.url
        publisher = {"id": None, "kind": "venue", "name": args.name or url,
                     "website": url, "instagram": None, "category": None}
        dry_run = True   # no DB row to attach a recipe to
        _say(f"[watch] ad-hoc URL — nothing will be written\n        {url}")
    else:
        matches = db.find_publishers(args.name)
        if not matches:
            _say(f"[watch] no publisher matching {args.name!r}. Try: discovery-agent queue")
            return
        if len(matches) > 1:
            _say(f"[watch] {len(matches)} matches for {args.name!r} — be more specific:")
            for m in matches:
                _say(f"    {m['name']}  ({m.get('category') or '—'}, "
                     f"{m.get('website') or 'no website'})")
            return
        publisher = matches[0]
        dry_run = args.dry_run
        if not publisher.get("website") and not publisher.get("instagram"):
            _say(f"[watch] {publisher['name']} has no website or Instagram — nothing to scout.")
            return
        _say(f"[watch] {publisher['name']}  ({publisher.get('category') or '—'})"
             + ("   DRY-RUN, nothing written" if dry_run else ""))

    _say(f"        model={settings.scout_model}  llm={'off' if args.no_llm else 'on'}\n")
    state = graph.scout_publisher(publisher, dry_run=dry_run,
                                  llm_enabled=not args.no_llm, on_step=_render)
    observability.flush()

    recipe = state.get("recipe")
    _say("")
    _say(f"[result] {state.get('outcome')}")
    if recipe:
        _say(f"  recipe     {recipe.recipe_type}"
             + (f"  {recipe.url}" if recipe.url else "")
             + (f"  @{recipe.instagram_handle}" if recipe.instagram_handle else ""))
        if recipe.params:
            _say(f"  selectors  {recipe.params.model_dump(exclude_none=True)}")
    if state.get("verified_events"):
        _say(f"  events     {state['verified_events']} upcoming, verified by execution")
    _say(f"  spend      {state.get('tokens', 0)} tokens, ${state.get('usd', 0.0):.4f}, "
         f"{state['session'].fetches if state.get('session') else 0} fetches")
    if recipe and recipe.needs_url() and not dry_run:
        _say("\n  Next: discovery-agent harvest   # runs this recipe and stages its events")


def cmd_scout(args: argparse.Namespace) -> None:
    mode = "DRY-RUN " if args.dry_run else ""
    _say(f"[scout] {mode}model={settings.scout_model} limit={args.limit} "
         f"llm={'off' if args.no_llm else 'on'} store={db.backend_name()}")

    def report(st) -> None:
        r = st.get("recipe")
        _say(f"  {st.get('outcome', '?'):15s} "
             f"{(st['publisher'].get('category') or '-')[:12]:12s} "
             f"{st['publisher']['name'][:34]:34s} "
             f"{r.recipe_type if r else '-':16s} "
             f"events={st.get('verified_events', 0):3d} "
             f"fetches={st['session'].fetches if st.get('session') else 0} "
             f"${st.get('usd', 0.0):.4f}")

    categories = db.PILOT_MIX if args.mix else (
        args.categories.split(",") if args.categories else None)
    results = graph.run(limit=args.limit, dry_run=args.dry_run,
                        llm_enabled=not args.no_llm, categories=categories,
                        on_result=report)
    observability.flush()   # a batch job exits before the tracer's own timer fires
    scouted = sum(1 for s in results if s.get("outcome") == "scouted")
    _say(f"[scout] done: {len(results)} publishers, {scouted} with working recipes, "
         f"total ${sum(s.get('usd', 0.0) for s in results):.4f}")


def cmd_harvest(args: argparse.Namespace) -> None:
    recipes = db.active_recipes()
    print(f"[harvest] {len(recipes)} active recipe(s)")
    now = datetime.now(tz=BERLIN)
    total = 0
    for row in recipes:
        recipe = Recipe(**row["recipe"])
        session = FetchSession()  # fresh politeness budget per source
        try:
            events = future_events(execute_recipe(recipe, session), now)
        except (FetchRefused, Exception) as exc:  # noqa: BLE001
            print(f"  FAIL {row['publisher_name'][:40]:40s} {type(exc).__name__}: {exc}")
            db.record_source_result(row["source_id"], ok=False)
            continue
        inserted = db.stage_events(row["publisher_id"], events)
        db.record_source_result(row["source_id"], ok=bool(events))
        total += inserted
        print(f"  ok   {row['publisher_name'][:40]:40s} "
              f"future={len(events):3d} new={inserted:3d}")
    print(f"[harvest] staged {total} new event(s) into discovered_events")


def cmd_queue(args: argparse.Namespace) -> None:
    rows = db.scout_queue(args.limit)
    print(f"[queue] next {len(rows)} publisher(s) (demand first):")
    for r in rows:
        print(f"  demand={r['demand']:3d}  {r['kind']:9s} {r['name'][:50]:50s} "
              f"{r.get('website') or '(instagram: ' + str(r.get('instagram')) + ')'}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="discovery-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scout", help="scout publishers for event-publishing recipes")
    s.add_argument("--limit", type=int, default=settings.run_max_publishers)
    s.add_argument("--dry-run", action="store_true", help="no DB writes")
    s.add_argument("--no-llm", action="store_true", help="sniffers only, zero tokens")
    s.add_argument("--mix", action="store_true",
                   help="draw an even sample across venue categories (the pilot sample)")
    s.add_argument("--categories", type=str, default="",
                   help="comma-separated categories to restrict the queue to")
    s.set_defaults(fn=cmd_scout)

    w = sub.add_parser("watch", help="scout ONE publisher and narrate every step live")
    w.add_argument("name", nargs="?", default="",
                   help="publisher name (substring is fine); omit when using --url")
    w.add_argument("--url", type=str, default="",
                   help="scout an arbitrary site instead of a seeded publisher (never writes)")
    w.add_argument("--dry-run", action="store_true", help="no DB writes")
    w.add_argument("--no-llm", action="store_true", help="sniffers only, zero tokens")
    w.set_defaults(fn=cmd_watch)

    h = sub.add_parser("harvest", help="execute saved recipes, stage future events")
    h.set_defaults(fn=cmd_harvest)

    q = sub.add_parser("queue", help="show the scout queue")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(fn=cmd_queue)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
