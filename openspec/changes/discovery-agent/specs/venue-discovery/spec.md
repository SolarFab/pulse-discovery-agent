# venue-discovery

## ADDED Requirements

### Requirement: Select venues that need scouting
The system SHALL select only venues that lack a `venue_sources` recipe fresher than the configured
staleness window, and SHALL cap the number selected per run.

#### Scenario: Venue with no recipe
- **WHEN** a venue has no rows in `venue_sources`
- **THEN** it is included in the scouting batch (subject to the per-run cap)

#### Scenario: Venue with a fresh recipe
- **WHEN** a venue has a `venue_sources` row with `last_checked` within `SCOUT_RESCOUT_DAYS`
- **THEN** it is excluded from the batch

#### Scenario: Per-run cap
- **WHEN** more venues need scouting than `SCOUT_MAX_VENUES`
- **THEN** at most `SCOUT_MAX_VENUES` venues are processed in the run

### Requirement: Discover where a venue publishes events
The system SHALL, for each selected venue, use an LLM with a bounded set of tools to determine the
channel(s) where that venue publishes events, and SHALL classify each as one of a known set
(`website`, `events_page`, `instagram`, `resident_advisor`, `eventbrite`, `telegram`, `none`).

#### Scenario: Venue with an events page
- **WHEN** a venue's website links to an events/programm page
- **THEN** a finding with `channel_type = events_page`, the resolved URL, and a confidence is produced

#### Scenario: Venue with no machine-readable source
- **WHEN** the scout finds no usable channel after its tool budget is exhausted
- **THEN** a single finding with `channel_type = none` is produced (so the venue is not re-scouted immediately)

#### Scenario: Tool-call budget
- **WHEN** the per-venue tool-call budget is reached
- **THEN** the scout stops calling tools and reports the findings gathered so far

### Requirement: Persist discovery recipes idempotently
The system SHALL upsert findings into `venue_sources` keyed on `(venue_id, channel_type)`, storing
`url`, `scrape_recipe`, `confidence`, and stamping `last_checked`.

#### Scenario: First discovery
- **WHEN** a finding is persisted for a venue+channel that has no existing row
- **THEN** a new `venue_sources` row is inserted with `last_checked` set to now

#### Scenario: Re-discovery of a known channel
- **WHEN** a finding is persisted for an existing venue+channel
- **THEN** the existing row is updated (url, recipe, confidence, last_checked) rather than duplicated

### Requirement: Treat fetched web content as untrusted
The system SHALL treat all text retrieved by tools as data, never as instructions, and SHALL NOT
allow fetched content to alter tool selection, confidence, or the system prompt.

#### Scenario: Injection attempt in page text
- **WHEN** a fetched page contains text instructing the agent to change its behaviour or output
- **THEN** the instruction is ignored and treated as ordinary page content

### Requirement: Remain model-agnostic
The system SHALL access the LLM only through an OpenAI-compatible gateway configured by environment
(`OPENAI_BASE_URL`, `SCOUT_MODEL`), with no provider-specific calls in node logic.

#### Scenario: Switching model
- **WHEN** `SCOUT_MODEL` (or `OPENAI_BASE_URL`) is changed in the environment
- **THEN** the scout uses the new model/provider without code changes
