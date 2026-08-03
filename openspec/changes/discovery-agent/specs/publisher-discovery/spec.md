# publisher-discovery

## ADDED Requirements

### Requirement: Publishers are the unit of discovery
The system SHALL model publishers with kinds `venue`, `organizer`, `curator`; events link a
venue (where) and optionally an organizer (who). Aggregator coverage SHALL be recorded
per-facet (`aggregator_covered` with scope), never marking a publisher fully covered.

#### Scenario: Venue partially covered by an aggregator
- **WHEN** a venue's club nights are on RA but its concerts are not
- **THEN** it carries an `aggregator_covered(scope: nightlife)` recipe AND the scout still checks its own channels for the rest

#### Scenario: Organizer discovered from event data
- **WHEN** an organizer (e.g. a Luma calendar) is seen in scraped events
- **THEN** a publisher of kind `organizer` is created and queued; its recipe yields events whose venue is read per event

### Requirement: Deterministic seeding, agent enrichment
Publisher lists SHALL be seeded deterministically (OSM/Overpass city polygon, aggregator
venue-unknowns, demand queue, submissions). The agent SHALL never compile city lists.

#### Scenario: New-city bootstrap
- **WHEN** a city polygon is configured
- **THEN** one Overpass import creates venue publishers with names/coords/websites, and the scout works the resulting queue

### Requirement: Hybrid scout — deterministic fast path first
For each publisher the scout SHALL run deterministic sniffers (ICS, JSON-LD, RSS, feed links,
program-page probes) BEFORE any LLM call, and SHALL invoke the bounded LLM investigation only
when sniffing fails.

#### Scenario: Venue with a hidden ICS feed
- **WHEN** sniffing finds a calendar feed that parses to future events
- **THEN** a verified `ics_feed` recipe is persisted with zero LLM tokens spent

#### Scenario: Messy venue needs reasoning
- **WHEN** sniffers find nothing structured
- **THEN** the LLM loop investigates within hard budgets (≤8 fetches, token and $ caps) and either proposes a recipe or concludes `none`

### Requirement: Recipes are typed and verified by execution
The scout SHALL output recipes only of types `ics_feed | jsonld | rss | html_selector |
aggregator_covered | instagram_lead | none`, schema-validated. A recipe SHALL be persisted as
trusted only if executing it via the real harvest executor yields ≥1 event with a parseable
future date. `html_selector` recipes SHALL additionally require high confidence.

#### Scenario: Hallucinated selector rejected
- **WHEN** a proposed selector recipe yields zero dated events on execution
- **THEN** it is rejected; after one retry the publisher records `none` (with cooldown), never an unverified recipe

#### Scenario: `none` is a result
- **WHEN** a publisher has no machine-readable channel
- **THEN** `none` is persisted with a 90-day cooldown and the scout does not revisit earlier

### Requirement: Deterministic nightly harvest with self-healing
A single executor SHALL run all healthy recipes nightly, writing RAW events to the
`discovered_events` staging table (never directly to `events`). Recipe health SHALL be
tracked; 3 consecutive failures SHALL re-queue the publisher for scouting.

#### Scenario: Site redesign breaks a recipe
- **WHEN** a recipe fails three consecutive nights
- **THEN** it is deactivated and the publisher enters the scout queue (repair loop)

#### Scenario: IP boundary
- **WHEN** harvested events are staged
- **THEN** enrichment (normalize/categorize/facets/embed/upsert) happens only in the private pipeline's staging reader — this repo imports no Pulse code

### Requirement: Demand-first scheduling
The scout SHALL order work: demand queue (`discovery_requests`) first, then publishers with
events-but-no-recipe, then the seeded long tail; respecting cooldowns and staleness cadences
(re-scout 60–90d; `none` 90d).

#### Scenario: Chat miss becomes tomorrow's answer
- **WHEN** users' zero-result searches name a venue
- **THEN** that venue is scouted in the next run before any backlog item

### Requirement: Fetch security wall
Every fetch SHALL enforce: https-only, DNS-resolved public-IP-only (reject private/link-local/
metadata ranges, re-checked per redirect, ≤5 redirects), ≤2 MB, content-type allowlist,
robots.txt compliance, ≥1s per-domain delay, and a ≤3-distinct-domains budget per
investigation. Page text SHALL enter prompts only as delimited data; tool arguments SHALL be
schema-validated.

#### Scenario: Malicious page attempts SSRF
- **WHEN** a fetched page links to an internal address or the scout is instructed by page text to fetch one
- **THEN** the fetch is refused by the wall and the investigation continues on allowed URLs

### Requirement: Traced, budgeted, observable runs
Every scout run SHALL persist a full reasoning trace (`scout_runs`: nodes visited, fetches,
proposals, verification results, tokens, USD, duration) and emit Langfuse traces when
configured. Per-publisher budget exhaustion SHALL abort gracefully and be recorded.

#### Scenario: Runaway publisher aborted
- **WHEN** the $ cap is hit mid-investigation
- **THEN** the run stops, records `budget_exhausted` with its partial trace, and the publisher is not marked scouted

### Requirement: Pilot evaluation gate before scale
Before scaling beyond the pilot, the system SHALL run 50 mixed publishers with the strong
model and report: recipe-type distribution, verification pass rate, cost per publisher and per
discovered event, and golden-venue miss-rate; scaling proceeds only on documented review of
these results.

#### Scenario: Fast-path dominance discovered
- **WHEN** the pilot shows most venues resolve via sniffing alone
- **THEN** the finding is documented and the LLM path is narrowed accordingly (the agent claim is adjusted honestly)
