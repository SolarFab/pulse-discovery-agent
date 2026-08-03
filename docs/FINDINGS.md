# Findings — Publisher Discovery Agent

Empirical notes from building and running the scout against real Berlin venues.
Every number here comes from a real run, not an estimate.

---

## F1 · The seeded publisher set had no websites at all

**Observed.** All 2,770 seeded publishers had `website` and `instagram` NULL, and the
source `venues` table had `website_url`/`instagram_handle` NULL for all 2,803 rows.
The scout had literally nothing to investigate; the queue was empty for a reason
that looked like a query bug.

**Why it matters.** The agent's input is not "a venue name" — it is "a venue name and
a place to look". Seeding names is not seeding publishers. This turned task 4.1
(OpenStreetMap import) from a nice-to-have into the critical path.

**Resolution.** `scripts/enrich_publishers_overpass.py` matches publishers to OSM
venues by normalized-exact name and copies `website` / `contact:instagram` /
category. Conservative by design: names that normalize to several different sites
are dropped and counted (66 of them), never guessed — a wrong website costs a paid
scout run and pollutes the contract. **612 of 2,770** publishers gained a channel.

---

## F2 · A single event's detail page looks exactly like a full program

**Observed.** The first sniffer pass reported 3 successes in 25 venues. All three had
exactly one event. The sniffer had followed a program link to an event *detail* page
(e.g. `astra-berlin.de/events/2026-08-08-queer-westling-circus`), which carries valid
schema.org `Event` JSON-LD and whose URL contains "events" — indistinguishable from a
program page by every signal the sniffer was using.

**Why it matters.** That recipe would have pinned the venue to one event forever, and
it would have looked like a success in every metric. This is the exact failure mode
the execution-verification gate exists to prevent, and the gate passed it, because it
only asked "does this yield ≥1 future event?".

**Resolution.** A program must be **list-shaped**: `MIN_PROGRAM_EVENTS = 3` for
page-embedded types (`jsonld`, `html_selector`), enforced in the sniffer *and* the
verification gate. Feeds (`ics_feed`, `rss`) keep a threshold of 1 — they are lists by
construction. Program links are now also sorted shallow-path-first, so `/programm`
is fetched before `/events/2026-08-08-some-show`.

**Corrected result on the same 25 venues: 3 "successes" → 1 real one.**

---

## F3 · The sniffer was starving the LLM of its entire fetch budget

**Observed.** In the first LLM pilot, **0 of 9** paid investigations produced a working
recipe, at $0.45. The traces showed `abort: fetch budget` on 10 of 12 runs.

**Cause.** The sniffer and the investigator share one `FetchSession` — correct, since
politeness delays, the robots cache, and the domain wall are per-publisher. But they
also shared its fetch *counter*. Sniffing routinely used 5–12 fetches, so by the time
`investigate()` ran, `session.fetches` was already past `scout_max_fetches = 8` and the
loop aborted before its first fetch. The model was being paid to think with no eyes.

**Why it matters.** Every symptom pointed at model capability ("the LLM can't find
programs"), and the real cause was an accounting bug in my own budget code. Without
the trace recording *why* each run aborted, the wrong conclusion was the obvious one.

**Resolution.** The LLM's allowance is counted from a baseline taken when
investigation starts; the sniffer gets its own cap (`scout_max_sniff_fetches = 12`);
and a per-publisher wall-clock deadline (`scout_max_seconds = 300`) stops runaway runs
(one observed at 716s).

---

## F4 · Dead domains are not venues without programs

**Observed.** Several OSM-sourced websites did not resolve at all (`aedesbar.de`,
`anton-saefkow-bibliothek.de`), and one legitimate homepage (A-Trane) was refused
outright for exceeding the 2MB response cap.

**Resolution.** An unreachable homepage now produces a distinct `unreachable` outcome
that **skips the LLM entirely** — a model cannot fetch what the security wall could
not reach, so paying it to try is pure waste. Oversized responses of an *allowed*
content type are truncated rather than refused; the parts that matter (feed links,
JSON-LD, program markup) are near the top of the document anyway.

---

## F5 · An alphabetical queue measures the wrong venues

**Observed.** The backlog is ordered by creation date, which in practice is
alphabetical: 8MM, Ankerklause, Baiz, Bar Bobu — corner bars that have no event
program by nature. Measuring the scout's hit rate on those understates it and teaches
nothing about whether the approach works.

**Resolution.** `publishers.category` (new column, OSM-derived) plus
`scout --mix`, which draws an even sample across event-likely categories *and* bars/
pubs, so the low end is measured honestly rather than quietly excluded. Real
distribution across the 612 enriched publishers:

| category | n | | category | n |
|---|---|---|---|---|
| theatre | 102 | | pub | 38 |
| nightclub | 84 | | library | 36 |
| museum | 75 | | gallery | 34 |
| bar | 68 | | community_centre | 33 |
| cinema | 44 | | events_venue | 25 |
| arts_centre | 40 | | music_venue | 6 |

---

## F6 · Long runs must stream, or they look dead

**Observed.** A 25-venue run produced no console output for over an hour while
working correctly — Python block-buffers stdout when it is piped or redirected, and
the CLI only printed its summary at the end.

**Resolution.** Per-publisher results stream with `flush=True` as each finishes.
Progress that only exists in a buffer is not progress you can supervise.
