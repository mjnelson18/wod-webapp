"""Archive generator for seasons whose raw data is gone: CSV -> canonical tables.

Used for 2425 only. The FPL API never serves a past season, and 2425 was never
snapshotted, so these CSVs are the sole record. **Logic cannot be validated for
2425** — there is no raw input to re-run against. Schema and plausibility checks
only (tests/test_archive_2425.py).

The 2425 CSVs are much sparser than 2526's: no ownership or rank in Player Points
Weekly, no fixtures, no difficulty, no cost, no draft round, no team names in the
weekly summary, a different transfers schema, and no trades file at all.

Anything genuinely derivable from what *is* present is derived (noted inline);
everything else is left null for the frontend's capability flags to hide.
"""

import numpy as np
import pandas as pd

from .. import paths
from ..transforms.league import form_table

STARTING_XI = 11
NOT_ORIGINALLY_DRAFTED = "Not Originally Drafted"
NOT_DRAFTED = "Not Drafted"


def _read(stem: str, season: str) -> pd.DataFrame | None:
    path = paths.historical_dir() / f"{stem}_{season}.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path, encoding="utf-8")
    return frame.loc[:, [c for c in frame.columns if not c.startswith("Unnamed")]]


def _renumber_picks(picks: pd.DataFrame, season) -> pd.DataFrame:
    """
    Renumber `index` per league and derive `round`.

    2425's Premiership `index` runs 1..90 with only 75 rows, so that league also
    had an excluded entry (6 drafted, 5 real). Same treatment as 2526: sort by the
    raw index, renumber the survivors 1..N, then divide by the configured drafter
    count. The CSVs have no `round` column at all, so this is new information
    rather than a reproduction.
    """
    pieces = []
    for league_code, group in picks.groupby("league_code", sort=False):
        size = season.league(league_code).size
        group = group.sort_values("index", kind="stable").copy()
        group["index"] = range(1, len(group) + 1)
        group["round"] = ((group["index"] - 1) // size) + 1
        pieces.append(group)
    return pd.concat(pieces, ignore_index=True)


def build_tables(season, *, verbose: bool = True) -> dict:
    """Assemble canonical tables for a CSV-only season."""
    say = print if verbose else (lambda *a, **k: None)
    sid = season.season
    say(f"{sid}: building archive from reference/historical CSVs")

    teams = _read("Teams", sid)
    players = _read("All Players Summary", sid)
    summary = _read("Weekly Summary", sid)
    picks = _read("Draft Picks", sid)
    points = _read("Player Points Weekly", sid)
    transfers_csv = _read("Transfers", sid)
    trades_csv = _read(f"trade_history", sid)

    if summary is None or picks is None:
        raise FileNotFoundError(f"{sid}: missing Weekly Summary or Draft Picks CSV")

    # --- players / teams -------------------------------------------------
    for column in ("draft_rank", "now_cost", "selected_by_percent"):
        if column not in players.columns:
            players[column] = pd.NA
    if "team_name" not in players.columns and teams is not None:
        players = players.merge(teams, on="team", how="left")

    # --- draft picks -----------------------------------------------------
    picks = _renumber_picks(picks, season)
    picks["short_name"] = picks["short_name"].str.upper()
    lookup = players[["id", "team", "team_name"]].rename(columns={"id": "element"})
    picks = picks.merge(lookup, on="element", how="left")
    for column in ("draft_rank", "now_cost", "selected_by_percent", "first_name", "last_name"):
        if column not in picks.columns:
            picks[column] = pd.NA

    # --- weekly summary --------------------------------------------------
    summary["short_name"] = summary["short_name"].str.upper()

    # club names: 2425's weekly summary carries team_id but no team_name
    if "team_name" not in summary.columns:
        summary = summary.merge(
            players[["id", "team_name"]].rename(columns={"id": "element"}),
            on="element", how="left",
        )

    # who originally drafted each player, in this league
    drafted = picks[["league_code", "element", "short_name", "index"]].rename(
        columns={"short_name": "drafter_name", "index": "draft_index"}
    )
    summary = summary.merge(drafted, on=["league_code", "element"], how="left",
                            suffixes=("", "_drafted"))
    summary["drafter_name"] = summary["drafter_name"].fillna(NOT_ORIGINALLY_DRAFTED)

    # round for the drafter who actually holds them
    own = picks[["league_code", "short_name", "element", "round"]]
    summary = summary.merge(own, on=["league_code", "short_name", "element"], how="left")

    # a player's own season total
    if points is not None:
        totals = (points.groupby("id", as_index=False)["total_points"].sum()
                  .rename(columns={"total_points": "player_total_points", "id": "element"}))
        summary = summary.merge(totals, on="element", how="left")
    else:
        summary["player_total_points"] = pd.NA

    summary = summary.sort_values(["league_code", "short_name", "element", "gameweek"])
    summary["points_scored_cumulative"] = (
        summary.groupby(["league_code", "short_name", "element"])["points_scored"].cumsum()
    )

    # optimal_weight was never stored for 2425 and cannot be recovered without the
    # raw squads; optimal_points itself is present in the CSV.
    if "optimal_weight" not in summary.columns:
        summary["optimal_weight"] = pd.NA
    for column in ("gameweek_matches", "opposition", "home_away", "team_score",
                   "opposition_score", "team_difficulty", "opposition_difficulty",
                   "kickoff_time_first", "team"):
        if column not in summary.columns:
            summary[column] = pd.NA
    if "id" not in summary.columns:
        summary["id"] = summary["element"]
    for column in ("index", "round", "player_total_points"):
        summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0).astype(int)
    summary["in_original_draft"] = np.where(summary["index"] > 0, 1, 0)

    # --- weekly points ---------------------------------------------------
    # The 2425 CSV holds only id/total_points/gameweek. Ownership and in-week rank
    # ARE derivable — rank from the points themselves, owner from the weekly
    # summary — so the table is rebuilt per league rather than left unusable.
    if points is not None:
        frames = []
        for league in season.leagues:
            frame = points[["id", "total_points", "gameweek"]].copy()
            frame["league_code"] = league.code
            frames.append(frame)
        weekly_points = pd.concat(frames, ignore_index=True)
        weekly_points = weekly_points.sort_values(["gameweek", "total_points"],
                                                  ascending=[True, False])
        weekly_points["rank_in_week"] = (
            weekly_points.groupby(["league_code", "gameweek"])["total_points"]
            .rank(method="min", ascending=False).astype(int)
        )
        owners = summary[["league_code", "gameweek", "element", "short_name", "place"]].rename(
            columns={"element": "id"}
        )
        weekly_points = weekly_points.merge(owners, on=["league_code", "gameweek", "id"], how="left")
        weekly_points["short_name"] = weekly_points["short_name"].fillna(NOT_DRAFTED)
        weekly_points["isBenched"] = np.where(weekly_points["place"] > STARTING_XI, 1, 0)
        weekly_points["short_name"] = np.where(
            weekly_points["isBenched"] == 1,
            weekly_points["short_name"] + " (Benched)", weekly_points["short_name"],
        )
        details = players[["id", "web_name", "position", "team", "team_name"]].rename(
            columns={"team": "team_id"}
        )
        weekly_points = weekly_points.merge(details, on="id", how="left")
        weekly_points = weekly_points.merge(drafted.rename(columns={"element": "id"}),
                                            on=["league_code", "id"], how="left")
        weekly_points["drafter_name"] = weekly_points["drafter_name"].fillna(NOT_ORIGINALLY_DRAFTED)
        for column in ("opposition", "home_away", "team_difficulty"):
            weekly_points[column] = pd.NA
    else:
        weekly_points = pd.DataFrame(columns=["id", "total_points", "gameweek", "league_code"])

    # --- transfers -------------------------------------------------------
    # 2425's schema differs: `person` not `short_name`, no league_code, and player
    # names only (no element ids, so element_in/out stay null).
    if transfers_csv is not None:
        transfers = transfers_csv.rename(columns={
            "person": "short_name", "event": "gameweek",
            "added": "date_added", "net_points_of_trade_in_week": "net_points_of_transfer_in_week",
        }).copy()
        transfers["short_name"] = transfers["short_name"].str.upper()
        league_of = (summary[["short_name", "league_code"]].drop_duplicates()
                     .set_index("short_name")["league_code"])
        transfers["league_code"] = transfers["short_name"].map(league_of)
        for column in ("element_in", "element_out", "priority"):
            if column not in transfers.columns:
                transfers[column] = pd.NA
        if "net_points_of_transfer_in_week" not in transfers.columns:
            transfers["net_points_of_transfer_in_week"] = pd.NA
        transfers["abs_net_trade"] = pd.to_numeric(
            transfers["net_points_of_transfer_in_week"], errors="coerce").abs()
        transfers["transfer_category"] = (
            transfers["kind"].astype(str) + " - " + transfers["result"].astype(str)
        )
        transfers["date_added"] = pd.to_datetime(transfers["date_added"], errors="coerce", utc=True)
    else:
        transfers = pd.DataFrame()

    trades = trades_csv if trades_csv is not None else pd.DataFrame(
        columns=["league_code", "gameweek", "offered_by", "received_by",
                 "element_in", "element_out", "state"]
    )

    # --- league table ----------------------------------------------------
    current_week = int(summary["gameweek"].max())
    totals = summary.groupby(["league_code", "short_name"], as_index=False)["points_scored"].sum()
    totals = totals.rename(columns={"points_scored": "total"})
    by_week = summary.groupby(["league_code", "short_name", "gameweek"],
                              as_index=False)["points_scored"].sum()
    by_week["cumulative_points"] = (
        by_week.groupby(["league_code", "short_name"])["points_scored"].cumsum()
    )
    by_week["gameweek_rank"] = (
        by_week.groupby(["league_code", "gameweek"])["cumulative_points"]
        .rank(method="min", ascending=False).astype(int)
    )
    table = totals.copy()
    table["rank"] = table.groupby("league_code")["total"].rank(
        method="min", ascending=False).astype(int)
    current = by_week[by_week["gameweek"] == current_week][
        ["league_code", "short_name", "points_scored", "gameweek_rank"]
    ].rename(columns={"points_scored": "gameweek_points"})
    table = table.merge(current, on=["league_code", "short_name"], how="left")
    previous = by_week[by_week["gameweek"] == max(1, current_week - 1)][
        ["league_code", "short_name", "gameweek_rank"]
    ].rename(columns={"gameweek_rank": "last_rank"})
    table = table.merge(previous, on=["league_code", "short_name"], how="left")
    table = table.merge(form_table(summary, current_week),
                        on=["league_code", "short_name"], how="left")
    table["name"] = table["short_name"]
    table["entry_name"] = pd.NA

    say(f"  {len(summary)} summary rows, {len(weekly_points)} point rows, "
        f"{len(picks)} picks, {len(transfers)} transfers")

    return {
        "season": season,
        "current_week": current_week,
        "hosts_agree": False,
        "teams": teams if teams is not None else pd.DataFrame(columns=["team", "team_name"]),
        "players": players,
        "draft_picks": picks,
        "weekly_summary": summary,
        "weekly_points": weekly_points,
        "transfers": transfers,
        "trades": trades,
        "standings": table,
        "league_table": table,
        "league_table_by_week": by_week,
        "fixtures_by_team": pd.DataFrame(),
    }
