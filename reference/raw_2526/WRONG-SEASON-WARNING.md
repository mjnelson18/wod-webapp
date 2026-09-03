# Two files in this folder are NOT 2025/26

This snapshot was taken in **late July 2026**. By then some FPL endpoints had already rolled over
to 2026/27 while others had not, so the folder contains a mix of two seasons and nothing in the
payloads says which is which.

## Do not trust these

| file | what it actually is |
|---|---|
| `fixtures.json` | **2026/27 fixtures.** 380 of them, kickoffs in August 2026, none finished. |
| `bootstrap_static_fantasy.json` | Genuine 2025/26 player totals, but a **2026/27 `teams[]` list** — COV, HUL and IPS are present; BUR, WHU and WOL, who actually played in 2025/26, are missing. |

Because the `teams[]` list is next season's, the element→club mapping derived from this file puts
2025/26 players at the clubs they joined *afterwards*.

## These are fine

- `event/*` — the per-gameweek live payloads. Recorded points, correct season.
- `bootstrap_static_draft.json` — 2025/26 elements, positions and `draft_rank`.
- `league/*`, `entry/*`, `game.json` — league and entry state as at the snapshot.

## Where to get the real thing

The pipeline resolved all of it correctly at the time, so its own output for the season is the
source of truth:

```
data/wod/2526/fixtures.json   real schedule, scores, venues, difficulty (per team per gameweek)
data/wod/2526/teams.json      the 20 clubs that actually played, with ids
data/wod/2526/players.json    element -> club, for that season
```

`seasonTruth()` in `draft/lib/season/oracle-ctx.mjs` builds a proper FPL-shaped fixture list from
those three, and guards on kickoff year and on 380 fixtures / 20 clubs so the problem cannot
silently return.

## Why this went unnoticed for so long

The clubs and their ids looked plausible, so every lookup returned *a* fixture for *a* club — never
an error, just the wrong opponent. And `check-autosubs.mjs`, the one hard regression test, reads
recorded points and never touches a fixture, so it reported 456/456 correct throughout.

Measured against the real 2025/26 schedule, what was being used matched:

- the true **opponent** 2.2% of the time (chance alone would be about 5%)
- the true **venue** 47.8% — a coin flip
- the true **difficulty** 33.2%

Every fixture-derived term in the 2025/26 replay was therefore noise, and two conclusions drawn
from it were wrong in ways that mattered: that fixture difficulty was worth almost nothing (the
real per-position slopes are 4–7× larger and clearly separated), and that the lineup model was at
parity with the drafters (it is about +18 points a season). See the fixture-bug section of
`draft/README.md`.

**When taking any future snapshot, assert the kickoff years and the club list against the season it
claims to be.** A rollover does not move every endpoint at once.
