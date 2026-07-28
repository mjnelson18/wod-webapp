# Notebook recon — `reference/weekly_report_generator.ipynb`

Phase 0b output: a complete map of the notebook that the pipeline must reproduce.
46 cells, ~140k chars of source. Cell numbers below are 0-indexed as stored in the `.ipynb`.

Verified against the 2526 raw snapshot and the 2526 CSVs where noted.

---

## 1. API endpoints

All 10 endpoints the notebook calls, all public/unauthenticated, all confirmed returning data
on 2026-07-28 via the Phase 0a snapshot.

| # | Endpoint | Cell | Feeds | Status |
|---|---|---|---|---|
| 1 | `draft/api/game` | 2 | `current_event` | ✅ 2526 |
| 2 | `draft/api/league/{code}/details` | 3 | `league_table`, entry_ids | ✅ 2526 |
| 3 | `draft/api/bootstrap-static` | 5 | `all_players`, `teams` | ✅ 2526 |
| 4 | `draft/api/draft/{code}/choices` | 10 | `draft_picks` | ✅ 2526 |
| 5 | `draft/api/event/{gw}/live` | 12 | element points per GW | ✅ 2526 |
| 6 | `draft/api/entry/{entry_id}/event/{gw}` | 12 | picks + subs per entry per GW | ✅ 2526 |
| 7 | `draft/api/draft/league/{code}/transactions` | 23 | `transfers` | ✅ 2526 |
| 8 | `draft/api/draft/league/{code}/trades` | 25 | `trade_history` | ✅ 2526 |
| 9 | `fantasy/api/bootstrap-static` | 7 | `now_cost`, `selected_by_percent`, team strengths | ⚠️ **already 2627** |
| 10 | `fantasy/api/fixtures/` | 8 | `fixtures`, `fixtures_by_team` | ⚠️ **already 2627** |

`draft.premierleague.com` and `fantasy.premierleague.com` roll over **independently**. As of the
snapshot the draft host still served completed 2526 (all 38 GWs finished) while the fantasy host
had already flipped to 2627 (GW1 deadline 2026-08-21, 0 finished). See §6.1.

**Gameweek indexing.** Cell 12 loops `for gameweek in range(current_week)` and requests
`event/{gameweek+1}` / `entry/{id}/event/{gameweek+1}`. The `+1` is purely a zero-based-loop
artifact — GW1 is `event/1`. The pipeline iterates `1..current_week` and drops the `+1`.

---

## 2. Output tables

