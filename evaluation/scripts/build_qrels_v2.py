#!/usr/bin/env python3
"""Assemble canonical qrels v2 (docs/EXPERIMENT.md, labeling guideline v2).

For the temporal queries (q01/q02/q03/q23/q25) labels come EXCLUSIVELY from the
semantic-only re-review (qrels_v2_temporal.jsonl); every other query keeps its
v1(+delta) labels unchanged. Output: eval/golden_set/qrels_v2.jsonl.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GS = ROOT / "eval" / "golden_set"
TEMPORAL_QIDS = {"q01", "q02", "q03", "q23", "q25"}


def jsonl(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_text().split("\n") if ln.strip()]


def main() -> None:
    rows: list[dict] = []
    for f in ["qrels_v1.jsonl", "qrels_v1_delta.jsonl"]:
        rows += [r for r in jsonl(GS / f) if r["query_id"] not in TEMPORAL_QIDS]
    rows += jsonl(GS / "qrels_v2_temporal.jsonl")
    seen = set()
    out = []
    for r in rows:
        key = (r["query_id"], r["event_id"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    (GS / "qrels_v2.jsonl").write_text(
        "\n".join(json.dumps(r) for r in sorted(out, key=lambda r: (r["query_id"], r["event_id"])))
        + "\n")
    per_q: dict[str, int] = {}
    for r in out:
        per_q[r["query_id"]] = per_q.get(r["query_id"], 0) + 1
    print(f"qrels_v2.jsonl: {len(out)} labels — per query: {dict(sorted(per_q.items()))}")


if __name__ == "__main__":
    main()
