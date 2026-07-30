# Data contract — pipeline → frontend

The interface between `pipeline/build.py` and the React app. The frontend fetches these files and
nothing else; it never calls the FPL API.

Currently produced by `scripts/make-dev-fixtures.mjs` (dev fixtures from the historical CSVs) so
the frontend could be built while Python was blocked. **The pipeline replaces that script and must
emit this same shape.** Delete the script once it does.

## Location

```
web/public/data/                 # gitignored; written at build time
  seasons.json                   # which seasons exist
  <season>/                      # e.g. 2526/
    meta.json
    league_table.json
    weekly_summary.json
    weekly_points.json
    draft_picks.json
    transfers.json
    trades.json
    players.json
    teams.json
    season_review_facts.json
```

The GitHub Action writes `/data/<season>/` and copies it to `web/public/data/` before
`npm run build`, so `/data` stays gitignored and out of `main`'s history.

## `seasons.json`

```json
{ "seasons": [ { "season": "2526", "label": "2025/26", "current_gameweek": 38, "complete": true } ],
  "default": "2526" }
```

## `meta.json`

Drives the season selector, gameweek chips, league toggle and — importantly — the
**capability flags**.

```json
{
  "season": "2526", "label": "2025/26",
  "current_gameweek": 38, "total_gameweeks": 38, "complete": true,
  "gameweeks": [1, 2, "…", 38],
  "leagues": [ { "code": "Prem", "name": "Premiership", "size": 6, "relegated": 2 },
               { "code": "Conf", "name": "Conference",  "size": 6, "promoted": 2 } ],
  "drafters": [ { "short_name": "TS", "name": "Tom Shiel", "league": "Prem" } ],
  "capabilities": {
    "fixtures": true, "difficulty": true, "cost": true, "ownership_by_league": true,
    "draft_round": true, "cumulative": true, "team_names": true, "trades": true,
    "optimal_points": true
  }
}
```

### Capabilities are how seasons degrade gracefully

A view checks the flag and renders an "unavailable for this season" notice instead of erroring or
drawing an empty chart. 2425 has **all of these false except `optimal_points`**, which makes it the
test case — its CSVs carry no per-league ownership, no fixtures, no cost, no draft round and no
trades. Any new view that depends on a column must gate on a flag.

`leagues[].size` matters beyond display: the Leagues view compares **mean points per drafter**, not
league totals, because 2425 ran 5 Prem vs 7 Conf and raw totals hand every gameweek to the larger
league on squad count alone.

## Table shapes

Records (array of objects), `null` for a column a season lacks — never omitted, never `NaN`.

| File | Grain | Key fields |
|---|---|---|
| `league_table` | one row per drafter | `league`, `short_name`, `name`, `rank`, `total`, `gameweek_points`, `form_points`, `form_rank`, `points_by_gameweek[]`, `cumulative_by_gameweek[]` |
| `weekly_summary` | drafter × squad slot × gameweek | `gameweek`, `league`, `short_name`, `element`, `place`, `web_name`, `position`, `team_id`, `team_name`, `total_points`, `points_scored`, `points_before_auto_subs`, `originally_starting`, `optimal_points`, `player_total_points`, `points_scored_cumulative`, `drafter_name`, `draft_index`, `round`, `in_original_draft`, `opposition`, `home_away`, `team_difficulty`, `opposition_difficulty` |
| `weekly_points` | element × gameweek (reduced, see below) | `gameweek`, `league`, `element`, `web_name`, `position`, `team_name`, `total_points`, `rank_in_week`, `owner`, `place`, `is_benched`, `drafter_name` |
| `draft_picks` | one row per pick | `league`, `short_name`, `index`, `pick`, `round`, `element`, `web_name`, `position`, `team_name`, `draft_rank`, `now_cost`, `selected_by_percent`, `total_points` |
| `transfers` | one row per move, **including failed attempts** | `league`, `gameweek`, `short_name`, `kind`, `result`, `priority`, `element_in`, `element_out`, `player_in`, `player_out`, `player_in_points`, `player_out_points`, `net_points` |
| `trades` | one row per trade item | `league`, `gameweek`, `offered_by`, `received_by`, `element_in`, `element_out`, `player_in`, `player_out`, `player_in_points`, `player_out_points`, `net_points`, `state` |
| `players` | one row per footballer | `element`, `web_name`, `position`, `team_id`, `team_name`, `total_points`, `goals_scored`, `assists`, `bonus`, `clean_sheets`, `minutes`, `draft_rank`, `now_cost`, `selected_by_percent` |
| `teams` | one row per PL club | `team_id`, `team_name` |