Column lists below are the CSV headers (the notebook's actual output), in CSV order.

### 2.1 `teams` — cell 5
`team`, `team_name`. From draft bootstrap `teams[].id` / `teams[].short_name`. 20 rows.

### 2.2 `league_table` / `live_league_table` — cells 3, 4, 15, 16
From league details. `league_entries` gives `entry_id, entry_name, id, short_name, first_name,
last_name`; `standings` gives `event_total→gameweek_points, total, rank, last_rank`. Inner-merged
on `league_entry == id`.

- `short_name` uppercased; first/last name `.capitalize()`; `name = first + ' ' + last`.
- **Rows with `id == exclude_id` (92234) are dropped.** That is Peter Vickers' Premiership
  entry — he organised both leagues but only played Conference, and filled the Prem squad with
  deliberate dud picks. Prem therefore has 7 API entries → 6 real drafters.
- Cell 15 rebuilds the table *live* from `weekly_summary` rather than trusting `standings`:
  `cumulative_points` = cumsum of per-GW `points_scored`; `gameweek_rank` = rank(method='min',
  desc) within (league, gameweek); `previous_gameweek_rank` = that shifted 1, `fillna(0)`.
- Cell 16 adds form over the last `form_games=5` GWs: mean `points_scored` per GW, ranked
  `method='dense'`; plus `points_from_top`, `points_from_safety`, `points_above_relegation`
  (Prem) and `points_from_promotion`, `points_above_chicken_suit` (Conf).

### 2.3 `all_players` (`All Players Summary`) — cells 5, 7
`id, web_name, team, team_name, position, total_points, goals_scored, assists, bonus,
clean_sheets, minutes, draft_rank, selected_by_percent, now_cost`. 841 rows.

`position` from `element_types.singular_name_short`; `team_name` from draft `teams.short_name`;
`now_cost` divided by 10. Last two columns come from the fantasy bootstrap via
`merge(..., on="id", how="inner")` — see §6.1, this join is now cross-season.

### 2.4 `fixtures` / `fixtures_by_team` — cell 8
Per-fixture rows are exploded into one row per team per fixture (home + away), then aggregated to
one row per `(gameweek, team)` so double gameweeks collapse:

- `gameweek_matches` = count of fixtures that GW
- `opposition` = opponents joined with `-`, order preserved, **de-duplicated** (`ARS-LIV`)
- `home_away` = `H`/`A` joined with `''`, order preserved, **not** de-duplicated (`HA`)
- `team_score`, `opposition_score`, `team_difficulty`, `opposition_difficulty` = **mean** across
  that GW's fixtures
- `kickoff_time_first` = min kickoff
- scores `fillna(0).astype(int)` before aggregation, so unplayed fixtures read as 0-0

### 2.5 `draft_picks` (`Draft Picks`) — cell 10
`element, short_name, index, pick, web_name, league_code, position, draft_rank, now_cost,
selected_by_percent, team, team_name, first_name, last_name, round, id, total_points`. 180 rows
(12 drafters × 15 rounds; the excluded entry's 15 dud picks are dropped by the inner merge).

- `index` = overall pick number, `pick` = position within round, from `choices`.
- `round = ((index - 1) // 6) + 1` — **hardcoded 6**, see §6.2.
- `index` is then overwritten for Prem rows with a running `range(1, len(df)+1)` — see §6.2.
- `total_points` appended in cell 12 from `player_points_weekly` grouped by
  (league_code, short_name, element).

### 2.6 `weekly_summary` (`Weekly Summary`) — cell 12 (+ 36)
The richest table. 6840 rows = 12 drafters × 15 squad slots × 38 GWs.

`element, place, gameweek, short_name, league_code, originally_starting, id, total_points,
points_before_auto_subs, player_total_points, web_name, position, team_id, team_name,
drafter_name, draft_index, points_scored, index, round, in_original_draft, optimal_points, total,
points_scored_pct, points_scored_cumulative, team, gameweek_matches, opposition, home_away,
team_score, opposition_score, team_difficulty, opposition_difficulty, kickoff_time_first,
optimal_weight`

Derivations:

| Column | Logic |
|---|---|
| `place` | the entry's `picks[].position` (1–11 = starting XI, 12–15 = bench) **after** auto-subs |
| `originally_starting` | `position <= 11` → 1, then for each sub: `element_in` → 0, `element_out` → 1. I.e. the lineup *before* auto-subs |
| `total_points` | element's `stats.total_points` from `event/{gw}/live` |
| `points_before_auto_subs` | `total_points` where `originally_starting == 1`, else 0 |
| `points_scored` | `total_points` where `place <= 11`, else 0 — i.e. what the drafter banked |
| `player_total_points` | that element's summed points over all GWs 1..current_week (all elements, not squad-restricted) |
| `drafter_name` | who originally drafted the element in *this* league; `'Not Originally Drafted'` if nobody |
| `draft_index` | that drafter's overall pick number |
| `index`, `round` | from `draft_picks` joined on (element, short_name) — non-null only if *this* drafter drafted them; `fillna(0)` |
| `in_original_draft` | 1 if `index` was non-null, else 0 |
| `total` | drafter's season total from `standings` |
| `points_scored_pct` | `points_scored / total` |
| `points_scored_cumulative` | cumsum of `points_scored` over (league_code, short_name, id) |
| `optimal_points` | see §3 |
| `optimal_weight` | added in cell 36 as `optimal_points / total_points` — **NaN when `total_points == 0`** (exactly 946 of 6840 rows). Not the same variable `calc_optimal_points` computes internally |
| fixture columns | left-merged from `fixtures_by_team` on (gameweek, team_name) |

### 2.7 `player_points_weekly` (`Player Points Weekly`) — cell 12
One row per element per GW **per league**. 59,494 rows, exactly 29,747 per league — every element
appears twice, once per league. **This duplication is intentional, not a bug:** a footballer can
be owned by different drafters in each league, so each league needs its own ownership view.

`id, total_points, gameweek, rank_in_week, element_x, short_name, place, isBenched, league_code,
element_y, web_name, position, team_id, team_name, drafter_name, draft_index, team,
gameweek_matches, opposition, home_away, team_score, opposition_score, team_difficulty,
opposition_difficulty, kickoff_time_first`

- `rank_in_week` = rank of `total_points` within a GW, `method='min'`, descending — across **all**
  elements, not just owned ones.
- `short_name` = current owner, `'Not Drafted'` if unowned (52,654 of 59,494 rows), with
  `' (Benched)'` appended when `place > 11`.
- `isBenched` = `place > 11`.
- `element_x` / `element_y` are merge artifacts and are **always equal** — collapse to one column.

### 2.8 `transfers` (`Transfers`) — cells 23, 28
`league_code, date_added, gameweek, short_name, kind, result, index, priority, position,
element_in, player_in, element_out, player_out, player_in_points_scored_in_week,
player_out_points_scored_in_week, net_points_of_transfer_in_week, abs_net_trade,
transfer_category`. 1206 rows from 1248 raw transactions (42 dropped by inner joins).

- `kind`: `w` → `waiver`, `f` → `free agent`.
- `result`: `a` → `successful`, `do` → `unsuccessful - player out already gone`,
  `di` → `unsuccessful - player in already been picked up`. **Any other code becomes NaN.**
- Includes *attempted* transfers, which is the point — the report counts failed waivers.
- `player_in`/`player_out` are mutated into display strings: `"Name (points)"`.
- `net_points_of_transfer_in_week` = in-week points of player in minus player out;
  `abs_net_trade` = its absolute value.
- `transfer_category` = `kind + ' - ' + result` (added in cell 28).

### 2.9 `trade_history` (`trade_history`) — cell 25
`league_code, GW traded, offered_by, received_by, element_in, player_in, element_out, player_out,
player_in_total_points, player_out_total_points, net_points_from_trade, Points Since Trade`.

- `player_in_total_points` / `player_out_total_points` = each player's points summed **from the
  trade gameweek to the end of the season** (achieved by merging without a GW key, then filtering
  `event <= gameweek`). Verified: reproduces the CSV's 112/86, 117/88, 32/38 exactly.
- `net_points_from_trade` = in minus out. `Points Since Trade` is a prose sentence.
- Empty-league guard returns an empty frame with a *different* column set.
- See §6.3 — the API has 13 trades, the CSV has 3, and none of them actually executed.

### 2.10 Derived summary tables (not persisted to CSV)
| Table | Cell | Content |
|---|---|---|
| `agg_summary` | 34, 35 | Per drafter: `draft_points`, `points_gained_through_waivers`, `squad_points`, `bench_strength`, `optimal_points`, `points_lost_choosing_starting_XI`, `points_before_auto_subs`, `points_gained_with_auto_subs`, `net_points_lost_through_subs`, `points_scored` + per-league average rows |
| `league_h2h_print` | 22 | Prem vs Conf total points per GW, win flags, running-total row |
| `league_comparison` | 21 | Top-18-ranked players owned in one league but `'Not Drafted'` in the other |
| `impact_of_subs` | 27 | `net_points_lost_through_subs` (current GW) + `total_points_lost_through_subs` (season) |
| `formation_comparison` | 36 | Count of each chosen `DEF-MID-FWD` formation vs mean optimal formation |
| `overlap_matrix` | 38 | Conf drafters × Prem drafters, count of shared players in the current GW |
| `player_points_pivot_topn` | 37 | Top 10 players by league total, owner+score per GW, last 8 weeks |
| `available_form_players` | 42 | Top 5 undrafted players per position by mean points over last 6 GWs |
| `form_points` | 16 | Mean `points_scored` over last 5 GWs + `form_rank` |

---

## 3. `optimal_points` — the one genuinely subtle transform (cell 12)

Best-possible XI in hindsight, under FPL formation rules: exactly 1 GKP, ≥3 DEF, ≥1 FWD, ≥2 MID,
11 total.

Algorithm:
1. Force the mandatory core — top 1 GKP, top 3 DEF, top 1 FWD by `total_points`.
2. From the remaining outfielders (excluding the second GKP), enumerate **all** size-6
   combinations, keep those satisfying the MID minimum, and take the max total.
3. Ties are **averaged, not broken arbitrarily.** Both the mandatory selection and the final
   6-pick set distribute weight uniformly across tied-optimal solutions, producing a fractional
   `optimal_weight` per player. `optimal_points = total_points × optimal_weight`.

Forcing the top-k mandatory players is sound (an exchange argument holds, since surplus DEF/FWD
can still be picked in the extra 6), so this yields the true optimum.

The fractional weighting is **real and must be reproduced exactly** — 1555 of 6840 CSV rows carry
non-integer `optimal_points` (e.g. `0.7777777777777778`). A naive "pick the best XI, break ties
arbitrarily" implementation will not match.

Cell 11 holds an earlier, fully commented-out version of this function — dead, 138 lines, ignore.

---

## 4. Charts

Ten PNG families, each rendered once per league (`Prem`, `Conf`), named
`{chart}_{league}_GW{week}.png`.

| Cell | File stem | Content |
|---|---|---|
| 17 | `gameweek_highs_lows` | Count of GW-high and GW-low finishes per drafter |
| 19 | `point_distribution` | GW scores binned into 10-point buckets, one labelled block per GW; bold outline = GW high |
| 20 | `cumulative_points` | Expanding-mean weekly points per drafter (y-axis hardcoded 35–55) |
| 26 | `weekly_points_heatmap` | **Flagship.** Current-GW squad grid, drafters as columns ordered by season total, `place` as rows, starter/bench divider after row 11. Each cell annotates transfer flag (W/F/AW), sub flag (SN/SF), name, points, position, club, draft round or trade/transfer GW, season total and points realised |
| 27 | `weekly_sub_points_barchart` | Points lost to sub choices — season total (grey) vs current GW (blue) |
| 28 | `transfer_activity` | Stacked successful vs failed transfers per drafter by category |
| 29 | `unique_players_used` | Unique players in squad vs unique players started |
| 31 | `heatmap_{position,team_name}` | % of a drafter's points by position, and by PL club (two variants) |
| 32 | `draft_players_remaining` | Count of original draft picks still held, by GW |
| 33 | `draft_picks_..._realised_outline_other_owned` | Top-N draft picks: points realised by drafter vs by others vs unrealised |

Colour palette (cell 18) is a fixed 6-colour map reused across both leagues, keyed by drafter
initials, plus grey for `Not Drafted`.

## 5. Report sections (cells 39–41)

`generate_weekly_report` emits one `weekly_report_GW{n}.html`; cell 40's `update_index_html`
rebuilds an index. Section order:

1. Premiership Table · 2. Conference Table · 3. Leagues Head to Head (+ *Top scoring players not
drafted*) · 4. Points Summaries (Prem / Conf) · 5. Choice of Substitutions · 6. Transfer Activity
(+ *Unique Players Used*) · 7. Trade History · 8. Draft Pick Performance (+ *Drafted Players
Remaining*) · 9. Season Summary (+ *Top N Players last X weeks*, *Chosen starting formation*) ·
10. Team Points Distribution · 11. Position Points Distribution · 12. Player Overlap Matrix ·
13. GW Results & Next Fixtures (*This Week*, *Next 6*)

Full curation list follows in Phase 4.

---

## 6. Problems to fix or decide

### 6.1 The fantasy API has already rolled over to 2627 ⚠️
`fantasy/bootstrap-static` and `fantasy/fixtures/` now serve 2627. Two consequences:

- **`all_players` is now silently wrong.** Cell 7 does `merge(fantasy_players, on="id",
  how="inner")`, and element IDs are reassigned every season, so 2526 players get joined to 2627
  IDs — wrong `now_cost` and `selected_by_percent` per player, with no error raised. Harmless for
  the live 2627 pipeline (both hosts will agree); it only affects rebuilding the 2526 archive.
- **2526 fixture data can't be refetched.** Resolved as agreed: rebuild `opposition`,
  `home_away`, `team_score`, `opposition_score`, `gameweek_matches` and kickoffs from the
  draft-side `event/{gw}/live` payload (which carries `team_h`, `team_a`, both scores and
  `kickoff_time`), and backfill the four fantasy-only columns — `team_difficulty`,
  `opposition_difficulty`, `now_cost`, `selected_by_percent` — from the 2526 CSVs.

### 6.2 League size is hardcoded — breaks 2425
- `round = ((index - 1) // 6) + 1` (cell 10) assumes 6 drafters. 2425 was 5 Prem / 7 Conf.
- Cell 16 hardcodes rank 4/5/6 for Prem safety and relegation and rank 2 for Conf promotion.
  2425 was 3 up / 1 down.
Both move to per-season config.

### 6.3 `draft_picks['index']` renumbering — intentional, but fragile
Cell 10 does:
```python
draft_picks['index'] = np.where(draft_picks['league_code'] == 'Prem',
                                range(1, len(draft_picks) + 1), draft_picks['index'])
draft_picks['round'] = ((draft_picks['index'] - 1) // 6) + 1
```
**This is deliberate, not a bug.** The excluded admin entry (92234) genuinely drafted in the
Premiership snake — it holds 15 of the 105 Prem choices, including pick 5 of round 1. Dropping
those picks leaves gaps in the raw `index` (1, 2, 3, 4, 6, 7, …), and because Prem ran with 7
entries a raw round is 7 picks wide, not 6. Renumbering the 90 survivors 1..90 restores a
contiguous sequence that `// 6` then divides into 15 correct rounds.

Verified against `Draft Picks_2526.csv`: sorting choices by raw `index`, dropping excluded
entries, renumbering 1..N and recomputing `round` reproduces **both leagues with 0 mismatches**
on `index` and `round`.

The implementation is fragile rather than wrong — it relies on Prem rows landing first and in
pick order through two inner merges and a `concat`, and the preceding `sort_values(...)` result is
discarded (no assignment, no `inplace`), so nothing actually enforces that order. The pipeline
implements the *intent* deterministically, per league:

1. sort `choices` by raw `index`
2. drop picks belonging to excluded entries
3. renumber `index` sequentially 1..N
4. `round = ((index - 1) // n_real_drafters) + 1`, with `n_real_drafters` from season config

That generalises to 2425's 5 Prem / 7 Conf split, which the hardcoded `// 6` cannot.

`pick` (position within the raw round) is left untouched by the notebook, so for Prem it stays
1..7 while `index` runs 1..90.

### 6.4 Trades: the notebook table doesn't mean what it looks like
- The Prem API returns **13 trades, all `state='p'`**; Conf returns 0. The notebook never filters
  on `state`.
- I verified squad membership either side of every trade GW: **not one of them executed.** In
  every case the offering entry still holds `element_in` before *and* after, and the receiving
  entry keeps `element_out`. These are unaccepted *offers*.
- 9 of the 13 vanish only because they were offered to the excluded entry 95076 and the inner
  join on the league table drops them.
- That leaves 4 candidate rows, but `trade_history_2526.csv` has **3** — the GW22 JP→MN
  Gyökeres/Woltemade offer is missing even though it computes cleanly (net +44). The CSV also
  stores `element_in` as a float (`237.0`) whereas the current cell ends with `.astype(int)`.
  Both point to the CSV having been written by an **earlier version of cell 25**, so it is not a
  faithful oracle for this table.
- Note this contradicts `CLAUDE.md`, which describes trades as "accepted only".

### 6.5 Recomputes all history on every run
Cell 12 loops every GW × every entry and refetches `event/{gw}/live` and
`entry/{id}/event/{gw}` from scratch — ~500 HTTP calls per run for data that is immutable once a
GW finalises. Then `calc_optimal_points` re-solves the combinatorial optimum for all
12 × 38 = 456 squad-weeks. This is the single biggest win from the refactor: cache finalised GWs
and only recompute the live one.

### 6.6 Duplicated and dead code
- Cells 34 and 35 build `agg_summary` twice; 35 supersedes 34 (adds league-average rows and int
  casts). Cell 34 is dead.
- Cell 11: 138 lines, entirely commented out.
- Cells 6, 9, 13, 14, 24, 30, 43, 44, 45: bare variable names, Jupyter display only.
- Cell 23 renames `total_points_scored_after_gameweek`, a column that never exists — no-op.
- `get_league_table` is re-fetched inside `get_draft_picks`, `get_weekly_summary`,
  `get_transfer_history` and `get_trade_history` — 4 redundant HTTP calls per league.
- Cell 27's `total_points_lost_through_subs` groups by `short_name` only, omitting `league_code`;
  safe today only because initials happen to be unique once 92234 is excluded.

### 6.7 Cosmetic output artifacts
Reproduce for a column-for-column match, then clean up deliberately and record it in the diff
report: `element_x`/`element_y` (always identical), `optimal_weight` NaN on zero-point rows,
display strings baked into data columns (`player_in` = `"Name (12)"`), and the space in the
`GW traded` / `Points Since Trade` column names.

---

## 7. Decisions taken

1. **§6.1 2526 fantasy columns** — rebuild the draft-derivable fixture columns from
   `event/{gw}/live`; backfill `team_difficulty`, `opposition_difficulty`, `now_cost` and
   `selected_by_percent` from the 2526 CSVs. Those four are flagged in the diff report as
   CSV-sourced rather than reproduced from raw.
2. **§6.2 league sizes** — per-season config, never hardcoded.
3. **§6.3 draft index** — confirmed intentional; implement the renumbering intent
   deterministically per league, driven by config, as set out above.
4. **§6.4 trades** — emit **all** trade offers with a `state` column and **no** `exclude_id`
   filter, so the nine offers made to the organiser's dead Prem entry are visible. This
   deliberately does not match `trade_history_2526.csv` (3 rows vs 13); trades are recorded as
   **not validatable against the CSV**, since that CSV was written by an earlier version of cell
   25. Whether the report keeps a trades *section* is a Phase 4 curation question.
