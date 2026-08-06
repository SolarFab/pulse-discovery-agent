# The concierge — the code the experiments measure

The four files here are the system under test. They are **excerpts from a private product
repo**, included so a reviewer can read the artifact behind every number in `../reports/`
rather than taking the results on trust. They are not runnable in isolation: their imports
(`@/lib/supabase/server`, `./anonClient`, `./embedQuery`) and the database they query stay
in the product.

What is deliberately absent: how events get *into* the database. The scrapers, the sources
they read, and the ingest pipeline are the product's own work and are not part of what these
experiments evaluate.

| File | What to look at |
|---|---|
| `route.ts` | The endpoint, and **the system prompt** — the artifact `benchmark_prompts.py` tested across 9 models |
| `tools.ts` | The two tool definitions the model calls, and the deterministic guards around them |
| `match_events.sql` | **The retrieval itself**: vector similarity ranked *inside* strict SQL filters |
| `match_events_title_boost.sql` | The revision that added a lexical title boost — see finding F3 |

## How the RAG loop actually works

There is no separate retriever service. One loop:

```
user question
  → model resolves relative dates itself ("tonight" → ISO window)
  → search_events(filters…, query)          tools.ts
      → embed the free-text query
      → match_events(...)                    match_events.sql
          filters are STRICT SQL; the embedding only ranks WITHIN them
  → compact rows back to the model (no descriptions — get_event_details drills in)
  → answer, grounded, each event cited by its exact id
```

The split between *filter* and *rank* is the central design decision. A date, a price cap or
a family-friendly requirement is a constraint, not a preference — expressing those as vector
similarity produces confident, wrong answers. So SQL narrows, and the embedding only orders
what survives.

## Things worth noticing, and why they are there

Most of these exist because something failed first; `../reports/CONCIERGE-FINDINGS.md` has
the full accounting.

- **`CHAT_MODEL` is an env var.** The stage-2 benchmark winner ships by changing a variable,
  not code. Its default is a 31B open model that scored a perfect 14/14 against the judge and
  resisted prompt injection at roughly an eighth of the cost of the obvious commercial pick.
- **Date guards in code, not in the prompt** (`tools.ts`). The prompt asks the model not to
  search the past; the tool layer *enforces* it by clamping `date_from`. Prompts ask nicely,
  code decides.
- **Berlin-time conversion before the model sees a timestamp.** Models read clock digits
  literally, so a UTC 18:00 in the payload became "18:00" in an answer about a 20:00 gig.
- **Degraded mode.** If the embedding service is down, `search_events` falls back to
  filter-only and tells the model so, instead of failing the turn.
- **Untrusted-data framing in the system prompt.** Titles and descriptions are scraped text;
  the prompt states they are data and never instructions (OWASP LLM01).
- **The grounding rules are blunt on purpose** — "NEVER name venues from memory", every event
  cited by id. A model that knows Berlin will happily recommend a real club that has no event
  that night, which is worse than saying nothing.
- **`log_discovery_miss` on an empty result.** A search that finds nothing is the purest
  signal of demand the product lacks — it feeds the discovery agent's queue. This is where
  the two halves of this repo meet.
