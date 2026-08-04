# Pulse Discovery Agent

An AI **agent that discovers events for a city by learning how to find them, per venue.**

Most event data is invisible to a scraper: a bar posts its events on its own website, another
only on Instagram, another on Resident Advisor or a Telegram channel. This agent treats
**publishers (not pages) as the durable unit**: for each publisher it *reasons about where that
publisher posts its events*, investigates with tools, and **writes down a typed recipe**
(`publisher_sources`) so cheap deterministic code can harvest it every night forever. The agent is
the scout; boring code does the rest.

**Measured on 43 real Berlin venues:** 10 working recipes at **$0.0088 per discovered event**,
371 events harvested and ingested. Full numbers in [`docs/PILOT-M3.md`](docs/PILOT-M3.md);
what broke and why in [`docs/FINDINGS.md`](docs/FINDINGS.md).

This is a standalone AI-engineering project. It powers [Pulse](https://innerloop-health.vercel.app)
— an event-discovery app for Berlin — but runs **completely on its own** against a local sample
database, so you can try it without any private data or credentials.

## Why an agent (and where not)
Discovering *how* to find a publisher's events is open-ended and per-source — it needs reasoning,
tool use, and memory, so it's a genuine agent (built with **LangGraph**). Everything downstream
(re-harvesting a known channel, ranking, categorising) is deterministic and deliberately **not** an
agent. See `openspec/` for the full rationale.

## How the scout works

```
triage ──► sniff ──► verify ──► persist          deterministic, 0 tokens
   │         │         ▲
   │         └──► investigate ──┘                bounded LLM loop, 1 retry
   └──► persist (no website / Instagram-only)
```

1. **Sniff first, free.** Declared feeds, homepage and program-page JSON-LD, well-known calendar
   paths. In the pilot this resolved **44% of the publishers it could reach, at zero cost** —
   a better hit rate than the LLM path, which is why ordering beats prompt tuning here.
2. **Investigate only if sniffing fails.** The model gets one guarded tool (`fetch_page`) and must
   answer by calling `propose_recipe` with a **typed Pydantic recipe** — free text is not accepted.
   Hard caps on LLM calls, fetches, USD, and wall-clock, all recorded in the trace.
3. **Verify by execution.** A recipe counts only if the *harvest code, run right now*, returns
   list-shaped, future-dated events. In the pilot this **rejected 45 of 55 candidates** — including
   a single-event detail page that looked exactly like a full program (see FINDINGS F2).
4. **Persist** the recipe plus a full `scout_runs` audit row (trace, tokens, USD, seconds).

Every fetch goes through an SSRF wall: https-only, public-IP checks re-verified per redirect,
robots.txt, per-domain politeness, size and content-type caps. Scraped text is wrapped as untrusted
data and the model is instructed never to act on instructions inside it (OWASP LLM01).

## How it connects to Pulse
The agent shares a **database contract**, not code. It reads `publishers`, and writes
`publisher_sources` recipes, `scout_runs` audit rows, and harvested events into a
`discovered_events` staging table. The product reads that staging table; nothing else crosses.

```
[ this repo ]  ── reads publishers / writes recipes + staged events ──►  Postgres
                                                                          ▲
                                    [ Pulse product (private) ] ──────────┘
   config   = DATABASE_URL, or SUPABASE_URL + SUPABASE_SERVICE_KEY, in .env
   contract = schema.sql (the table shapes both sides agree on)
```

Same code, swap the `.env`: point it at the bundled **sample DB** for the demo, or at real Supabase
in production. This repo never contains real data or secrets.

## Quickstart (standalone demo — no real data needed)
```bash
make demo        # spins up a local Postgres with sample venues, runs the scout against it
```
Or step by step:
```bash
cp .env.example .env      # fill in an LLM key (OpenRouter); DB defaults to the local demo DB
make db-up                # start local Postgres + load schema.sql + seed publishers
make install              # install deps (uv)
```

The CLI has three commands:
```bash
discovery-agent queue                  # who's next, demand-queue misses ranked first
discovery-agent scout --limit 25 --mix # find recipes (--mix = category-stratified sample)
discovery-agent scout --no-llm         # sniffers only: zero tokens, zero cost
discovery-agent harvest                # run every saved recipe, stage the events
```

`--dry-run` runs the whole graph without writing. `--no-llm` is worth trying first: it costs
nothing and, per the pilot, still finds a working recipe for a meaningful share of venues.

## Tests
```bash
make test    # 40 tests, no DB / no network / no API key required
make lint
```
That constraint is enforced in CI: the workflow simply never provides a database, a network
fixture, or a key. Telemetry is hard-disabled during tests — an earlier run leaked 15 mock
generations into the real Langfuse project (FINDINGS), and mock traffic corrupts exactly the
numbers you would judge the agent by.

## Layout
| Path | What |
|---|---|
| `schema.sql` | the shared DB contract (`publishers`, `publisher_sources`, `scout_runs`, `discovered_events`) |
| `seed/` | sample publishers so the demo runs standalone |
| `docker-compose.yml` | local Postgres for the demo |
| `src/discovery_agent/graph.py` | the LangGraph state machine (triage/sniff/investigate/verify/persist) |
| `src/discovery_agent/sniffers.py` | the deterministic zero-token fast path |
| `src/discovery_agent/investigator.py` | the bounded LLM tool loop + typed recipe output |
| `src/discovery_agent/guards.py` | the SSRF / robots / budget fetch wall |
| `src/discovery_agent/harvest.py` | the generic executor: one parser per recipe type |
| `src/discovery_agent/observability.py` | Langfuse tracing, guarded so it cannot break a run |
| `scripts/pilot_report.py` | turns `scout_runs` into the evaluation numbers |
| `docs/` | [PILOT-M3.md](docs/PILOT-M3.md) (results + decision), [FINDINGS.md](docs/FINDINGS.md) |
| `openspec/` | the change spec (proposal → design → specs → tasks) driving the build |

## Evaluation
`scripts/pilot_report.py` reads real `scout_runs` and reports outcome distribution, recipe-type
mix, verification pass rate, the free-vs-paid split, cost per publisher / per scouted publisher /
per discovered event, and latency. Every number in the docs came from that script, not an estimate.

## Status
Working end to end and measured on real venues; scaling decision documented in
[`docs/PILOT-M3.md`](docs/PILOT-M3.md). Known-open items are tracked in
`openspec/changes/discovery-agent/tasks.md` — most notably a ground-truth set of hand-verified
golden venues, a cheap-vs-strong model benchmark, and a recipe-rot re-check.
Event data comes from public sources; this is not a medical or safety-critical system.
