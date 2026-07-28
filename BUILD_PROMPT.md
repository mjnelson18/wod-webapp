# Build prompt — paste into Claude Code

Read `CLAUDE.md` first. Then follow the phases below. **Stop at every checkpoint marked
🛑 and wait for my answer — do not proceed past it.** When anything is ambiguous in a way
that changes the output, ask a focused question instead of guessing. Prefer the simplest
thing that works; flag any dependency or abstraction you're about to add that I didn't ask for.

## Setup
This working folder **is** the git repo for the project — build everything here. `/reference` is
committed (`/reference/historical/` is needed by the tests); `/data` is gitignored and regenerated
each build. Nothing in `/reference` is served on the site.

## Inputs I've provided in `/reference`
- `weekly_report_generator.ipynb` — my existing, messy, organically-grown logic. **This is the
  spec for all data transformations.** Port it; don't invent new stat definitions.
- `/reference/historical/` — CSVs for seasons 2425 and 2526. **These are the validation oracle.**
- `/reference/old_html/` — last season's rendered reports. Source for the content inventory.

## Phase 0a — Snapshot 2526 raw (⚠️ DO THIS FIRST — time-limited)
The live API still serves complete 2526 season data, but only until the 2627 rollover, which may
come as soon as the new-season draft opens (possibly before the first match). Once it flips, 2526
raw is gone forever. So before any refactoring:
1. I'll give you the 2526 `league_code`. Write a quick scrape-everything script (throwaway quality
   is fine — completeness matters, not cleanliness) that saves the raw JSON from every endpoint for
   2526 into `/reference/raw_2526/`: game status, league details, draft choices, both bootstraps,
   fixtures, `event/{gw}/live` for all 38 GWs, `entry/{entry_id}/event/{gw}` for every entry × GW,
   transactions, trades. Derive entry_ids from league details.
2. Run it, verify the files look complete (spot-check a few GWs), and commit `/reference/raw_2526/`.
3. 🛑 **CHECKPOINT:** confirm the snapshot is captured and committed before moving on. This fixture
   is the regression oracle and the source for the 2526 archive — don't proceed until it's safe.

## Phase 0b — Recon (no code yet)
1. Read the notebook end to end. Produce a written map of: every API endpoint it calls, every
   output table/column it derives, every chart it renders, and the transformation logic behind
   each. Call out logic that is duplicated, dead, or re-computes unchanging history.
2. The FPL APIs are public — no auth. Do a quick unauthenticated call to each endpoint to confirm
   it returns data, then proceed. (No credentials or secrets in the pipeline.)
3. Gameweeks are 1-indexed (GW1 = first week). The old `event/{gameweek+1}` was just a zero-based
   Python loop artifact — drop the `+1` and use the gameweek number directly throughout.

## Phase 1 — Pipeline skeleton (fetch + pure transforms)
1. Scaffold `/pipeline` per the layout in CLAUDE.md: thin `fetchers`, PURE `transforms`, `config`,
   raw-response `cache`, `build.py` orchestrator.
2. Move all season-variable values into `pipeline/config` (league codes, entry_ids, league sizes,
   promo/releg). Leave clearly-marked `<FILL IN>` placeholders for the real league codes /
   entry_ids — I'll provide them, or you discover entry_ids from the league details endpoint.
3. Port the notebook's transforms as pure functions (raw JSON in → table out, no I/O). Preserve
   the existing stat definitions exactly. Where the notebook is unclear, ask. Emit a single
   **canonical JSON schema** per table (same shape for every season).
4. Write the **archive generators**: 2425 → canonical JSON from the `/reference/historical/` CSVs
   via an adapter (remember the 5/7 split); 2526 → canonical JSON by running the pipeline on the
   `/reference/raw_2526/` snapshot, cross-checked against the 2526 CSV. If a season lacks a column
   the canonical schema has, leave it null (the frontend handles absence). Archives are frozen.
5. Implement incremental logic: cache raw responses for finalized gameweeks; each run refetches
   only game status + the in-progress gameweek + anything uncached. Do not re-loop history.

## Phase 2 — Validate the refactor (do this before the frontend)
1. **2526 (the oracle):** run the new pipeline on the `/reference/raw_2526/` snapshot and assert its
   output equals the 2526 CSVs column-for-column. A full completed season is the strongest test.
2. **2425:** raw is gone — schema/plausibility sanity-check on the CSV-derived archive only. Do not
   claim logic-equivalence for 2425.
3. Handle 2425's 5/7 split and 3-up/1-down correctly.
4. 🛑 **CHECKPOINT:** show me the diff report for 2526 (matches, mismatches, and any intentional
   cleanups that change values). Do not move on until the new pipeline reproduces the 2526 numbers.

## Phase 3 — Data artifacts + scheduled build
1. Have `build.py` write per-season JSON: both raw tables (for the data explorer) and pre-computed
   per-view JSON (so the mobile client stays light).
2. Write `.github/workflows/update.yml`: a cron that runs `build.py`, self-throttles on game status
   (early-exit + no deploy when nothing changed), builds the frontend, and **force-deploys site +
   data to GitHub Pages** (no data commits to `main` history). Target ~10–15 min cadence during
   live matches, daily between gameweeks, weekly/off in the off-season.
3. Note in the README that GitHub auto-disables scheduled workflows after 60 days of no commits, so
   the cron will lapse over the off-season and must be re-enabled (one click) at season start. Do
   NOT add a keepalive workflow unless I ask.
4. 🛑 **CHECKPOINT:** propose the exact cron schedule and throttling rules for me to approve.

## Phase 4 — Content inventory & curation (my call)
1. From the notebook + `/reference/old_html/`, produce a single list of **every** section, chart,
   and metric the current report shows, each with a one-line description.
2. 🛑 **CHECKPOINT:** present that list. I will mark keep / cut / merge and note anything missing.
   **Do not design the frontend information architecture until I've curated.** Don't drop or add
   sections on your own judgement.

## Phase 5 — Frontend (React, mobile-first)
1. Scaffold Vite + React in `/web`. Set `base` for Pages; add `404.html`/hash routing for deep links.
2. **Season selector:** load per-season canonical JSON (current + archived 2425/2526), switch
   between seasons in-app, deep-linkable per season. Any view needing a column a season lacks must
   hide/grey-out for that season, never error.
3. Build the curated views. Charts via Recharts (hover/tooltips). A raw-data explorer with
   filterable/sortable tables via TanStack Table for ad-hoc questions.
3. Mobile-first and genuinely usable on a phone is a hard requirement — verify layouts at narrow
   widths, not just desktop.
4. Frontend fetches local JSON only. No secrets, no direct FPL calls.
5. If you want to reach for ECharts or DuckDB-WASM, ask first — default is Recharts + TanStack.

## Phase 6 — Ship & document
1. Wire the Pages deploy end to end; confirm a full run produces a live, current site.
2. Update `CLAUDE.md` if the build revealed anything (real config values stay out of git if sensitive).
3. Write a short `README` covering: how a new season is onboarded (which config to fill), how to
   run locally, and how the scheduled update works.

## Standing rules for this build
- Concise progress notes: what changed and why, not a re-explanation of whole files.
- Match conventions you establish; don't churn style.
- If you think a step in this plan is wrong or over-complex, say so before doing it.
