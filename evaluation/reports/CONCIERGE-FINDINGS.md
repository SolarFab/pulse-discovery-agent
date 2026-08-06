# Key findings — Pulse evaluation program

Each finding: the claim, the evidence (all reproducible from files in this repo), and why it
matters. Experiments follow the one-variable-at-a-time protocol in [EXPERIMENT.md](EXPERIMENT.md);
raw run records live in `eval/results/`.

## 1. Proxy metrics would have picked the wrong story
On automatic proxy labels (kNN category match), the two embedding candidates looked nearly tied —
qwen3-8b even *led* on subcategories. Hand-labeled relevance judgments revealed a ~3× quality gap:
text-embedding-3-small MRR **0.896** vs qwen3-8b 0.646, nDCG@5 0.729 vs 0.337.
*Evidence:* `embedding-benchmark.md` (proxy) vs `embedding-benchmark-qrels.md` (human).
*Lesson:* cheap automatic metrics are for regressions, not decisions — decisions need ground truth.

## 2. Human review caught what the pipeline couldn't
The first frozen eval corpus silently sampled the 300 **oldest** events (all past) — discovered
only when a human looked at the labeling sheet and asked why "jazz tonight" showed last year's
events. Separately, a scraped description containing an invisible Unicode line separator (U+2028)
corrupted the corpus file. Both fixed, corpus re-frozen on upcoming events sampled across days.
*Lesson:* eval data is code — it has bugs, and eyeballs are a test tool.

## 3. Pool bias is real and measurable
Relevance labels came from pooled top-K of the *embedding* models — so new retrieval configs
surfaced events "scored irrelevant" merely because no one had judged them (baseline: 0 unlabeled
top-5 results; other configs: 6–25). An incremental labeling round over only the new candidates
fixed it; Multi-Query gained +0.10 R@5 from that correction alone.
*Lesson:* when the answer key comes from system A, scoring system B against it needs a top-up round.

## 4. Labeling guidelines are part of the architecture
qrels v1 judged temporal queries date-aware ("Saturday flea market ✗ for 'Flohmarkt am Sonntag'")
— contradicting the system design, where dates are hard SQL filters and embeddings only rank
within them. Five queries were re-judged under a written semantic-only guideline → qrels v2
(versioned; old labels never edited). Baseline MRR rose 0.78 → 0.896 — it had been punished for
mistakes the production system cannot make.
*Lesson:* the labeling instruction must match the layer under test; guideline changes are versioned.

## 5. Retrieval: the boring baseline won everything
Vector-only retrieval beat BM25+RRF hybrid, Multi-Query and HyDE on every metric
(R@5 0.621 / MRR 0.896 / nDCG@5 0.729). HyDE — the headline winner in the author's prior
RAG project (riester-kompass, legal corpus) — did **not** replicate: event queries and event
descriptions share the same vocabulary register, so a hypothetical document only adds
hallucinated detail. Multi-Query and HyDE also cost 2.1–2.6 s/query — over the chat budget
regardless of quality.
*Evidence:* `retrieval-benchmark.md`, per-query audit in `showcase/retrieval-comparison.html`.
*Lesson:* retrieval tricks are gap-bridgers; with no gap they add noise, latency and cost.

## 6. LLM-dependent evals must pin their LLM outputs
Uncached Multi-Query/HyDE scores wobbled run-to-run (HyDE R@5 0.28–0.45 at temperature 0)
because each run generated fresh query expansions. Expansions are now cached per query —
runs are reproducible; without pinning, config comparisons were partly noise.

## 7. Prompting: rules tell, examples teach
Across the full grid, a rules-only production prompt was no better than a three-line zero-shot
prompt. Adding **five worked tool-call examples** made few-shot best-or-tied on **all nine
models** tested. The examples fixed exactly the hard skills: kiez→coordinates and relative-date
→ ISO resolution failed in every variant *without* examples and nowhere *with* them.
*Evidence:* `prompt-benchmark.md`; cost/accuracy chart `showcase/prompt-scatter.html`.

