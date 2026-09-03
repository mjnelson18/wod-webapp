# CLAUDE.md — WOD Datapacks

Public web app: a near-live data pack for a **draft** Fantasy Premier League among friends.
Supports a weekly podcast (two hosts review the previous gameweek + long-term trends) and
casual viewers who just want the stats. Replaces a manual Jupyter → PNG → static-HTML →
git-commit workflow with an automated pipeline + interactive frontend.

## Architecture (static-first — do not add a server or DB without asking)

```
FPL APIs ──(scheduled GitHub Action)──> pipeline (Python) ──> JSON artifacts ──> React SPA on GitHub Pages
```

- **No always-on server, no database.** Data is tiny (single-digit MB/season), append-only,
  read by a handful of people. A scheduled job + static JSON is the correct scale.
- The Action runs on a cron, self-throttles based on game status (see Pipeline principles),
  and **force-deploys** the built site *including* the JSON data to Pages each run, so git
  history does not bloat with hundreds of data commits.
- Frontend is a static SPA. It never talks to the FPL API directly and holds no secrets.

## Repo layout

The Claude Code working folder **is** the git repo (one repo for the whole project). `/reference`
is committed — `/reference/historical/` is read by the regression tests, so it must be in the repo.
Nothing under `/reference` is served on the site (Pages deploys the build output, not repo source).

```
/pipeline
  /fetchers        # one thin client per endpoint; return raw parsed JSON, no logic
  /transforms      # PURE functions: raw JSON in, output tables out. No I/O, no fetching.
  /config          # season config (league codes, entry_ids, sizes, promo/releg, gw offset)
                   # + sites.py: which seasons/leagues each published site covers
  /cache           # cached raw responses for finalized (immutable) gameweeks
  build.py         # orchestrator: decide what to fetch -> fetch -> transform -> write JSON
/data              # generated JSON output (gitignored; produced at build time)
  /<site>/<season>/  # e.g. wod/2627/ -> players.json, weekly_points.json, ...
/web               # React (Vite) app; .env.<slug> carries each site's branding + base path
/reference         # READ-ONLY inputs, do not treat as source of truth for the app:
  weekly_report_generator.ipynb   # the existing messy logic = the SPEC to port (commit; optional)
  /historical/                    # last seasons' CSVs = the VALIDATION ORACLE (commit — tests need it)
  /old_html/                      # last seasons' rendered reports (content inventory; gitignore if bulky)
/tests
.github/workflows/update.yml
CLAUDE.md
```

## Data model (logical tables + join keys)

The pipeline reproduces these tables (same as the historical CSVs). The valuable part is the
join graph and the gotchas, not the column lists (those are in the CSVs / notebook).

- **players** (`All Players Summary`) — 1 row per footballer. PK `id`.
- **draft_picks** — 1 row per pick. `element` → players.`id`. `short_name` = drafter initials.
  `index` = overall pick number; `pick` = position within a round. Draft is a **snake**
  (ABCDDCBA), so pick→drafter ordering reverses each round.
- **weekly_points** (`Player Points Weekly`) — 1 row per footballer per gameweek. `id` → players.`id`.
- **weekly_summary** — 1 row per drafter per player per gameweek. The richest table:
  starting/benched, auto-subs, `optimal_points`, cumulative %, fixtures/difficulty. `element`/`id`
  → players.`id`.
- **transfers** — waiver + free-transfer moves, incl. *attempted* ones (`result` distinguishes).
  Waiver = priority-ordered, resolved by reverse league position weekly. Free = 24h window pre-lock.
- **trades** — drafter↔drafter swaps. Keep `state`, `offer_time` and `response_time`; `state='p'`
  means *processed*. Trades really do execute, and `event` is the gameweek the swap **takes effect
  in**, so squads change between GW `event-1` and GW `event`. Do **not** filter out the entries in
  `exclude_id` here — that silently hid 9 of 2526's 13 Prem trades. (None existed in 2425.)
- **teams** — `team` ↔ `team_id` lookup used across the point/summary tables.
- Every league-scoped row carries `league_code` (there are two leagues — Premiership + Conference).

Joins: `element` == `id` (footballer); `team` == `team_id` (PL club); `league_code` selects league.

## Seasons & archives

- **Every season is first-class in the same app**, served from one GitHub Pages site with an in-app
  season selector and deep-linkable per-season routes (e.g. `#/2425`).
- **Current season** = live pipeline output (regenerated on the cron).
- **Archived seasons** = frozen JSON, generated **once** and baked into the deploy; never refetched.
  - **2425:** raw is gone forever — generate archive JSON from the `/reference/historical/` CSVs via
    the adapter. Logic can't be re-validated for 2425; schema/plausibility sanity-check only.
  - **2526:** the live API still serves 2526 raw as of late July 2026, until the 2627 rollover.
    **Snapshot it immediately** (see Validation) and commit to `/reference/raw_2526/`. Generate the
    2526 archive JSON by running the pipeline on that snapshot (native canonical schema), and
    cross-check it equals the CSV-derived version.
  - Note the FPL API only serves the current season, so once 2627 opens, 2526 raw is unrecoverable.
