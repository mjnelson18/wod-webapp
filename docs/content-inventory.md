# Content inventory — everything the current report shows

Phase 4 deliverable. Source: notebook cells 15–42 plus the last **complete** rendered report,
`reference/old_html/weekly_report_GW37.html` (22 headings, 11 tables, 20 images).

> `weekly_report_GW38.html` was regenerated on 2026-07-28 and is **truncated** — it stops
> mid-document at "Chosen starting formation" with no closing tags, 16 headings instead of 22.
> That is the fantasy-API rollover breaking the notebook (see recon §6.1), so GW37 is the
> canonical inventory.

Every chart is rendered **twice — once per league** (Prem, Conf). "Chart ×2" below means exactly
that, not two different charts.

**How to curate:** mark each numbered item **K**eep / **C**ut / **M**erge-with-#. Nothing here is
dropped or added without your say-so.

---

## 1. Premiership Table  *(§1 heading)*

| # | Item | Type | Description |
|---|---|---|---|
| 1 | Prem league table | table | Rank, last rank, name, team name, GW points, total, form points, form rank. Rebuilt live from `weekly_summary` rather than the API standings. |
| 2 | `points_from_top` | metric | Gap from the league leader's total. |
| 3 | `points_from_safety` | metric | Gap to the lowest safe position. **Hardcoded to rank 4/3** — needs to be config-driven. |
| 4 | `points_above_relegation` | metric | Cushion above the relegation line. **Hardcoded to rank 5/6.** |
| 5 | Rolling average weekly points | chart ×2 | `cumulative_points_*.png` — expanding-mean points per GW per drafter, one labelled line each. **Y-axis hardcoded to 35–55**, so it clips whenever scores fall outside that band. |
| 6 | Points distribution blocks | chart ×2 | `point_distribution_*.png` — every GW as a labelled block stacked into 10-point bins; bold outline marks that week's high score. |

## 2. Conference Table  *(§2)*

| # | Item | Type | Description |
|---|---|---|---|
| 7 | Conf league table | table | Same columns as #1. |
| 8 | `points_from_promotion` | metric | Gap to the promotion place. **Hardcoded to rank 2.** |
| 9 | `points_above_chicken_suit` | metric | Cushion above last place — i.e. above the forfeit. |
| 10 | Rolling average weekly points | chart ×2 | Conf rendering of #5. |
| 11 | Points distribution blocks | chart ×2 | Conf rendering of #6. |

## 3. Leagues Head to Head  *(§3)*

| # | Item | Type | Description |
|---|---|---|---|
| 12 | Prem vs Conf per GW | table | Total points scored by each league each GW, win flag per league, plus a running-total row. |
| 13 | Top scoring players not drafted | table | Players ranked top-18 in a GW who were owned in one league but undrafted in the other — the "your league missed this guy" table. |

## 4. Points Summaries  *(§4)*

| # | Item | Type | Description |
|---|---|---|---|
| 14 | **Weekly points heatmap** | chart ×2 | **The flagship.** Current-GW squad grid: drafters as columns (ordered by season total, GW total beneath each), squad places 1–15 as rows, heavy line after row 11 dividing starters from bench, cell shade = points scored. Each cell packs: transfer flag, sub flag, player, GW points, position, club, acquisition route, season total, and points realised by that drafter. |
| 15 | Cell flag legend | legend | `W` waiver this week · `F` free agent this week · `AW` attempted waiver · `SN` subbed on · `SF` subbed off · `D#` draft round · `Tn#` transferred in GW# · `Td#` traded in GW# · `S` season total · `R` points realised by drafter. |

> `Td#` is correct — trades genuinely execute (recon §6.4). An earlier draft of this doc claimed
> otherwise off the back of a gameweek-offset error; disregard that.

## 5. Choice of Substitutions  *(§5)*

| # | Item | Type | Description |
|---|---|---|---|
| 16 | Impact of subs | chart ×2 | `weekly_sub_points_barchart_*.png` — horizontal bars per drafter: season-total points lost to sub choices (grey) against this GW's loss (blue). |
| 17 | `net_points_lost_through_subs` | metric | `optimal_points − points_scored` for the current GW: what a perfect lineup would have added. |
| 18 | `total_points_lost_through_subs` | metric | Same across the whole season to date. |

