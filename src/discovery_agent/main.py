"""CLI entry point.

    discovery-agent scout   [--limit N] [--dry-run] [--no-llm]   # find recipes
    discovery-agent harvest                                       # run saved recipes
    discovery-agent queue                                         # show who's next
"""

from __future__ import annotations

import argparse
from datetime import datetime

from . import db, graph
from .config import settings
from .guards import FetchRefused, FetchSession
from .harvest import execute_recipe
from .recipes import BERLIN, Recipe, future_events


def _say(msg: str) -> None:
    """Progress must appear as it happens: a scout run takes minutes per publisher,
    and Python block-buffers stdout when it is piped or redirected."""
    print(msg, flush=True)


def cmd_scout(args: argparse.Namespace) -> None:
    mode = "DRY-RUN " if args.dry_run else ""
    _say(f"[scout] {mode}model={settings.scout_model} limit={args.limit} "
         f"llm={'off' if args.no_llm else 'on'} store={db.backend_name()}")

    def report(st) -> None:
        r = st.get("recipe")
        _say(f"  {st.get('outcome', '?'):15s} {st['publisher']['name'][:40]:40s} "
             f"{r.recipe_type if r else '-':18s} "
             f"events={st.get('verified_events', 0):3d} "
             f"fetches={st['session'].fetches if st.get('session') else 0} "
             f"${st.get('usd', 0.0):.4f}")

    results = graph.run(limit=args.limit, dry_run=args.dry_run,
                        llm_enabled=not args.no_llm, on_result=report)
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
    s.set_defaults(fn=cmd_scout)

    h = sub.add_parser("harvest", help="execute saved recipes, stage future events")
    h.set_defaults(fn=cmd_harvest)

    q = sub.add_parser("queue", help="show the scout queue")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(fn=cmd_queue)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
