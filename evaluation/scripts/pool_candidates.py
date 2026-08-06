#!/usr/bin/env python3
"""Freeze the eval corpus and pool retrieval candidates for hand-labeling.

Pooling (standard IR methodology): for each retrieval query in the frozen golden set,
take the union of each model's top-POOL_K results. A human labels only that pool —
not the whole corpus. Output:

  eval/corpus/v1.jsonl                  frozen 300-event snapshot (created once, never refetched)
  eval/results/pool_v1.json             per-query, per-model rankings (event ids)
  docs/showcase/labeling-sheet.html     checkbox sheet -> exports qrels_v1.jsonl

After labeling: put the exported file at eval/golden_set/qrels_v1.jsonl and run
scripts/score_qrels.py.
"""

from __future__ import annotations

import html
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from pipeline.embedder import build_embed_text, get_embedder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "eval" / "corpus" / "v1.jsonl"
GOLDEN = ROOT / "eval" / "golden_set" / "v1.jsonl"
POOL_OUT = ROOT / "eval" / "results" / "pool_v1.json"
SHEET = ROOT / "docs" / "showcase" / "labeling-sheet.html"

MODELS = ["openai/text-embedding-3-small", "qwen/qwen3-embedding-8b"]
POOL_K = 10  # per model per query


def cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def freeze_corpus() -> list[dict]:
    if CORPUS.exists():  # frozen means frozen — never refetch silently
        print(f"corpus already frozen ({CORPUS}), reusing")
        # split("\n"), NOT splitlines(): descriptions may contain U+2028/U+2029,
        # which splitlines() treats as line breaks — that would corrupt JSON lines
        return [json.loads(ln) for ln in CORPUS.read_text().split("\n") if ln.strip()]
    from db.supabase import get_client
    now = datetime.now(UTC)
    resp = (
        get_client().table("events")
        .select("id,title,description,category,subcategory,tags,venue_name,start_time,neighborhood")
        .eq("is_active", True).not_.is_("description", "null")
        # mirror production retrieval: upcoming, default 14-day window
        .gte("start_time", now.isoformat())
        .lte("start_time", (now + timedelta(days=14)).isoformat())
        .order("start_time", desc=False).limit(2000).execute()
    )
    pool = [e for e in resp.data if e.get("category")]
    # even subsample across the window (every Nth by start_time) — deterministic,
    # spans all days so weekday-specific queries ("am Sonntag") have candidates
    step = max(1, len(pool) // 300)
    events = pool[::step][:300]
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n")
    print(f"froze corpus: {len(events)} events -> {CORPUS}")
    return events


def main() -> None:
    events = freeze_corpus()
    texts = [build_embed_text(e) for e in events]
    golden = [json.loads(ln) for ln in GOLDEN.read_text().splitlines() if ln.strip()]
    queries = [g for g in golden if "retrieval" in g["applies_to"]]

    rankings: dict[str, dict[str, list[str]]] = {q["id"]: {} for q in queries}
    for model in MODELS:
        emb = get_embedder("openrouter", model=model)
        vecs = emb.embed_batch(texts)
        qvecs = emb.embed_batch([q["query"] for q in queries])
        for q, qv in zip(queries, qvecs):
            top = sorted(range(len(events)), key=lambda j: -cosine(qv, vecs[j]))[:POOL_K]
            rankings[q["id"]][model] = [events[j]["id"] for j in top]
        print(f"ranked with {model}")

    POOL_OUT.parent.mkdir(parents=True, exist_ok=True)
    POOL_OUT.write_text(json.dumps(
        {"corpus": "v1", "golden_set": "v1", "pool_k": POOL_K, "rankings": rankings}, indent=2
    ))

    by_id = {e["id"]: e for e in events}
    sections = []
    for q in queries:
        pool_ids = list(dict.fromkeys(  # union, first-seen order
            eid for model in MODELS for eid in rankings[q["id"]][model]
        ))
        cards = ""
        for eid in pool_ids:
            e = by_id[eid]
            desc = html.escape((e.get("description") or "")[:220])
            cards += f"""<label class="card"><input type="checkbox" data-q="{q['id']}" data-e="{eid}">
<div><b>{html.escape(e['title'])}</b>
<span class="meta">{html.escape(e.get('category') or '')}/{html.escape(e.get('subcategory') or '')}
· {html.escape(e.get('venue_name') or '')} · {html.escape((e.get('start_time') or '')[:16])}
· {html.escape(e.get('neighborhood') or '')}</span>
<p>{desc}…</p></div></label>"""
        sections.append(
            f"<section><h2>{q['id']} <em>{html.escape(q['query'])}</em></h2>"
            f"<p class='hint'>{html.escape(q['expect'])} — tick every event a user with this "
            f"question would be happy to see. Pool: {len(pool_ids)} candidates.</p>{cards}</section>"
        )

    SHEET.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pulse — qrels labeling sheet (golden set v1)</title>
<style>
 :root {{ color-scheme: light dark; --line:#88888840; --card:#88888812 }}
 body {{ font:15px/1.5 system-ui,sans-serif; max-width:860px; margin:2rem auto; padding:0 1rem }}
 h2 {{ border-bottom:1px solid var(--line); padding-bottom:.3rem; margin-top:2.2rem }}
 h2 em {{ font-weight:normal }}
 .hint {{ color:#888; font-size:.9em }}
 .card {{ display:flex; gap:.7rem; border:1px solid var(--line); background:var(--card);
         border-radius:8px; padding:.6rem .8rem; margin:.4rem 0; cursor:pointer }}
 .card:has(input:checked) {{ outline:2px solid #16a34a }}
 .card p {{ margin:.2rem 0 0; color:#888; font-size:.88em }}
 .meta {{ display:block; color:#888; font-size:.85em }}
 #bar {{ position:sticky; top:0; background:Canvas; padding:.7rem 0; border-bottom:1px solid var(--line);
        display:flex; gap:1rem; align-items:center; z-index:2 }}
 button {{ font:inherit; padding:.45rem 1rem; border-radius:8px; border:1px solid var(--line);
          cursor:pointer; background:#16a34a; color:white }}
</style></head><body>
<div id="bar"><button onclick="exportQrels()">Export qrels_v1.jsonl</button>
<span id="count">0 relevant ticked</span></div>
<h1>Label the golden set (v1)</h1>
<p>For each query: tick every event that a user asking this would consider a good hit.
Unticked = not relevant. When done, export and save the file as
<code>eval/golden_set/qrels_v1.jsonl</code>.</p>
{''.join(sections)}
<script>
const boxes = [...document.querySelectorAll('input[type=checkbox]')];
const count = document.getElementById('count');
boxes.forEach(b => b.addEventListener('change', () =>
  count.textContent = boxes.filter(x => x.checked).length + ' relevant ticked'));
function exportQrels() {{
  const lines = boxes.filter(b => b.checked)
    .map(b => JSON.stringify({{query_id: b.dataset.q, event_id: b.dataset.e, relevant: 1}}));
  const blob = new Blob([lines.join('\\n') + '\\n'], {{type: 'application/jsonl'}});
  const a = Object.assign(document.createElement('a'),
    {{href: URL.createObjectURL(blob), download: 'qrels_v1.jsonl'}});
  a.click();
}}
</script></body></html>""")
    total_pool = sum(len(set(eid for m in MODELS for eid in rankings[q['id']][m])) for q in queries)
    print(f"wrote {POOL_OUT}\nwrote {SHEET} ({len(queries)} queries, {total_pool} candidate labels)")


if __name__ == "__main__":
    main()
