# Evaluation — the retrieval + concierge experiments

This directory is the **evaluation half** of the capstone. The rest of this repo is the
discovery agent (finding *where* events are published). This part answers the other
question: once the events are in the database, **does asking for them in natural language
actually return the right ones?**

The system under test is Pulse's concierge — a tool-calling chat over a pgvector index of
Berlin events. **The code under test is in [`concierge/`](concierge/)**: the endpoint and its
system prompt, the two tool definitions, and the SQL retrieval function. Alongside it: the
frozen golden set, the hand-labeled relevance judgements, the experiment scripts, the
reports, and the rendered result artifacts.

Not included, by design: how events get *into* the database. The scrapers and the sources
they read are the product's own work, and are not what these experiments measure.

> **The scripts do not run standalone.** They import the product's pipeline (`pipeline.embedder`,
> `db.supabase`) and read a live index. They are included as the record of *how* each number
> was produced, not as a runnable harness. The frozen 300-event corpus is deliberately not
> committed — it is scraped production data.

## The method

Every experiment changes **one variable** against a frozen corpus and a frozen query set,
and reports classical IR metrics plus cost and latency.

| Piece | What it is |
|---|---|
| `concierge/` | **The code under test** — system prompt, tool definitions, retrieval SQL |
| `golden_set/v1.jsonl` | 25 real questions ("jazz tonight", "something with my kids on the weekend, outside") |
| `golden_set/qrels_*.jsonl` | Hand-labeled relevance, **four rounds** — see below |
| `prompts/*.txt` | The four prompt variants compared (zero-shot, few-shot, clarify-first, production) |
| `scripts/` | The experiment runners and report builders |
| `reports/` | Written results per experiment |
| `showcase/` | Rendered HTML: the full testing report, the labeling sheets, the charts |

### Why four rounds of labels

The labels were wrong twice, and both corrections are part of the record:

1. **`qrels_v1`** — labeled from a pool of candidates the systems returned. That pool is
   biased: a document no system retrieved can never be judged relevant.
2. **`qrels_v1_delta`** — a second labeling round over candidates found only by the
   *challenger* configurations, to correct that bias.
3. **`qrels_v2`** — relabeled under a corrected guideline. The first pass judged relevance
   *including the date*, so "jazz tonight" marked a perfect jazz match irrelevant for being
   on the wrong night. Dates are a filter, not a relevance signal; conflating them measures
   the SQL layer, not the retrieval.
4. **`qrels_v2_temporal`** — the five temporal queries re-judged under that guideline.

## What the experiments found

Full numbers in `reports/`; the short version:

- **Embeddings** — `text-embedding-3-small` beat a much larger open model decisively
  (Recall@5 0.62 vs 0.25). Bigger was not better.
- **Retrieval** — plain vector search beat BM25, Reciprocal Rank Fusion, Multi-Query and
  HyDE on *every* metric. Multi-Query and HyDE also broke the 2s chat latency budget. A
  published technique failing to replicate on your own data is a result worth keeping.
- **Prompting** — few-shot won on all 9 models tested; clarify-first collapsed to 31–46%.
  A 31B open model sat on the Pareto frontier at 92% accuracy for $0.00012/turn.
- **Judging** — the judge is not the candidate. One cheap model matched a frontier judge
  14/14 and resisted prompt injection at 1/8 the cost; another was disqualified for
  fabricating events that were not in its context.

`reports/CONCIERGE-FINDINGS.md` collects 13 findings, including the ones that were bugs in
my own method rather than in the system.

## Start here

Open **`showcase/testing-report.html`** in a browser — it is the assembled report, with the
scatter plot and the per-configuration retrieval comparison embedded.
