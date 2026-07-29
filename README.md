# Pulse Discovery Agent

An AI **agent that discovers events for a city by learning how to find them, per venue.**

Most event data is invisible to a scraper: a bar posts its events on its own website, another
only on Instagram, another on Resident Advisor or a Telegram channel. This agent treats **venues
(not pages) as the durable unit**: for each venue it *reasons about where that venue publishes its
events*, tries tools to find them, and **writes down the recipe** (`venue_sources`) so cheap
deterministic scrapers can exploit it forever. The agent is the scout; boring code does the rest.

This is a standalone AI-engineering project. It powers [Pulse](https://innerloop-health.vercel.app)
— an event-discovery app for Berlin — but runs **completely on its own** against a local sample
database, so you can try it without any private data or credentials.

## Why an agent (and where not)
Discovering *how* to find a venue's events is open-ended and per-source — it needs reasoning,
tool use, and memory, so it's a genuine agent (built with **LangGraph**). Everything downstream
(re-scraping a known channel, ranking, categorising) is deterministic and deliberately **not** an
agent. See `openspec/` for the full rationale.

## How it connects to Pulse
The agent shares a **database contract**, not code. It reads `venues`, and writes discovered
`events` + `venue_sources` recipes.

```
[ this repo ]  ── reads venues / writes events+recipes ──►  Postgres  ◄── [ Pulse product (private) ]
   config = DATABASE_URL in .env  (a local sample DB for the demo; real Supabase in production)
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
cp .env.example .env      # fill in an LLM key (OpenRouter/Anthropic); DB defaults to the local demo DB
make db-up                # start local Postgres + load schema.sql + seed venues
make install              # install deps (uv)
make run                  # run the discovery scout over the seeded venues
```

## Layout
| Path | What |
|---|---|
| `schema.sql` | the shared DB contract (`venues`, `events`, `venue_sources`) |
| `seed/` | sample venues so the demo runs standalone |
| `docker-compose.yml` | local Postgres for the demo |
| `src/discovery_agent/` | the agent: `config`, `db`, `tools`, `graph` (LangGraph), `main` |
| `openspec/` | the change spec (proposal → design → specs → tasks) driving the build |

## Status
Scaffold. The behaviour is specified in `openspec/changes/discovery-agent/` and implemented against
those tasks. Not a medical/production system; event data comes from public sources.
