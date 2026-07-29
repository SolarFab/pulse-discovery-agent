# Discovery Agent

## Why
Pulse's event coverage is bottlenecked by *finding sources*, not scraping them. Berlin has
thousands of venues, and each publishes its events somewhere different — its own site, an events
subpage, Instagram, Resident Advisor, Eventbrite, a Telegram channel, or nowhere machine-readable.
Hand-maintaining a scraper per venue does not scale, and a generic crawler misses most of them.

The open-ended part is **deciding where a given venue publishes** — it needs reasoning, tool use,
and per-venue memory. That is a genuine agent. Once the channel is known, extracting events from it
is deterministic and cheap. So we build a **scout agent** that discovers the channel and writes a
reusable recipe (`venue_sources`); ordinary scheduled code re-scrapes from the recipe.

## What Changes
- Add a LangGraph scout that, for each venue lacking a fresh recipe, investigates where it publishes
  events using a small set of tools and emits `venue_sources` rows (channel_type, url, scrape_recipe,
  confidence).
- Persist recipes idempotently (upsert per venue+channel) with `last_checked` for staleness-based
  re-scouting.
- Enforce a per-run venue cap and a tool-call budget per venue for cost control.
- Treat all fetched web text as untrusted data (indirect-injection safe).

## Non-goals
- Re-scraping known channels, ranking, categorising, or embedding events (deterministic, separate).
- Writing `events` rows (the scout produces recipes; extraction is a later, non-agent step).
- Provider-specific model features; the LLM stays behind the model-agnostic gateway.

## Impact
- New capability: `venue-discovery`.
- Code: `src/discovery_agent/{graph,tools,db,config,main}.py`; contract table `venue_sources`.
- Cost: bounded by `SCOUT_MAX_VENUES` and the per-venue tool-call budget; recipes amortise the LLM
  spend across all future re-scrapes.
