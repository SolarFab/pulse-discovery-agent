#!/usr/bin/env python3
"""Score frozen model rankings against hand-labeled qrels (Experiment 1, upgraded).

Inputs (all frozen artifacts — no network, fully reproducible):
    eval/results/pool_v1.json           rankings per query per model
    eval/golden_set/qrels_v1.jsonl      human labels from the labeling sheet

Metrics per model: Recall@5, Precision@5, MRR, nDCG@5 (binary relevance).
Writes eval/results/qrels_scores_v1.json and docs/embedding-benchmark-qrels.md.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "eval" / "results" / "pool_v1.json"
_V2 = ROOT / "eval" / "golden_set" / "qrels_v2.jsonl"
QRELS = _V2 if _V2.exists() else ROOT / "eval" / "golden_set" / "qrels_v1.jsonl"
K = 5


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, e in enumerate(ranked[:k]) if e in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def main() -> None:
    if not QRELS.exists():
        sys.exit(f"{QRELS} not found — label docs/showcase/labeling-sheet.html and export first.")
    pool = json.loads(POOL.read_text())
    rels: dict[str, set[str]] = {}
    for ln in QRELS.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            rels.setdefault(r["query_id"], set()).add(r["event_id"])

    models = sorted({m for q in pool["rankings"].values() for m in q})
    scores: dict[str, dict] = {}
    for model in models:
        per_q = []
        for qid, by_model in pool["rankings"].items():
            relevant = rels.get(qid, set())
            if not relevant:
                continue  # query judged to have no relevant events in pool — skip, report separately
            ranked = by_model[model]
            top = ranked[:K]
            hits = [e for e in top if e in relevant]
            rr = next((1 / (i + 1) for i, e in enumerate(ranked) if e in relevant), 0.0)
            per_q.append({
                "query_id": qid,
                "recall": len(hits) / len(relevant),
                "precision": len(hits) / K,
                "rr": rr,
                "ndcg": ndcg_at_k(ranked, relevant, K),
            })
        n = len(per_q)
        scores[model] = {
            "queries_scored": n,
            f"recall@{K}": round(sum(q["recall"] for q in per_q) / n, 3),
            f"precision@{K}": round(sum(q["precision"] for q in per_q) / n, 3),
            "mrr": round(sum(q["rr"] for q in per_q) / n, 3),
            f"ndcg@{K}": round(sum(q["ndcg"] for q in per_q) / n, 3),
            "per_query": per_q,
        }

    no_rel = [qid for qid in pool["rankings"] if qid not in rels]
    out = {"experiment": "1-embedding-model-qrels", "corpus": pool["corpus"],
           "golden_set": pool["golden_set"], "k": K,
           "queries_without_relevant": no_rel, "models": scores}
    (ROOT / "eval" / "results" / "qrels_scores_v1.json").write_text(json.dumps(out, indent=2))

    md = ["# Embedding benchmark — hand-labeled qrels (golden set v1, frozen corpus v1)", "",
          f"Human relevance labels over pooled candidates; K={K}. "
          f"Queries with no relevant event in pool: {', '.join(no_rel) or 'none'}.", "",
          f"| model | recall@{K} | precision@{K} | MRR | nDCG@{K} | queries |", "|---|---|---|---|---|---|"]
    for m, s in scores.items():
        md.append(f"| {m} | {s[f'recall@{K}']} | {s[f'precision@{K}']} | {s['mrr']} "
                  f"| {s[f'ndcg@{K}']} | {s['queries_scored']} |")
    (ROOT / "docs" / "embedding-benchmark-qrels.md").write_text("\n".join(md) + "\n")

    for m, s in scores.items():
        print(f"{m:38} R@{K}={s[f'recall@{K}']} P@{K}={s[f'precision@{K}']} "
              f"MRR={s['mrr']} nDCG={s[f'ndcg@{K}']}")
    print("wrote eval/results/qrels_scores_v1.json and docs/embedding-benchmark-qrels.md")


if __name__ == "__main__":
    main()