## 8. Over-clarification is a measurable failure mode
The clarify-first dialog policy (ask a question before searching) collapsed to 31–46% tool-call
accuracy: models interrogated users whose requests were already fully specified ("free open-air
cinema", "rap events"). The answer-first policy (search, show a spread, offer to narrow) won —
settling a design debate with data rather than taste.

## 9. An open 31B model owns the accuracy-per-dollar frontier
On measured cost (OpenRouter usage accounting), **Gemma-4-31B** sits on the Pareto frontier:
92% tool-call accuracy at **$0.00012/turn** (~1.8 s) — matching claude-haiku-4.5's accuracy at
~1/20th the price. But latency splits the open field: MiniMax-M2.7 and DeepSeek-V4 match on
accuracy and undercut on price at 4–8 s/turn — disqualifying for interactive chat.
*Lesson:* cheap per token ≠ viable per turn; report latency next to cost, always.

## 10. Temperature 0 is not determinism
The same model × prompt × queries scored 12/13, 13/13, 12/13 across three runs. The flip was a
single query — q18, the deliberately ambiguous "Plan uns was Schönes" that sits on the
search-vs-clarify decision boundary. Provider-side effects (batching, floating-point order,
routing) shift near-tied logits. On a 13-item set one item = 7.7 points, so near scores are
**ties**, not rankings.
*Evidence:* three timestamped `eval/results/prompts-*.json` with per-query detail.
*Lesson:* report repeats or ranges; identify boundary cases instead of celebrating single runs.

## 11. The entire program cost almost nothing
Embedding 21,784 events: **~$0.10**. All benchmarks (2 embedding models, 5 retrieval configs,
36 prompt cells across 9 models, with reruns): **under ~$2 total**, each run's spend recorded in
its results JSON. Rigorous evaluation at this scale is a workflow question, not a budget question.

## 12. The judge round overturned the speed champion — and crowned the open model
Stage 2 (full loop, real DB, gpt-4o as judge): **gemma-4-31b scored perfect** — 14/14 on
grounding, honesty, format and language, and **resisted a planted prompt-injection** event —
at 1/8th of claude-haiku's cost (haiku matched quality but at $0.097 vs $0.012 and 7.7s vs
5.2s). The stage-1 latency champion gemini-2.5-flash **fabricated events with invented IDs**
whenever results were thin — invisible to stage-1's tool-call asserts, fatal for a grounded
concierge. `CHAT_MODEL` shipped as the open 31B model, on judged evidence.
*Lesson:* tool-call accuracy does not predict grounding; never promote a model on stage 1 alone.

## 13. One wrong answer, five independent defects — and a measured error rate
A user asked why the concierge denied a comedy show that visibly existed. The autopsy found
five stacked causes: (1) the scraper stored Eventbrite's 140-char teaser instead of the full
description (starving categorizer, neighborhood detection and embeddings — the full text
contained "stand-up" and "Friedrichshain"); (2) the LLM categorizer filed a Comedy-tagged
show under culture **against its own prompt rule**; (3) `subcategory=comedy` was 99.5% dead in
the data (1 tagged vs 220 actual) so the concierge's filter could never match; (4) the event
was unembedded (an orphaned backfill + timeout-killed nightlies — no gauge watched the count);
(5) by-name lookup was impossible in vector-only ranking. Every fix landed at class level:
deterministic tag-beats-LLM pre-pass, full-description ingest (+239 enriched), 195 events
refiled, backfill to zero (+gauge to come), lexical title boost. The first run of the
embedding-neighbor taxonomy audit then **measured** the residual problem: **6.2%**
miscategorization-candidate rate, concentrated around `culture` as the junk-drawer category.
*Lesson:* in an AI product, a wrong answer is usually compound interest on small data sins —
the model is rarely the main culprit, and each sin needs a gauge, not just a fix.