Conventions that differ from the notebook's CSVs, and are deliberate:

- `league` replaces `league_code`, and carries the short code (`Prem` / `Conf`).
- `element` is the footballer id everywhere. The CSVs' `element_x` / `element_y` are merge
  artifacts and always identical — collapsed to one column.
- `owner` replaces `player_points_weekly.short_name`, since that column held the *owning drafter*,
  not the row's drafter, and the `' (Benched)'` suffix is dropped in favour of `is_benched`.
- Display strings stay out of data: `player_in` is `"Cunha"`, not `"Cunha (117)"`.
- `short_name` is always upper-case.

## `season_review_facts.json`

The one output that isn't a table. A nested dict of **story beats** for the season review
tab: final standings, how the title race moved, the best and worst weeks, draft hits and
misses, the transfers and trades that mattered, points left on the bench, and Prem v Conf.
Produced by `pipeline/transforms/narrative.py`.

```json
{ "season": "2526", "label": "2025/26", "complete": true,
  "leagues": [ { "code": "Prem", "champion": {…}, "final_table": […], "race": {…},
                 "extremes": {…}, "draft": {…}, "moves": {…}, "bench": {…} } ],
  "cross_league": { "weekly": […], "record": {…}, "champion_crossover": […] } }
```

Two rules it follows, both of which matter more than the exact keys:

- **A beat is absent, never zero.** 2425 has no trades, so there is no `best_trade` key at
  all — rather than a trade worth 0 points, which reads as a finding. Anything consuming
  this must treat every beat as optional.
- **Moves are only reported when they can be scored.** 2425's CSV transfers carry player
  names and no element ids, so ids are recovered from unambiguous names; rows that still
  can't be resolved are excluded from the valued beats and `moves.counts.valued` records
  how many survived.

The prose that sits alongside it is **not** in the data pack — it lives in
`web/src/content/season-review/<season>.md`, is written by hand once a season ends, and is
committed. That split is the point: the honours strip renders from this JSON so headline
numbers can't drift, while the writing stays a human artefact that no cron run rewrites.

## Payload size — the mobile constraint

Measured on the 2526 fixtures:

| File | Size | Note |
|---|---|---|
| `weekly_summary.json` | 3.2 MB | 6,840 rows × 24 cols |
| `weekly_points.json` | 1.6 MB | reduced from 59,494 → 7,815 rows |
| everything else | < 0.6 MB | |

Two rules follow, both already implemented in the app:

1. **Load lazily, per view.** `lib/data.js` caches per file and a view requests only what it needs.
   Views are `React.lazy`, so the gameweek grid loads ~68 KB gzip and never pulls Recharts.
2. **`weekly_points` is reduced.** The raw table is one row per element per gameweek *per league* —
   59,494 rows for 2526, of which 52,654 are undrafted players. The fixtures keep owned rows plus
   undrafted players who ranked top-20 in a gameweek, which is all the "top scorers not drafted"
   and "best available" views need. **The pipeline should apply the same reduction**, and emit the
   full table only if the explorer is later given a paged loader.

CLAUDE.md's "pre-computed per-view JSON" is the next step: `league_table` already ships
`points_by_gameweek[]` and `cumulative_by_gameweek[]` precomputed so the trends chart does no
aggregation on the client. Extend that pattern to the season summary and draft-pick tables rather
than shipping bigger raw tables.
