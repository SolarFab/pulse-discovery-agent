# Product Workshop — August 2026

Facilitated product-discovery session covering personas, problems, solutions, assumptions and
the roadmap. Decisions below are binding until a future workshop revisits them.

## Round 1 — Users & North Star

- **North Star: Weekly Active Askers (WAA)** — people who ask Pulse ≥1 question per week.
  WAA is lagging, so the working **metric tree**: `WAA ← answered-well rate × coverage × retention`
  — engineering moves the branches, the top measures the product.
- **Geographic scope: Berlin only, deep.** Hamburg (or any city #2) is a documented scale-out
  chapter (OSM seed → aggregators → scout), not a build.

## Round 2 — Personas & problems

- **Personas: co-primary — (1) the engaged Berlin local** in three modes (tonight-mode /
  planning-mode / scene-mode) **and (2) the newcomer/tourist.** Consequences: English is
  first-class; the concierge explains venues rather than just naming them; trust signals are
  product features. No automatic tie-breaker between the two — conflicts decided case by case.
- **Top-3 problems (next 3 months):**
  - **P1 Scene coverage** — aggregators are genre lenses; the venue/organizer long tail is dark
    (evidence: rap 3 events; Kantine 3 of ~20/month; Sisyphos 0; RA carries only Berghain's
    club-night facet).
  - **P2 Data quality/trust** — 4 user-found bugs in 2 days (UTC times, "@ Berlin" venues,
    multi-venue pins, coordinate collisions); the class persists without systematic gates.
  - **P4 Personalization** — nothing to come back for; the preference-feed foundation
    (embeddings, pgvector, RLS design) is already built, §2–7 are not.
- **Parked:** P3 reliability (asterisk: self-hosted runner / timeout bump stays a hygiene fix),
  P5 concierge latency-feel, P6 distribution.

## Round 3 — Solution decisions

- **Build order: agent first** (capstone's required agentic core), **feed second** (foundation
  ready), **quality as continuous small gates** alongside.
- **Instagram: leads-only in v1** — scout records handle + channel; existing Apify scraper
  harvests. No new legal/technical surface.
- **Demo story: the full loop** — chat miss → overnight scout → next-day answer. Makes the
  demand queue and nightly harvest demo-critical.

### Architecture decisions folded in from the discovery deep-dives
- **Publisher model:** the unit of discovery is the *publisher* — venue (fixed place),
  organizer/promoter (wanders across venues), curator/media. Events link `venue_id` (where) +
  `organizer_id` (who). Aggregators are partial feeds *within* a publisher's file.
- **Aggregators are lenses, not mirrors:** `aggregator_covered` is always per-facet
  (RA covers Berghain's club nights, not Berghain); the scout still checks the venue's own
  channel. Metric: **aggregator miss-rate** per golden venue.
- **Recipes, not generated scrapers:** the agent fills a typed recipe
  (`ics_feed | jsonld | rss | html_selector | aggregator_covered | instagram_lead | none`);
  ONE generic executor runs them nightly. Model decides, code executes.
- **Verification gate:** a recipe is trusted only if executing it now yields ≥1 dated future
  event. Self-healing: 3 consecutive harvest failures → re-scout.
- **Seeding is deterministic** (OSM/Overpass + aggregator venue-unknowns + submissions);
  the agent enriches and resolves, never compiles city lists.
- **Cadences:** harvest nightly · repair on 3 failures · staleness re-scout ~60–90d ·
  `none` cooldown 90d · new-publisher discovery continuous (three demand feeds: chat misses,
  scrape-time unknowns, user submissions) + monthly OSM diff.
- **Submission entity-resolution:** user-submitted events (incl. flyer photos → vision extract)
  fuzzy-match venue/organizer before insert; unknown names feed the discovery queue.

## Round 4 — Assumptions under test

| # | Bet | Test |
|---|---|---|
| A1 (load-bearing) | Dark venues have findable structured channels | pilot recipe-type distribution |
| A2 | Affordable model suffices for scout reasoning | strong-first, then cheap-vs-strong benchmark |
| A3 | Recipes rot slowly | +14d survival re-run |
| A4 | Verification kills hallucinated recipes | hand-audit vs golden venues |
| A5 | Demand queue gets real volume | zero-result logging + 1 week of traffic |
| A6 | Organizers discoverable from event data (not OSM) | SQL count of luma/RA organizers |
| A7 | Polite scraping is uncontroversial | robots.txt + rate caps by construction |

- **Pilot: 50 mixed venues** (nightlife + galleries + kiez + family).
- **Scout model: strong-first** — top model establishes the ceiling; cheaper models benchmarked
  against its results (stage-1/stage-2 pattern). Scout is offline: latency irrelevant,
  cost one-off per venue.

## Round 5 — Roadmap (approved)

- **M0** Hygiene + demo plumbing: `discovery_requests` (zero-result logging), organizer-count
  query (A6), Actions timeout/self-hosted runner.
- **M1** Spec rewrite of `discovery-agent` around all of the above; validated.
- **M2** Core build: harvest executor (6 recipe types) → scout graph (LangGraph, strong model)
  → 15 golden venues with verified ground truth → SSRF/injection guards.
- **M3** **The pilot = decision gate.** 50 venues; outputs: recipe-type distribution (A1
  verdict), verification pass rate, cost/venue, golden-venue miss-rate. Findings written
  either way; results decide scale / adjust / pivot.
- **M4** Close loops: demand-queue priority, nightly harvest, +14d rot check, scout model
  benchmark, first quality gates (price sanity, time plausibility, dupe monitor).
- **M5** Demo assembly: rehearsed full loop + coverage dashboard + FINDINGS.
- **Then:** preference feed (§2–7 of its spec).

### Explicitly OUT
Hamburg build · full Instagram pipeline · agent-generated scraper code · collaborative
filtering · B2B demand-data products · tourist-specific curation features (tourists are served
through core quality) · LLM-in-the-loop ranking.
