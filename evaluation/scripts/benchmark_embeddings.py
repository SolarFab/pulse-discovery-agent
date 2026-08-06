#!/usr/bin/env python3
"""Embedding model benchmark (preference-feed: decides the embedder before task 1.1).

Part A — proxy labels: kNN precision@5 against category/subcategory labels over a
sample of real events. Both candidates see the identical sample.
Part B — mini golden set: German<->English queries; top-5 retrievals are PRINTED for
human verification (cross-lingual quality is the risk proxy labels can't measure).

All candidate models run through ONE gateway (OpenRouter) — identical conditions,
one API key.

Usage:
    python scripts/benchmark_embeddings.py                # default candidate models
    python scripts/benchmark_embeddings.py --sample 300
    python scripts/benchmark_embeddings.py --models openai/text-embedding-3-small
Writes docs/embedding-benchmark.md with the results table.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from db.supabase import get_client  # noqa: E402
from pipeline.embedder import build_embed_text, get_embedder, has_key  # noqa: E402

# Candidate models, all via the OpenRouter gateway (one key, identical conditions).
DEFAULT_CANDIDATES = [
    "openai/text-embedding-3-small",   # industry default, good multilingual
    "google/gemini-embedding-001",     # Google's current embedder
    "qwen/qwen3-embedding-8b",         # top multilingual open model
]

# ── Part B: golden queries come from the FROZEN golden set (see docs/EXPERIMENT.md) ──
GOLDEN_SET = Path(__file__).resolve().parent.parent / "eval" / "golden_set" / "v1.jsonl"


def load_golden_queries() -> list[dict]:
    items = [json.loads(ln) for ln in GOLDEN_SET.read_text().splitlines() if ln.strip()]
    return [it for it in items if "embedding" in it["applies_to"]]


K = 5


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def knn_precision(vecs: list[list[float]], labels: list[str | None], k: int = K) -> float:
    """Mean fraction of each item's k nearest neighbours sharing its label."""
    scored = 0
    total = 0.0
    for i, (v, lab) in enumerate(zip(vecs, labels)):
        if not lab:
            continue
        sims = [(cosine(v, w), labels[j]) for j, w in enumerate(vecs) if j != i]
        sims.sort(key=lambda s: -s[0])
        top = [s for s in sims[:k] if s[1]]
        if not top:
            continue
        total += sum(1 for _, other in top if other == lab) / len(top)
        scored += 1
    return total / scored if scored else 0.0


def fetch_events(sample: int) -> list[dict]:
    client = get_client()
    resp = (
        client.table("events")
        .select("id,title,description,category,subcategory,tags")
        .eq("is_active", True)
        .not_.is_("description", "null")
        .gte("start_time", datetime.now(UTC).isoformat())  # upcoming only — mirror production retrieval
        .order("start_time", desc=False)
        .limit(sample)
        .execute()
    )
    return [e for e in resp.data if e.get("category")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--models", default=None, help="comma list of gateway model ids")
    args = ap.parse_args()

    if not has_key("openrouter"):
        sys.exit("OPENROUTER_API_KEY not set — add it to .env. Nothing to do.")
    models = args.models.split(",") if args.models else DEFAULT_CANDIDATES

    print(f"Fetching up to {args.sample} events…")
    events = fetch_events(args.sample)
    texts = [build_embed_text(e) for e in events]
    cats = [e.get("category") for e in events]
    subs = [e.get("subcategory") for e in events]
    print(f"{len(events)} events with a category. Candidates: {models}\n")

    rows = []
    query_sections = []
    for name in models:
        emb = get_embedder("openrouter", model=name)
        t0 = time.time()
        try:
            vecs = emb.embed_batch(texts)
        except Exception as exc:  # one bad model id must not kill the run
            print(f"{name:35} SKIPPED: {type(exc).__name__}: {exc}")
            continue
        dt = time.time() - t0
        actual_dim = len(vecs[0]) if vecs else 0  # native size (EMBED_DIM unset)
        p_cat = knn_precision(vecs, cats)
        p_sub = knn_precision(vecs, subs)
        rows.append((name, actual_dim, p_cat, p_sub, dt, len(texts)))
        print(f"{name:35} dim={actual_dim:5} p@{K} cat={p_cat:.3f} sub={p_sub:.3f} ({dt:.1f}s)")

        # Part B — print retrievals for human judgment
        golden = load_golden_queries()
        qvecs = emb.embed_batch([g["query"] for g in golden])
        lines = [f"\n### {name} (dim={actual_dim})"]
        for g, qv in zip(golden, qvecs):
            q = f"{g['id']} [{g['category']}] {g['query']}"
            sims = sorted(
                ((cosine(qv, v), events[j]) for j, v in enumerate(vecs)),
                key=lambda s: -s[0],
            )[:K]
            lines.append(f"\n**{q}**")
            for s, e in sims:
                lines.append(f"- {s:.3f} [{e.get('category')}/{e.get('subcategory')}] {e['title'][:70]}")
        query_sections.append("\n".join(lines))

    out = Path(__file__).resolve().parent.parent / "docs" / "embedding-benchmark.md"
    table = "\n".join(
        f"| {n} | {d} | {pc:.3f} | {ps:.3f} | {dt:.1f}s / {cnt} events |"
        for n, d, pc, ps, dt, cnt in rows
    )
    out.write_text(
        "# Embedding benchmark\n\n"
        f"Sample: {len(events)} active events with category labels. "
        f"Metric: kNN precision@{K} (do an event's nearest neighbours share its label?).\n\n"
        "All models via the OpenRouter gateway (identical conditions).\n\n"
        "| model | dim | p@5 category | p@5 subcategory | time |\n"
        "|---|---|---|---|---|\n" + table + "\n\n"
        "## Golden-query retrievals (verify by hand)\n"
        "Cross-lingual DE<->EN probes — a human judges whether the top-5 are correct.\n"
        + "\n".join(query_sections) + "\n"
    )
    # Reproducible run record (docs/EXPERIMENT.md): full JSON next to the golden set version.
    results_dir = Path(__file__).resolve().parent.parent / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (results_dir / f"embedding-{stamp}.json").write_text(json.dumps({
        "experiment": "1-embedding-model",
        "golden_set": "v1",
        "sample_events": len(events),
        "k": K,
        "runs": [
            {"model": n, "dim": d, "p_at_k_category": pc, "p_at_k_subcategory": ps,
             "seconds": round(dt, 1)}
            for n, d, pc, ps, dt, _ in rows
        ],
    }, indent=2))
    print(f"\nWrote {out} and eval/results/embedding-{stamp}.json")


if __name__ == "__main__":
    main()