## 6. Transfer Activity  *(§6)*

| # | Item | Type | Description |
|---|---|---|---|
| 19 | Transfer log | table | Every waiver and free-agent move including failed attempts: date, GW, drafter, kind, result, waiver priority, player in/out with their in-week points, and net points of the move. |
| 20 | Transfer activity chart | chart ×2 | `transfer_activity_*.png` — stacked bars per drafter, successful (waiver/free) beside failed (player already gone / already picked up). |
| 21 | `net_points_of_transfer_in_week` | metric | In-week points of player in minus player out — did the move pay off that week. |
| 22 | Unique players used | chart ×2 | `unique_players_used_*.png` — unique players held vs unique players actually started, per drafter, over the season. |

## 7. Trade History  *(§7)*

| # | Item | Type | Description |
|---|---|---|---|
| 23 | Trade table | table | GW, who offered, who received, players both ways, each player's points from the trade GW to season end, net points, and a prose summary line. |
| 24 | `net_points_from_trade` | metric | Points-since-trade for the player in minus the player out. |

> **KEEP** (curated). Trades do execute. The notebook shows only 3 of 13 because the `exclude_id`
> inner join drops the 9 involving the organiser's Prem entry, and the CSV is stale. The pipeline
> emits all 13 with `state`, `offer_time` and `response_time` — unaccepted trades included, per
> your call.

## 8. Draft Pick Performance  *(§8)*

| # | Item | Type | Description |
|---|---|---|---|
| 25 | Draft pick value | chart ×2 | `draft_picks_*_realised_outline_other_owned.png` — one bar per pick in draft order (top N per drafter), coloured by drafter, split into points realised by the drafter / realised by someone else / never realised. Outline marks picks still held. |
| 26 | `points_realised_by_drafter` | metric | Points this player banked *for the drafter who picked them*. |
| 27 | `points_realised_by_other` | metric | Points they banked for a different owner in that league after moving on. |
| 28 | `points_unrealised` | metric | Points scored for nobody — benched or unowned. |
| 29 | `still_owned` | metric | Whether the pick is still with its original drafter. |
| 30 | Drafted players remaining | chart ×2 | `draft_players_remaining_*.png` — count of original picks still held, by GW. |

## 9. Season Summary  *(§9)*

| # | Item | Type | Description |
|---|---|---|---|
| 31 | Points summary table | table | Per drafter, with league-average rows appended: draft points → waiver gains → squad points → bench strength → optimal points → points lost picking the XI → points before auto-subs → auto-sub gains → net sub loss → points scored. |
| 32 | `draft_points` | metric | Total points scored by everyone this drafter originally drafted, wherever they ended up. |
| 33 | `points_gained_through_waivers` | metric | Squad points minus draft points — value added by transfers. |
| 34 | `bench_strength` | metric | `optimal_points − squad_points`. |
| 35 | `points_lost_choosing_starting_XI` | metric | `points_before_auto_subs − optimal_points`. |
| 36 | `points_gained_with_auto_subs` | metric | `points_scored − points_before_auto_subs` — what FPL's auto-subs rescued. |
| 37 | Top 10 players, last 8 weeks | table | Highest-scoring players by league total over the trailing 8 GWs, with owner and score per GW. |
| 38 | Chosen starting formation | table | Count of each `DEF-MID-FWD` formation a drafter started, next to their mean optimal formation. |

## 10. Team Points Distribution  *(§10)*

| # | Item | Type | Description |
|---|---|---|---|
| 39 | Points by PL club | chart ×2 | `heatmap_team_name_*.png` — % of each drafter's points coming from each Premier League club. |

## 11. Position Points Distribution  *(§11)*

| # | Item | Type | Description |
|---|---|---|---|
| 40 | Points by position | chart ×2 | `heatmap_position_*.png` — % of each drafter's points by GKP/DEF/MID/FWD. |

