# Tasks — Discovery Agent

## 1. Foundations
- [x] 1.1 Repo scaffold (uv, Ruff, pytest, pre-commit, Makefile, Docker compose)
- [x] 1.2 `schema.sql` contract with `venue_sources` + seed venues
- [x] 1.3 `config.py` settings (DB, model-agnostic gateway, cost caps)
- [x] 1.4 `db.py` read/write helpers (`venues_needing_scout`, `upsert_venue_source`)
- [x] 1.5 Smoke tests green with no DB/network

## 2. Selection
- [ ] 2.1 Verify `venues_needing_scout` honours staleness window and per-run cap (add a DB-backed test, opt-in)
- [ ] 2.2 Log which venues were selected vs skipped (and why) for observability

## 3. Scout node (the agent)
- [ ] 3.1 Build the OpenAI-compatible client from settings; assert no provider-specific imports in node logic
- [ ] 3.2 Bind `fetch_url` / `find_events_page` / `check_resident_advisor` as callable tools
- [ ] 3.3 Implement the bounded tool-calling loop (respect the per-venue `steps` budget)
- [ ] 3.4 Force structured `findings` output (Pydantic model: channel_type ∈ known set, url, scrape_recipe, confidence)
- [ ] 3.5 Emit `channel_type = none` when nothing usable is found
- [ ] 3.6 Harden the untrusted-input boundary: no page text may alter tool choice/confidence/system prompt

## 4. Persist
- [ ] 4.1 Validate findings against the schema before write
- [ ] 4.2 Upsert idempotently on `(venue_id, channel_type)`, stamping `last_checked`

## 5. Verification probe (optional, cost-aware)
- [ ] 5.1 For a claimed channel, cheaply confirm it lists dated events before high confidence
- [ ] 5.2 Downgrade confidence when the probe fails

## 6. Quality & demo
- [ ] 6.1 Unit-test the injection guard (page with adversarial text → instruction ignored)
- [ ] 6.2 Unit-test upsert idempotency (same venue+channel twice → one row, updated)
- [ ] 6.3 `make demo` runs the scout end-to-end over seeded venues on the local DB
- [ ] 6.4 README quickstart verified from a clean checkout
