# Design — Publisher Discovery System

## The three loops

```
SEED (deterministic, rare)         SCOUT (the agent, per publisher)     HARVEST (nightly)
OSM/Overpass · aggregator     ┌──► investigates channels          ┌──► executes recipes
unknowns · demand queue ──────┘    writes verified recipes ───────┘    raw events → staging
· submissions                                                          3 fails → re-scout
```

## Scout graph (LangGraph core only: StateGraph, conditional edges, checkpointer)

```
[1] triage      det.  load publisher context, robots.txt, start URL, cooldown check
[2] sniff       det.  fetch site; probe .ics / JSON-LD / RSS / <link alt> / sitemap;
                      follow "Programm/Events/Kalender" links (bounded).  ZERO tokens.
     └─ found → [5]
[3] investigate LLM   bounded tool loop (fetch_url, list_links): reason over pages,
                      locate where events live & how structured. Budgets: ≤8 fetches,
                      token cap, $ cap — hard aborts, recorded in trace.
[4] propose     LLM   structured Recipe (Pydantic): type, url, params, scope, confidence
[5] verify      det.  EXECUTE recipe via the real harvest executor; require ≥1 future
                      dated event. Fail → back to [3] once, else recipe=none.
[6] persist     det.  publisher_sources upsert + full trace to scout_runs (+ Langfuse)
```

State: `publisher · fetched_pages[] · candidates[] · findings[] · steps · cost · trace[]`.
`none` is a first-class outcome (90-day cooldown). The sniff fast path is the cost story:
expected 30–50% of venues resolve with zero LLM tokens (pilot measures it — A1).

## Framework decisions

- **LangGraph** for the scout only — multiple typed nodes, conditional edges, per-node
  budgets, checkpointing for batch resume, replayable traces. Core API only; tools stay plain
  Python; the graph is ~100 lines and replaceable. (Chat stays AI SDK; harvest stays plain.)
- **No runtime skills in v1.** Future option once channel playbooks accumulate
  (Instagram/ticket-shop/Linktree procedures) — skill-shaped, evidence-permitting.
- **Model**: OpenRouter gateway, `SCOUT_MODEL`, strong-first (ceiling), temp 0, Pydantic
  structured outputs. Cheap-vs-strong benchmark after the pilot (A2).
- **Observability**: Langfuse (shared project with concierge; cloud EU first, self-host
  option). `scout_runs` is the durable product-side trace (queryable, demo-able).

## Recipes & harvest executor

One executor, strategy per type: `ics_feed` (parse ICS), `jsonld` (schema.org Event),
`rss`, `html_selector` (item/date/title selectors — v1-included but HIGH-confidence gate),
`aggregator_covered` (marker + scope facet, no-op), `instagram_lead` (handoff marker for the
existing Apify path), `none`. Health per recipe: `last_success`, `consecutive_failures`
(3 → re-scout queue). Executor writes RAW events to `discovered_events` staging.

## IP boundary (repo contract)

This repo never imports Pulse code. It reads `publishers`/queues and writes
`publisher_sources`, `scout_runs`, `discovered_events`. The private pipeline adds one reader:
staging → normalize → categorize → facets → embed → upsert (all existing). Standalone demo:
docker sample DB shows raw discovered events end-to-end without Pulse.

## Security (sharper than chat — the scout follows links from untrusted pages)

- SSRF wall on EVERY fetch: https only · resolve DNS, reject private/link-local/metadata
  ranges · ≤5 redirects each re-checked · ≤2 MB · content-type allowlist.
- Domain budget: ≤3 distinct domains per publisher investigation.
- robots.txt respected; ≥1s per-domain delay; honest User-Agent.
- Page text enters prompts delimited as DATA; tool args schema-validated; fetched content can
  influence only which allowed URL is fetched next. Recipes are typed — no execute channel.

## Seeding & priority

Deterministic: Overpass city-polygon query (venues), aggregator venue-unknowns, Luma
calendars/RA promoters (organizers), `discovery_requests` (chat misses), submissions.
Scout order: demand queue > venues-with-events-but-no-recipe > OSM long tail.
Cadences: harvest nightly · repair on 3 failures · staleness re-scout 60–90d · `none`
cooldown 90d · OSM diff monthly.

## Evaluation (the same discipline as Experiments 1–3)

Golden venues (15, hand-verified programs) → recipe precision + aggregator miss-rate.
Pilot (50 mixed, strong model) → A1 recipe-type distribution · A4 verification pass rate ·
cost per venue & per discovered event · miss-rate. +14d rot re-run (A3). Cheap-vs-strong
grid (A2). All runs write eval-results JSONs; decision gate documented either way.
