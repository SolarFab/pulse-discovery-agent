# Experiment protocol (pinned configuration)

Methodology: every experiment varies **exactly one variable**; everything below stays pinned.
Golden set is **frozen** per version — changing it bumps the version (`eval/golden_set/v2.jsonl`),
never edits v1. Results are written to `eval/results/` as JSON; tables in the showcase are
generated from those files, never typed by hand.

## Pinned configuration

| Variable | Pinned value |
|---|---|
| Golden set | `eval/golden_set/v1.jsonl` (25 items: 16 embedding/retrieval, 13 chat, overlapping) |
| Event sample | 300 active events with category labels, ordered by start_time (deterministic) |
| K | 5 (precision@K, top-K retrievals) |
| Embedding gateway | OpenRouter (`/v1/embeddings`), native model dimensions |
| Embed text | `build_embed_text()` v1: title + description[:1500] + category/subcategory + sorted tags[:15] |
| Chat judge model | must differ from the answering model (self-preference bias) |
| Chat temperature | 0 for eval runs |

## Experiments

| # | Variable under test | Status |
|---|---|---|
| 1 | Embedding model (text-embedding-3-small vs gemini-embedding-001 vs qwen3-embedding-8b) | ready, blocked on OPENROUTER_API_KEY |
| 1b | Embed-text composition ablation (title / +description / +category / +tags; truncation length) | planned |
| 2 | Retrieval technique ladder (see below) | planned; needs qrels_v1 — runs offline on the frozen corpus |
| 3 | Prompt technique × chat model grid (zero-shot / few-shot / +reasoning / policy variants) | planned (promptfoo; needs tool-calling chat) |

## Experiment 2 — retrieval technique ladder

One config per run, all scored against `qrels_v1` on the frozen corpus, all reporting quality
(Recall@5, MRR, nDCG@5) **and** added query-time latency/cost — retrieval sits on the chat hot
path (~2s budget), so the ship decision weighs both:

| config | mechanism | query-time cost |
|---|---|---|
| baseline | vector-only (Experiment-1 winner) | ~0 |
| + BM25/RRF | Postgres FTS (`german`) fused with vectors via Reciprocal Rank Fusion | ~0 (SQL) |
| + Multi-Query | LLM expands the query into 3 variants, results unioned | +1 LLM call |
| + HyDE | LLM writes a hypothetical event description; embed that instead of the query | +1 LLM call |
| combos | only if a single technique wins on its own (stacking didn't compound in riester-kompass) | — |

Pool-bias control: new configs surface unlabeled events; their top-K get pooled and labeled
incrementally (label only the new candidates) before scores are compared.

## Why one-variable-at-a-time

Stacked changes can't be attributed; see the riester-kompass Experiment 2 finding that combined
retrieval tricks performed worse than either alone. Also: classical metrics and judge metrics can
disagree (HyDE effect) — both are always reported, decisions name which metric they optimized.

## Labeling guideline (learned the hard way, v2)

Retrieval-layer relevance = **semantic/type match only — ignore dates.** Temporal constraints
("heute Abend", "am Sonntag") are hard SQL filters in production and are evaluated at the chat
layer (Experiment 3), not against the ranker. qrels v1 partially applied date-aware judgment on
the temporal queries (q01/q02/q03/q23/q25); those five were re-reviewed under this guideline →
`qrels_v2_temporal.jsonl` supersedes v1(+delta) for exactly those queries. Guideline changes
create a new qrels version; they never edit old label files.
