# Tasks — Publisher Discovery (M1–M5 of the workshop roadmap)

[capstone] = this repo · [event-map] = private pipeline · [db] = shared Supabase contract

## 1. Contract & scaffolding (M1/M2)
- [x] 1.1 [db] Migration: `publishers`, `publisher_sources`, `scout_runs`, `discovered_events`
      (+ mirror in this repo's schema.sql + docker seed)
- [x] 1.2 [db] Seed publishers from existing `venues` (kind=venue) + Luma calendars/RA promoter
      names where extractable (kind=organizer) — 2,770 venue-publishers seeded
- [x] 1.3 [capstone] Config: SCOUT_MODEL (strong default), budgets (fetches/tokens/$),
      Langfuse keys optional-guarded

## 2. Harvest executor first (verification depends on it) (M2)
- [x] 2.1 [capstone] Fetch security wall (single module) + robots/rate-limit helpers + tests
      (private-IP rejection, redirect re-check, size/type caps)
- [x] 2.2 [capstone] Strategies: ics_feed, jsonld, rss + fixture tests each
- [x] 2.3 [capstone] Strategy: html_selector (+ high-confidence gate) + fixtures
- [x] 2.4 [capstone] Markers: aggregator_covered (no-op), instagram_lead (handoff row)
- [x] 2.5 [capstone] Staging writer + recipe health updates (last_success/consecutive_failures)
      — db.stage_events / db.record_source_result + `discovery-agent harvest` CLI
- [x] 2.6 [event-map] Staging reader: discovered_events → existing normalize→categorize→facets→
      embed→upsert; dedup via fingerprint; nightly step
      — scrapers/discovery_staging.py, registered as source "discovery_agent"

## 3. Scout graph (M2)
- [x] 3.1 [capstone] Sniffers (deterministic): ics/jsonld/rss/link-alt/sitemap/program-link probes
- [x] 3.2 [capstone] LangGraph: state, nodes (triage/sniff/investigate/propose/verify/persist),
      conditional edges, retry budget (no checkpointer: runs are single-shot per publisher;
      resume happens at queue level, not mid-graph)
- [x] 3.3 [capstone] Tools: guarded fetch_page (text + declared feeds + links + repeating-
      structure selector hints); Pydantic Recipe schema enforced at propose time
- [x] 3.4 [capstone] scout_runs trace persistence + Langfuse tracing (observability.py:
      span per publisher, generation per LLM call; guarded so absent keys / a broken
      collector degrade to no-ops, with tests)
- [x] 3.5 [capstone] Unit tests: graph wiring, budget aborts, injection probe (page text
      demanding actions must not alter tool args), recipe validation

## 4. Seeding & scheduling (M2/M4)
- [x] 4.1 [capstone] Overpass import script (city polygon → venue publishers)
      — scripts/enrich_publishers_overpass.py; 612/2,770 publishers given a website
      + OSM category. Prerequisite discovered the hard way: every seeded publisher
      had website=NULL, so the scout had nothing to scout at all.
- [~] 4.2 [capstone] Demand-queue reader + priority ordering done (chat misses rank first
      in scout_queue); aggregator-unknowns reader still open
- [x] 4.3 [capstone] Runner CLI (`scout` / `harvest` / `queue`, with --mix, --dry-run,
      --no-llm) + GH Actions: tests.yml, discovery.yml (nightly harvest, weekly scout,
      manual dispatch)

## 5. Golden venues & pilot — the M3 gate
- [ ] 5.1 Pick 15 golden venues; hand-verify their real programs (ground truth doc)
- [~] 5.2 Run the 50-venue mixed pilot (strong model); write eval-results JSON
      — sampling now category-stratified (`scout --mix`); pre-fix baseline kept in
      docs/pilot-before-budget-fix.json for the budget-bug before/after
- [x] 5.3 Pilot report generator: scripts/pilot_report.py (A1 recipe types, A4
      verification pass rate, free-vs-paid split, cost/publisher, cost/scouted,
      cost/event, latency). DECISION still pending the mixed run.

## 6. Close the loops (M4)
- [ ] 6.1 Nightly harvest scheduling; failure counters drive the re-scout queue end-to-end
- [ ] 6.2 +14d rot re-run on pilot recipes (A3) → survival rate
- [ ] 6.3 Cheap-vs-strong scout model benchmark on identical publishers (A2)
- [ ] 6.4 [event-map] Coverage metrics: dark-publisher count, events/week via agent,
      aggregator miss-rate on golden venues → showcase dashboard section

## 7. Demo (M5)
- [ ] 7.1 Full-loop rehearsal: real chat miss → scout run (trace visible) → staging → ingest →
      next-day chat answers
- [ ] 7.2 FINDINGS + showcase updates (pilot numbers, traces, cost story)
