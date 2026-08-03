# Discovery Agent v2 — Publisher Discovery System

(Supersedes the v1 venue-scout proposal; incorporates the 2026-08 product workshop.)

## Why

Pulse's aggregators are genre lenses, not mirrors: RA carries Berghain's club nights but not
Kantine's concerts; kulturdaten carries institutions but no kiez culture. Measured gaps: rap = 3
events citywide; Sisyphos/Anomalie absent; Kantine am Berghain at ~15% of its real program. The
bottleneck is not scraping — it is *finding out where each publisher announces events*. That
question is open-ended and per-publisher → the one place an agent is earned. Everything around
it stays deterministic.

## What Changes

- **Publisher model.** The unit of discovery is the *publisher*: `venue` (fixed place),
  `organizer` (wanders across venues — party crews, Luma calendars, RA promoters), `curator`
  (publishes others' events). Events link venue (where) + organizer (who). Aggregator coverage
  is always per-facet, never "venue done".
- **Three loops, one agent.** SEED (deterministic: OSM/Overpass, aggregator unknowns, demand
  queue, submissions) → SCOUT (the agent: investigates channels, writes typed recipes) →
  HARVEST (deterministic nightly executor runs recipes; 3 failures → re-scout).
- **Hybrid scout graph** (LangGraph core): deterministic fast path first — sniffers for
  ICS/JSON-LD/RSS resolve venues with ZERO tokens; the bounded LLM loop is the escalation path
  for the messy remainder. Verification gate: a recipe exists only if executing it now (via the
  real executor) yields ≥1 future dated event.
- **Recipes, not generated code**: `ics_feed | jsonld | rss | html_selector |
  aggregator_covered | instagram_lead | none` — one generic executor, model fills parameters.
- **Demand-first ordering**: chat misses (`discovery_requests`, live in prod) outrank the
  backlog — enabling the full-loop demo (chat miss → overnight scout → next-day answer).

## Capabilities

### New Capabilities
- `publisher-discovery` — seeding, the scout, recipes+verification, harvest, self-healing,
  demand queue, security guards, observability, and the pilot evaluation gate.

### Removed
- `venue-discovery` (v1 draft) — superseded before implementation.

## Impact

- **DB contract** (shared with Pulse, schema.sql): `publishers`, `publisher_sources`,
  `scout_runs`, `discovered_events` (staging); `discovery_requests` already live in prod.
- **IP boundary preserved**: this repo writes RAW events to staging; the private pipeline
  ingests staging through its existing normalize→categorize→facets→embed chain (one small
  reader added there). No code crosses repos — only tables.
- **Cost**: sniff path ≈ $0; LLM path budgeted per publisher (fetch/token/$ caps); strong-first
  model via OpenRouter (`SCOUT_MODEL`), offline so latency is irrelevant; measured
  cost-per-discovered-event is a first-class metric.
- **Security**: the scout follows links read on untrusted pages → SSRF wall (https-only,
  public-IP resolve check, redirect re-checks, size/type caps), per-venue domain budget,
  robots.txt + rate limits, page text as delimited data only.
- **Observability**: Langfuse traces (shared project with the concierge) + durable
  `scout_runs` reasoning traces (the demo artifact).

## Non-goals

- Agent-generated scraper code · full Instagram pipeline (leads only, harvested by the existing
  Apify path) · city-list compilation by LLM (OSM does it) · Hamburg build (documented scale-out
  only) · runtime agent skills (v2 option: channel playbooks) · autonomous writes to `events`
  (staging only; enrichment stays in the private pipeline).

## Decision gate (M3)

The 50-venue mixed pilot decides scale/adjust/pivot on measured evidence: recipe-type
distribution (A1 — the load-bearing bet), verification pass rate (A4), cost per venue and per
discovered event, golden-venue miss-rate. Findings are written up either way.