## 12. Player Overlap Matrix  *(§12)*

| # | Item | Type | Description |
|---|---|---|---|
| 41 | Cross-league overlap | table | Conf drafters × Prem drafters, counting players both currently hold. Blue gradient. |

## 13. GW Results & Next Fixtures  *(§13)*

| # | Item | Type | Description |
|---|---|---|---|
| 42 | This week's results | panel | Current-GW fixtures grouped by day with scores. |
| 43 | Next 6 fixtures | table | Per-club grid of the next 6 opponents with difficulty shading. **Difficulty is fantasy-API-only** and unavailable for 2526 except via CSV backfill. |

## 14. Site-level

| # | Item | Type | Description |
|---|---|---|---|
| 44 | Report index | page | `index.html` — flat list of all 38 gameweek links, newest first. Replaced by the SPA's routing. |
| 45 | Nav buttons + back-to-top | nav | In-page jump links per section. |

---

## Generated but never published

| # | Item | Type | Description |
|---|---|---|---|
| 46 | Gameweek highs & lows | chart ×2 | ❌ **CUT** (curated). `gameweek_highs_lows_*.png` — count of GW-high and GW-low finishes per drafter. 56 PNGs written across the season, referenced by zero reports. Deliberately dropped and replaced by the score histogram (#6 / #11). Cell 17 should be deleted rather than ported. |

## Computed in the notebook but never rendered

| # | Item | Type | Description |
|---|---|---|---|
| 47 | Best available free agents | table | Cell 42 — top 5 undrafted players per position by mean points over the last 6 GWs. A natural "who should you pick up" panel; currently output to the notebook only. |
| 48 | Player overlap between leagues (`league_comparison`) | table | Cell 21 feeds #13; the fuller pivot is discarded. |

---

## Candidates for new views (not in the current report — flagging, not adding)

The pipeline will emit these as data regardless; they only become views if you want them.

| # | Item | Description |
|---|---|---|
| 49 | Per-drafter season page | One drafter's squad, transfers, and points over the whole season on a single page. |
| 50 | Raw data explorer | Required by CLAUDE.md — sortable/filterable tables over every canonical table for ad-hoc questions. |
| 51 | Cross-season records | Now that 2425/2526/2627 share a schema: highest GW score ever, best draft pick, etc. |
| 52 | Waiver priority effectiveness | `priority` is already captured in transfers but never analysed. |

---

## Curation decisions (answered)

1. **Split gameweek from season.** Two distinct areas rather than one scrolling report:
   - **This Gameweek** — per-GW stats and analysis: the heatmap (#14), GW tables, subs impact for
     the week (#17), this week's transfers and trades, results (#42).
   - **Season Trends** — longer-term: rolling averages (#5), score histogram (#6), season summary
     (#31), draft pick performance (#25–30), distributions (#39, #40), unique players (#22),
     drafted players remaining (#30), season-long transfer activity (#20).
   Section-by-section assignment goes in the Phase 5 IA proposal.
2. **Prem/Conf toggle** for everything currently duplicated per league — replaces 20 stacked
   images with 10 toggled views, which is the single biggest mobile win. **Exception:** Leagues
   Head to Head (#12) shows both by definition and keeps its combined view.
3. **New: League Comparison** — a fuller cross-league view living alongside H2H (#12). Draws on
   `league_comparison` (#48, currently discarded) and the overlap matrix (#41): which league is
   stronger, who each league missed, shared players. Marked as an addition, not a silent one.
4. **#46 highs and lows** — cut, already replaced by the histogram.
5. **#23 trades** — keep, unaccepted trades included.
6. **League structure** — 6 per league, 2 up / 2 down from 2526 onward. 2425's 5/7 and 3-up/1-down
   was a one-off from new joiners starting in the Conference; it lives in config only so the 2425
   archive builds, and the promo/relegation metrics (#3, #4, #8) become config-driven rather than
   hardcoded ranks.

## Still open

- Where exactly each of #1–#48 lands across **This Gameweek** vs **Season Trends** vs **Explorer**
  — I'll propose the full mapping at the start of Phase 5 for your sign-off.