- **One canonical JSON schema** for all seasons. The live pipeline emits it; the adapter maps the
  historical CSV columns onto it. Where an older season lacks a column a current-season view needs,
  the frontend must degrade gracefully (hide/grey-out that view for that season), never error.

## Sites

One repo publishes **two independent data packs** from the same pipeline and app:

- **`wod`** — What's On Draft: Premiership + Conference, plus the 2425/2526 archives. Root of Pages.
- **`dunelmliga`** — a different group of friends. One standalone league, first season 2026/27, no
  promotion or relegation, no comparison drawn to the WOD leagues. Served at `/dunelmliga/`.

Scope lives in `pipeline/config/sites.py`; branding and base path live in `web/.env.<slug>`. Data
is namespaced per site (`data/<slug>/<season>/`) and the deploy copies one site's folder in as the
app's `data/`, so **the frontend never sees a site slug** — don't add one to it. A view that a site
can't support must degrade (hide the tab, drop the stat), never error. Everything below describes
the WOD leagues unless it says otherwise.

**Two scoring modes.** WOD leagues are classic — the table is points banked. Dunelmliga is
head-to-head: each gameweek is a fixture, 3/1/0, and its gameweek view leads with that table and
keeps the points one below it. The mode is discovered from the league payload into
`meta.leagues[].scoring`, never configured. Don't assume a league's table is its points total.

## Domain rules

- Two leagues of six: **Premiership** and **Conference**. 2 promoted / 2 relegated per season.
  **Assume this going forward** — 6/6 and 2-up/2-down is the settled structure.
- **Season 2425 was the one exception: 5 in Premiership, 7 in Conference, 3 up / 1 down** — new
  joiners had to start in the Conference that year. League sizes and promo/releg counts stay
  per-season **config** (never hardcoded), but only so the 2425 archive builds correctly; don't
  treat varying league size as a live design constraint.
- One entry may be excluded per league via `exclude_id`: in 2526 that is league_entry **92234**
  (entry 95076), Peter Vickers' Premiership team. He organised both leagues but only played the
  Conference, filling the Prem squad with deliberate dud picks. Because that entry *did* draft in
  the Prem snake, dropping its picks leaves gaps in `index`, so surviving picks must be renumbered
  1..N before `round` is derived. Excluding it is right for standings/draft/summary tables and
  **wrong for trades** (see above).
- Points during a live match are **provisional**; bonus points are added after matches finish.
  A gameweek is only immutable once fully finalized (bonus applied, no live fixtures).
- Auto-subs: benched players replace non-playing starters per FPL rules; `optimal_points` is the
  best-possible lineup in hindsight. This logic lives in the notebook — port it, don't reinvent.

## Pipeline principles

- **The notebook is the spec.** Port its transformation logic; do not invent new stat definitions.
  If the notebook is ambiguous, ask — don't guess a formula.
- **Incremental / no wasted work.** Finalized past gameweeks never change → fetch once, cache raw
  response, never refetch. Each run refetches only: game status, the current (in-progress) GW, and
  anything not yet cached. This is the #1 fix vs. the old notebook (which re-looped all history).
- **Transforms are pure.** `raw JSON -> DataFrame/dict`. No network, no file writes inside them.
  This is what makes them testable against the historical CSVs.
- **Gameweeks are 1-indexed everywhere**, matching FPL's `event` field (GW1 = first week). The old
  `event/{gameweek+1}` was only compensating for a zero-based Python loop — do **not** carry the
  `+1` forward; use the gameweek number directly.
