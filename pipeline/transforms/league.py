"""League standings and drafter identity. Ported from notebook cells 3, 4, 15, 16. Pure."""

import pandas as pd

STANDINGS_COLUMNS = [
    "id", "entry_id", "entry_name", "short_name", "first_name", "last_name",
    "total", "gameweek_points", "rank", "last_rank",
]


def league_table(details: dict, *, league_code, exclude_entries=()) -> pd.DataFrame:
    """
    One row per drafter, from the league details payload.

    Entries in `exclude_entries` are dropped. In 2526 that is league_entry 92234,
    the organiser's Premiership team, which drafted deliberate dud picks. Dropping
    it here is right for standings, draft and summary tables — and wrong for
    trades, which keeps every entry.
    """
    mapping = pd.json_normalize(details["league_entries"])[[
        "entry_id", "entry_name", "id", "short_name",
        "player_first_name", "player_last_name",
    ]].copy()
    mapping["short_name"] = mapping["short_name"].str.upper()
    mapping["player_first_name"] = mapping["player_first_name"].str.capitalize()
    mapping["player_last_name"] = mapping["player_last_name"].str.capitalize()
    mapping = mapping.rename(columns={
        "player_first_name": "first_name", "player_last_name": "last_name",
    })

    if exclude_entries:
        mapping = mapping[~mapping["id"].isin(list(exclude_entries))]

    # Between a league being created and GW1 opening, the API serves an empty
    # standings list: the drafters exist but have no position yet. json_normalize
    # leaves no columns behind for an empty list, so selecting them raises — take
    # the drafters at zero instead, which is what the league actually looks like.
    if not (details.get("standings") or []):
        blank = mapping.assign(gameweek_points=0, total=0, rank=0, last_rank=0,
                               league_code=league_code)
        return blank[STANDINGS_COLUMNS + ["league_code"]]

    standings = pd.json_normalize(details["standings"])[[
        "league_entry", "event_total", "total", "rank", "last_rank",
    ]]
    standings = standings.merge(mapping, left_on="league_entry", right_on="id", how="inner")
    standings = standings.rename(columns={"event_total": "gameweek_points"})
    standings["league_code"] = league_code
    return standings[STANDINGS_COLUMNS + ["league_code"]]


def entry_ids(details: dict, *, exclude_entries=()) -> dict[int, str]:
    """entry_id -> upper-case short name, for the per-entry picks fetch."""
    out = {}
    for entry in details["league_entries"]:
        if entry["id"] in set(exclude_entries):
            continue
        if entry.get("entry_id"):
            out[int(entry["entry_id"])] = entry["short_name"].upper()
    return out


def live_league_table(weekly_summary: pd.DataFrame, standings: pd.DataFrame,
                      current_week: int) -> pd.DataFrame:
    """
    Rebuild the table from banked points rather than trusting the API standings.

    Ranks use method='min' so ties share the higher rank, and
    `previous_gameweek_rank` is the prior week's rank (0 in GW1).
    """
    by_week = (
        weekly_summary.groupby(["league_code", "short_name", "gameweek"], as_index=False)
        .agg({"points_scored": "sum"})
    )
    by_week["cumulative_points"] = (
        by_week.groupby(["league_code", "short_name"])["points_scored"].cumsum()
    )
    by_week["gameweek_rank"] = (
        by_week.groupby(["league_code", "gameweek"])["cumulative_points"]
        .rank(method="min", ascending=False).astype(int)
    )
    by_week["previous_gameweek_rank"] = (
        by_week.groupby(["league_code", "short_name"])["gameweek_rank"]
        .shift(1).fillna(0).astype(int)
    )

    current = by_week[by_week["gameweek"] == current_week]
    table = standings.merge(current, on=["league_code", "short_name"], how="left",
                            suffixes=("", "_live"))
    table["total"] = table["cumulative_points"]
    table["gameweek_points"] = table["points_scored"]
    table["rank"] = table["gameweek_rank"]
    table["last_rank"] = table["previous_gameweek_rank"]
    table["name"] = table["first_name"] + " " + table["last_name"]
    return table, by_week


def form_table(weekly_summary: pd.DataFrame, current_week: int,
               form_games: int = 5) -> pd.DataFrame:
    """Mean banked points over the last `form_games` gameweeks, ranked densely."""
    window = weekly_summary[
        (weekly_summary["gameweek"] <= current_week)
        & (weekly_summary["gameweek"] > current_week - form_games)
    ]
    form = window.groupby(["league_code", "short_name"], as_index=False)["points_scored"].sum()
    divisor = form_games if current_week >= form_games else current_week
    form["points_scored"] = form["points_scored"] / divisor
    form["form_rank"] = (
        form.groupby("league_code")["points_scored"]
        .rank(ascending=False, method="dense").astype(int)
    )
    return form.rename(columns={"points_scored": "form_points"})


def league_gaps(table: pd.DataFrame, league) -> pd.DataFrame:
    """
    Promotion/relegation gap metrics, driven by config rather than hardcoded ranks.

    The notebook pinned these to ranks 4/5/6 for the Premiership and rank 2 for the
    Conference, which breaks 2425's 5/7 split with 3 up / 1 down.
    """
    rows = table[table["league_code"] == league.code].sort_values("rank").copy()
    if rows.empty:
        return rows

    totals = rows.set_index("rank")["total"]
    best = rows["total"].max()
    rows["points_from_top"] = best - rows["total"]

    if league.relegated:
        safe_rank = league.size - league.relegated          # last safe position
        drop_rank = safe_rank + 1                            # first relegated position
        if safe_rank in totals.index:
            rows["points_from_safety"] = totals[safe_rank] - rows["total"]
        if drop_rank in totals.index:
            rows["points_above_relegation"] = rows["total"] - totals[drop_rank]

    if league.promoted:
        last_promoted = league.promoted
        if last_promoted in totals.index:
            rows["points_from_promotion"] = totals[last_promoted] - rows["total"]
        # last place forfeits — the chicken suit
        rows["points_above_last"] = rows["total"] - rows["total"].min()

    return rows
