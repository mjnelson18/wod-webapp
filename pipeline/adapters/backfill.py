"""CSV backfill for columns the FPL API can no longer supply.

Only ever used for archived seasons whose API window has closed. A live season
gets everything from the API and never touches this.

For 2526 (docs/notebook-recon.md 6.1 and 6.1b):

* `now_cost`, `selected_by_percent` — fantasy.premierleague.com had already
  rolled to 2627, and element ids are reassigned each season, so the merge the
  notebook did would join 2526 players onto 2627 ids.
* `team`, `team_name`, `web_name` — the snapshot's draft bootstrap carries 2526
  `teams` and 2526 stats but **2627** `elements[].team` ids and some 2627
  `web_name`s. Left uncorrected this silently mislabels 39% of players' clubs,
  and then cascades: club feeds the fixture join, so `opposition`, `home_away`
  and both scores come out wrong too.
* `team_difficulty`, `opposition_difficulty` — only the fantasy fixtures endpoint
  ever exposed these.

Everything backfilled here is listed in the Phase 2 diff report as CSV-sourced
rather than reproduced from raw, because it cannot be re-derived.
"""

import pandas as pd

from .. import paths

PLAYER_COLUMNS = ("team", "team_name", "web_name", "now_cost", "selected_by_percent")
DIFFICULTY_COLUMNS = ("team_difficulty", "opposition_difficulty")


def _read(stem: str, season: str) -> pd.DataFrame | None:
    path = paths.historical_dir() / f"{stem}_{season}.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path, encoding="utf-8")
    return frame.loc[:, [c for c in frame.columns if not c.startswith("Unnamed")]]


def backfill_players(players: pd.DataFrame, season, *, columns=None) -> pd.DataFrame:
    """Override player columns from All Players Summary_<season>.csv, matched on element id."""
    wanted = tuple(c for c in (columns or season.csv_backfill) if c in PLAYER_COLUMNS)
    if not wanted:
        return players
    csv = _read("All Players Summary", season.season)
    if csv is None:
        return players

    available = [c for c in wanted if c in csv.columns]
    if not available:
        return players

    source = csv[["id"] + available].copy()
    source["id"] = pd.to_numeric(source["id"])
    out = players.copy()
    out = out.merge(source, on="id", how="left", suffixes=("", "__csv"))
    for column in available:
        csv_column = f"{column}__csv"
        if csv_column in out.columns:
            # keep the API value only where the CSV has nothing
            out[column] = out[csv_column].where(out[csv_column].notna(), out[column])
            out = out.drop(columns=[csv_column])
    return out


def backfill_difficulty(fixtures_by_team: pd.DataFrame, season) -> pd.DataFrame:
    """
    Fill fixture difficulty from Weekly Summary_<season>.csv.

    Difficulty is a per (gameweek, team) property, so it is recovered by taking the
    first occurrence of each pair in the CSV.
    """
    wanted = [c for c in DIFFICULTY_COLUMNS if c in season.csv_backfill]
    if not wanted or fixtures_by_team is None or fixtures_by_team.empty:
        return fixtures_by_team

    # Prefer Player Points Weekly: it covers every element, so every club appears
    # every gameweek. Weekly Summary only covers clubs someone actually owned that
    # week, which leaves gaps for the unowned-player rows.
    csv = None
    for stem in ("Player Points Weekly", "Weekly Summary"):
        candidate = _read(stem, season.season)
        if candidate is not None and all(c in candidate.columns for c in wanted + ["gameweek", "team"]):
            csv = candidate
            break
    if csv is None:
        return fixtures_by_team

    lookup = (
        csv[["gameweek", "team"] + wanted]
        .dropna(subset=["team"])
        .drop_duplicates(subset=["gameweek", "team"])
    )
    lookup["gameweek"] = pd.to_numeric(lookup["gameweek"])

    out = fixtures_by_team.copy()
    out = out.merge(lookup, on=["gameweek", "team"], how="left", suffixes=("", "__csv"))
    for column in wanted:
        csv_column = f"{column}__csv"
        if csv_column in out.columns:
            out[column] = out[csv_column].where(out[csv_column].notna(), out[column])
            out = out.drop(columns=[csv_column])
    return out