- Output both **raw tables** (for the data explorer) and **pre-computed per-view JSON** (so the
  mobile client isn't crunching large tables for charts).

## Config (must be data, not code)

Per season: `season_id`, `league_code` per league, `entry_id` per drafter, league sizes,
promotion/relegation mapping to the prior season. Fill placeholders:

```
# pipeline/config/2627.py  (example — real values TBD)
LEAGUE_CODES = {"premiership": "<FILL IN>", "conference": "<FILL IN>"}
ENTRY_IDS    = { "<short_name>": <entry_id>, ... }   # discover via league details endpoint
```

## Frontend conventions

- **Mobile-first.** The old report was laptop-only; phone usability is a hard requirement.
- Charts: **Recharts** (interactive tooltips/hover). Data tables/filtering: **TanStack Table**.
  Do not pull in ECharts or DuckDB-WASM without asking (weight/complexity).
- **Season selector.** All seasons load from per-season canonical JSON; a selector switches between
  them and each season is deep-linkable. Views that need columns a season lacks degrade gracefully.
- SPA on GitHub Pages: set Vite `base` to the repo path; add a `404.html` fallback (or use hash
  routing) so deep links work on Pages.
- No secrets, no API keys, no direct FPL calls from the browser. It only fetches local JSON.

## Commands

```
# pipeline
python pipeline/build.py --season 2627          # incremental build
python pipeline/build.py --season 2627 --full    # ignore cache, rebuild from scratch
pytest                                            # incl. historical regression tests

# web
cd web && npm run dev                             # local dev
cd web && npm run build                           # production build
```

## Validation (acceptance test for the refactor)

The goal is to prove the refactored pipeline reproduces the old notebook's logic on identical input.

- **2526 is the oracle — but the window is closing.** The live API still serves complete 2526 raw
  data until the 2627 rollover (which may come as soon as the new-season draft opens, potentially
  before the first match). **Snapshot every 2526 endpoint now** (all 38 GWs, all entries, league
  details/choices/transactions/trades, both bootstraps, fixtures) into `/reference/raw_2526/` and
  commit it. Then run the new pipeline on that snapshot and assert its output equals the 2526 CSVs
  column-for-column. A full completed season is the strongest possible regression test.
- **PART OF THAT SNAPSHOT IS THE WRONG SEASON — see the Gotchas entry below.** It was taken in late
  July 2026, after `/api/fixtures/` and the fantasy bootstrap's `teams[]` had already rolled over
  to 2026/27. `fixtures.json` and `bootstrap_static_fantasy.json` in `/reference/raw_2526/` are
  **not** 2025/26 and must not be used as an oracle. The per-gameweek `event/*` payloads and the
  draft bootstrap are fine. Anything needing 2025/26's real schedule, club list or element→club
  mapping should read the pipeline's own output for that season instead.
- **2425 can't be validated** (no raw, ever). Schema/plausibility sanity-check on the CSV-derived
  archive only.
- Handle 2425's 5/7 split and 3-up/1-down correctly regardless.

Any intentional cleanup that changes a value must be listed explicitly. **A refactor that can't
reproduce the 2526 numbers from 2526 raw is wrong.**

## Gotchas

- FPL APIs are **public read endpoints** — no auth, no credentials, no secrets in the job. (Do a
  one-off unauthenticated sanity check at build time to confirm each still returns data.)
- GitHub Actions cron: 5-min minimum, and short schedules get delayed/dropped. Target near-live
  (~10–15 min during matches), not true-live.
- **60-day cron auto-disable.** On public repos GitHub disables scheduled workflows after 60 days
  with no new commits. The off-season exceeds this, so the cron switches itself off ~summer. Plan:
  re-enable it (one click) when onboarding the new season — you're editing config then anyway. A
  monthly keepalive workflow is the automated alternative if you'd rather it never lapse.
- Provisional vs. final points/bonus — don't cache a gameweek as immutable until it's truly done.
- Season 2425's 5/7 split will break any code that assumes 6/6.
- **`draft/<league>/choices` is not a history.** It serves the league's current or *next* draft, so
  a league with a second draft scheduled (Dunelmliga re-drafts at GW21) returns an empty list for a
  draft that already happened. Snapshot a draft the day it finishes; `League.draft_choices_fallback`
  points at the committed copy, used only when the API serves none.
- **The bootstrap's `total_points`/`minutes` change meaning at GW1.** Before the season opens they
  are *last* season's totals, which is what makes the pre-season draft board exact. From GW1 they
  are this season's — the highest total in the whole bootstrap on GW1 day was 15. Anything wanting
  last season's numbers mid-season must read the previous season's archive instead, joined on
  `code` (permanent) and never on `element` (reassigned yearly) — see `attach_prior_season`.
- **A raw snapshot can contain more than one season, and nothing in it says so.** Two files in
  `/reference/raw_2526/` are actually 2026/27, because they were captured after those endpoints
  rolled over while others had not:
  - `fixtures.json` — 380 fixtures with kickoffs in **August 2026**, none finished.
  - `bootstrap_static_fantasy.json` — the 2026/27 **team list**: COV, HUL and IPS are present and
    BUR, WHU and WOL are missing, so 2025/26 players map onto next season's clubs.

  Nothing caught this for months: the clubs looked plausible and every lookup returned *a* fixture
  for *a* club. The one hard regression test reads recorded points and never touches a fixture, so
  it kept passing. Measured against the real schedule, the snapshot matched the true opponent
  **2.2%** of the time and the true venue **47.8%** — a coin flip. When taking a snapshot, assert
  the kickoff years and the club list against the season it claims to be; a rollover does not move
  every endpoint at once.
- **An unplayed fixture has no score, and that is not nil-nil.** `fillna(0)` on
  `team_h_score`/`team_a_score` turned every future fixture into a completed goalless draw — 753 of
  760 rows at GW3 — so nothing downstream could tell "not played" from "finished 0-0". Use nullable
  `Int64` and let the gap reach JSON as `null`; the frontend already renders that as a dash.
- **`meta.gameweeks` is the list of gameweeks that have been PLAYED**, so it is `[1]` in August.
  Anything looking *forward* must take its gameweeks from the fixture table, which is published for
  all 38 up front. Filtering `meta.gameweeks` for weeks after the current one is always empty, which
  is how the fixture look-ahead silently rendered nothing for a whole season.

## Non-goals / do not do

- Do not add a database or long-running server.
- Do not silently drop or add report sections — content changes go through the user (curation step).
- Do not reimplement stat definitions from scratch; port them from the notebook.
- Do not commit generated `/data` JSON to `main` history.
