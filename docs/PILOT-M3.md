# M3 gate — 50-venue mixed pilot

Run: 2026-08-03 · model `openai/gpt-5.2` · category-stratified sample · $3.27 total.
Raw numbers in `pilot-50-mixed.json`; regenerate with `scripts/pilot_report.py`.

The queue returned **43** publishers rather than 50 — the stratified draw takes
`limit // categories` per category and several categories had fewer eligible rows.
Reported as-is rather than topped up alphabetically, which would have reintroduced
the sampling bias the stratification exists to remove.

## Outcomes

| outcome | n | share |
|---|---|---|
| none | 21 | 49% |
| **scouted (working recipe)** | **10** | **23%** |
| instagram_lead | 7 | 16% |
| unreachable | 5 | 12% |

## A1 · Recipe types

Of the 10 verified recipes: `html_selector` 4, `jsonld` 3, `ics_feed` 2, `rss` 1.

No single channel dominates. That is the argument for typed recipes over a
per-venue scraper: four generic parsers cover everything found so far, and the
agent's only job is choosing between them.

## A4 · Verification

55 candidate recipes were executed against live sites; **10 passed** (18%). The
gate is doing real work — 45 plausible-looking recipes produced no future-dated,
list-shaped events and were discarded rather than persisted. 62 LLM proposals were
made, 9 rejected by the Pydantic schema before execution.

## Economics

| metric | value |
|---|---|
| cost per publisher | $0.076 |
| cost per scouted publisher | $0.327 |
| events discovered | 371 |
| **cost per discovered event** | **$0.0088** |
| median run | 74s (slowest 290s, capped) |

**Free vs paid.** 9 runs spent nothing (sniffer resolved or site unreachable) and
yielded 4 recipes — a 44% hit rate at zero cost. 34 runs used the LLM and yielded 6
recipes (18%) for $3.27. The deterministic path is roughly **2.4× more accurate per
attempt and infinitely cheaper**, so ordering sniff-before-LLM is worth more than
any prompt tuning; the LLM's value is the 6 recipes the sniffers could not find.

Extrapolated to the 612 enriched publishers: ~$47 for ~140 recipes and ~5,000
events, at well under a cent per event. Against any manual alternative this is not
a close call.

## Decision: **SCALE, with three adjustments**

The economics clear the bar and the verification gate has demonstrated it rejects
bad recipes. Three fixes come first, in this order:

1. **Deduplicate publishers.** The sample contained "Columbia-Theater" *and*
   "Columbia Theater", "8MM" and "8mm Bar", "arkaoda" and "arkaoda Berlin" — each
   scouted twice at full price. Visible waste: ~$0.32 on the Columbia pair alone.
2. **Fix the html_selector path** (done, unmeasured). Diagnosis of the 49% none-rate
   showed the model was choosing repeating containers that hold no date at all,
   because the fetch tool showed it text but never markup. Hints now include child
   markup and explicitly flag dateless containers; `<li>`/`<tr>` are no longer
   excluded. Needs a re-run to quantify.
3. **Benchmark a cheap model (A2)** on the same 43 publishers. At $0.076/publisher
   the strong model is affordable but not obviously necessary — the task after
   sniffing is mostly "read this page and name a selector".

## What the failures actually were

Not a JS-rendering ceiling. All four expensive `none` venues (FEZ Berlin $0.28,
Hamburger Bahnhof $0.28, Columbia Theater $0.16, Klick Café $0.15) serve fully
rendered HTML with 20k–220k characters of text. They failed because the scout
could not construct a working selector, which is a fixable tooling problem — see
adjustment 2 — not a structural limit.

`unreachable` was likewise partly self-inflicted: Columbiahalle's stored URL
(`/de/`, from OSM) 404s while the site root is healthy. The sniffer now retries the
origin once.

## Blocked: ingest into the product

The full loop runs up to the boundary. `discovery-agent harvest` executed all 10
recipes and staged **371 events** into `discovered_events`, and the event-map
staging reader dry-run processed all 371 with 0 failures.

The real ingest is **deliberately not run**: `pipeline/categorizer.py` is hardwired
to Anthropic (`anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)`) and that key now
returns 401, so every categorization batch fails. Writing 371 uncategorized,
unembedded events into the live map would degrade the product to prove a pipeline.

The staged rows are untouched (`ingested = false`), so nothing is lost — the ingest
runs the moment categorization works. Note this also contradicts the repo's own
rule 3 (model-agnostic LLM access), and affects the nightly scrape, not just this
loop.
