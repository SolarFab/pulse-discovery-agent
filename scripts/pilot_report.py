"""Task 5.3 — turn scout_runs into the M3 decision numbers.

Answers, from real runs only:
  A1  recipe-type distribution (what kind of channels venues actually publish)
  A4  verification pass rate (how often a proposed recipe survives execution)
      + the free/paid split: how much of the yield the deterministic path gets
  cost per publisher, per scouted publisher, and per discovered event
  latency, and where the failures concentrate

    uv run python scripts/pilot_report.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discovery_agent.store_supabase import _client  # noqa: E402


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()
    sb = _client()

    runs = (sb.table("scout_runs")
            .select("publisher_id,outcome,tokens,usd,seconds,trace,created_at")
            .order("created_at").execute().data or [])
    if not runs:
        print("no scout_runs yet")
        return
    sources = sb.table("publisher_sources").select("publisher_id,recipe_type,url,scope,confidence").execute().data or []
    staged = sb.table("discovered_events").select("publisher_id").execute().data or []

    outcomes = Counter(r["outcome"] for r in runs)
    total = len(runs)
    usd = sum(float(r["usd"] or 0) for r in runs)
    secs = [float(r["seconds"] or 0) for r in runs]
    scouted = outcomes.get("scouted", 0)

    # Free vs paid: a run that spent no tokens was resolved by the sniffers alone.
    free_runs = [r for r in runs if not (r["tokens"] or 0)]
    free_scouted = sum(1 for r in free_runs if r["outcome"] == "scouted")
    paid_runs = [r for r in runs if (r["tokens"] or 0)]
    paid_scouted = sum(1 for r in paid_runs if r["outcome"] == "scouted")

    # A4: every verify step recorded in the traces.
    verifies = [s for r in runs for s in (r["trace"] or []) if s.get("step") == "verify"]
    passed = sum(1 for v in verifies if v.get("future_events", 0) >= v.get("needed", 1))
    proposals = sum(1 for r in runs for s in (r["trace"] or []) if s.get("step") == "propose")
    invalid = sum(1 for r in runs for s in (r["trace"] or []) if s.get("step") == "propose_invalid")
    aborts = Counter(s.get("reason") for r in runs for s in (r["trace"] or [])
                     if s.get("step") == "abort")

    print(f"\n{'=' * 66}\nPILOT REPORT — {total} scout runs\n{'=' * 66}")
    print("\nOUTCOMES")
    for name, count in outcomes.most_common():
        print(f"  {name:16s} {count:3d}  {_pct(count, total)}")

    print("\nA1 · RECIPE TYPES PERSISTED")
    for rtype, count in Counter(s["recipe_type"] for s in sources).most_common():
        print(f"  {rtype:20s} {count:3d}  {_pct(count, len(sources))}")

    print("\nA4 · VERIFICATION")
    print(f"  recipes executed against live sites : {len(verifies)}")
    print(f"  passed (list-shaped, future-dated)  : {passed}  {_pct(passed, len(verifies))}")
    print(f"  LLM proposals made                  : {proposals} ({invalid} schema-rejected)")
    if aborts:
        print("  budget aborts: " + ", ".join(f"{k}={v}" for k, v in aborts.items()))

    print("\nFREE vs PAID PATH")
    print(f"  sniffer-only runs : {len(free_runs):3d} -> {free_scouted} scouted "
          f"({_pct(free_scouted, len(free_runs))}), $0.00")
    print(f"  LLM runs          : {len(paid_runs):3d} -> {paid_scouted} scouted "
          f"({_pct(paid_scouted, len(paid_runs))}), ${usd:.2f}")

    print("\nCOST & LATENCY")
    print(f"  total                    ${usd:.2f}")
    print(f"  per publisher            ${usd / total:.4f}")
    print("  per SCOUTED publisher    " +
          (f"${usd / scouted:.4f}" if scouted else "n/a (none scouted)"))
    if staged:
        print(f"  per discovered event     ${usd / len(staged):.4f}  ({len(staged)} staged)")
    print(f"  median run               {statistics.median(secs):.0f}s"
          f"   slowest {max(secs):.0f}s")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "runs": total, "outcomes": dict(outcomes), "usd": usd,
            "usd_per_publisher": usd / total,
            "verification": {"executed": len(verifies), "passed": passed,
                             "proposals": proposals, "invalid": invalid},
            "free": {"runs": len(free_runs), "scouted": free_scouted},
            "paid": {"runs": len(paid_runs), "scouted": paid_scouted},
            "recipe_types": dict(Counter(s["recipe_type"] for s in sources)),
            "seconds": {"median": statistics.median(secs), "max": max(secs)},
        }, indent=2))
        print(f"\n[json] {args.json}")


if __name__ == "__main__":
    main()
