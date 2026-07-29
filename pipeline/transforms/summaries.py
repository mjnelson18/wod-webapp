"""Per-view summary tables. Ported from notebook cells 33-38 and 42. Pure.

These are the tables the old report showed but the pipeline wasn't yet emitting.
Pre-computed here rather than in the browser so the mobile client doesn't
aggregate 6,840-row tables to draw a chart (CLAUDE.md).
"""

import numpy as np
import pandas as pd

STARTING_XI = 11
FORM_GAMES = 6
AVAILABLE_PER_POSITION = 5
LOOKAHEAD_GAMEWEEKS = 6

# Order matters: it's the flow of the old report's Points Summary table, from
# what you drafted through to what you actually banked.
SUMMARY_METRICS = [
    "draft_points",
    "points_gained_through_waivers",
    "squad_points",
    "bench_strength",
    "optimal_points",
    "points_lost_choosing_starting_XI",
    "points_before_auto_subs",
    "points_gained_with_auto_subs",
    "net_points_lost_through_subs",
    "points_scored",
]


def _derive_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """The five differences the old report built its Points Summary from."""
    frame = frame.copy()
    frame["points_gained_through_waivers"] = frame["squad_points"] - frame["draft_points"]
    frame["bench_strength"] = frame["optimal_points"] - frame["squad_points"]
    frame["points_lost_choosing_starting_XI"] = (
        frame["points_before_auto_subs"] - frame["optimal_points"]
    )
    frame["points_gained_with_auto_subs"] = (
        frame["points_scored"] - frame["points_before_auto_subs"]
    )
    frame["net_points_lost_through_subs"] = frame["points_scored"] - frame["optimal_points"]
    return frame


def season_summary(weekly_summary: pd.DataFrame, weekly_points: pd.DataFrame) -> pd.DataFrame:
    """
    One row per drafter, plus a league-average row. Ported from cell 35.

    `draft_points` is every point scored by players this drafter originally
    drafted, wherever those players ended up — which is why it comes from
    weekly_points keyed on drafter_name, not from the drafter's own squad.
    """
    drafted = (
        weekly_points.groupby(["league_code", "drafter_name"], as_index=False)["total_points"]
        .sum().rename(columns={"drafter_name": "short_name", "total_points": "draft_points"})
    )
    owned = (
        weekly_summary.groupby(["league_code", "short_name"], as_index=False)[
            ["total_points", "optimal_points", "points_before_auto_subs", "points_scored"]
        ].sum().rename(columns={"total_points": "squad_points"})
    )
    summary = _derive_summary(owned.merge(drafted, on=["league_code", "short_name"], how="left"))
    summary = summary[["league_code", "short_name"] + SUMMARY_METRICS]

    averages = summary.groupby("league_code", as_index=False)[SUMMARY_METRICS].mean()
    averages["short_name"] = averages["league_code"] + "_Avg"
    averages["is_average"] = True
    summary["is_average"] = False

    out = pd.concat([summary, averages[summary.columns]], ignore_index=True)
    for column in SUMMARY_METRICS:
        out[column] = pd.to_numeric(out[column]).round(1)
    return out.sort_values(["league_code", "is_average", "points_scored"],
                           ascending=[True, True, False])


def season_summary_by_gameweek(weekly_summary: pd.DataFrame,
                               weekly_points: pd.DataFrame) -> pd.DataFrame:
    """
    The same metrics per gameweek, so any summary column can be charted over time.

    Cumulative, matching how the summary table reads at a point in the season.
    """
    drafted = (
        weekly_points.groupby(["league_code", "drafter_name", "gameweek"], as_index=False)
        ["total_points"].sum()
        .rename(columns={"drafter_name": "short_name", "total_points": "draft_points"})
    )
    owned = (
        weekly_summary.groupby(["league_code", "short_name", "gameweek"], as_index=False)[
            ["total_points", "optimal_points", "points_before_auto_subs", "points_scored"]
        ].sum().rename(columns={"total_points": "squad_points"})
    )
    weekly = owned.merge(drafted, on=["league_code", "short_name", "gameweek"], how="left")
    weekly["draft_points"] = weekly["draft_points"].fillna(0)

    weekly = weekly.sort_values(["league_code", "short_name", "gameweek"])
    keys = ["league_code", "short_name"]
    for column in ("squad_points", "optimal_points", "points_before_auto_subs",
                   "points_scored", "draft_points"):
        weekly[column] = weekly.groupby(keys)[column].cumsum()

    weekly = _derive_summary(weekly)
    columns = keys + ["gameweek"] + SUMMARY_METRICS
    return weekly[columns].round(1)


def formations(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """
    How often each drafter started each DEF-MID-FWD shape, vs their mean optimal
    shape. Ported from cell 36. The keeper is excluded — there is always exactly one.
    """
    outfield = weekly_summary[weekly_summary["position"] != "GKP"]

    chosen = (
        outfield.groupby(["league_code", "short_name", "gameweek", "position"], as_index=False)
        ["originally_starting"].sum()
        .pivot_table(index=["league_code", "short_name", "gameweek"], columns="position",
                     values="originally_starting", fill_value=0)
        .reset_index()
    )
    for position in ("DEF", "MID", "FWD"):
        if position not in chosen.columns:
            chosen[position] = 0
    chosen["formation"] = (
        chosen["DEF"].astype(int).astype(str) + "-"
        + chosen["MID"].astype(int).astype(str) + "-"
        + chosen["FWD"].astype(int).astype(str)
    )
    counts = (
        chosen.groupby(["league_code", "short_name", "formation"], as_index=False)
        .size().rename(columns={"size": "count"})
    )

    # No usable weights means no meaningful optimal shape — say so with null
    # rather than reporting a confident 0.0-0.0-0.0.
    if "optimal_weight" not in outfield.columns or not outfield["optimal_weight"].notna().any():
        counts = (
            chosen.groupby(["league_code", "short_name", "formation"], as_index=False)
            .size().rename(columns={"size": "count"})
        )
        return counts.assign(optimal_formation=None)

    optimal = (
        outfield.groupby(["league_code", "short_name", "gameweek", "position"], as_index=False)
        ["optimal_weight"].sum()
        .groupby(["league_code", "short_name", "position"], as_index=False)["optimal_weight"].mean()
        .pivot_table(index=["league_code", "short_name"], columns="position",
                     values="optimal_weight", fill_value=0)
        .reset_index()
    )
    for position in ("DEF", "MID", "FWD"):
        if position not in optimal.columns:
            optimal[position] = 0.0
    optimal["optimal_formation"] = (
        optimal["DEF"].round(1).astype(str) + "-"
        + optimal["MID"].round(1).astype(str) + "-"
        + optimal["FWD"].round(1).astype(str)
    )

    return counts.merge(optimal[["league_code", "short_name", "optimal_formation"]],
                        on=["league_code", "short_name"], how="left")


def draft_pick_performance(weekly_summary: pd.DataFrame, weekly_points: pd.DataFrame,
                           current_week: int) -> pd.DataFrame:
    """
    Per draft pick: who actually banked the points. Ported from cell 33.

    `points_realised_by_drafter` is what the pick returned to the person who made
    it; `by_other` went to whoever held them later; `unrealised` went to nobody,
    scored while benched or unowned. The three sum to the player's season total.
    """
    by_drafter = (
        weekly_summary.groupby(["league_code", "short_name", "id"], as_index=False)
        ["points_scored"].sum().rename(columns={"points_scored": "points_realised_by_drafter"})
    )
    by_anyone = (
        weekly_summary.groupby(["league_code", "id"], as_index=False)["points_scored"]
        .sum().rename(columns={"points_scored": "points_realised_total"})
    )

    picks = weekly_points[weekly_points["draft_index"].notna()]
    picks = (
        picks.groupby(["league_code", "drafter_name", "web_name", "position",
                       "draft_index", "id"], as_index=False)["total_points"].sum()
    )

    frame = picks.merge(
        by_drafter, left_on=["league_code", "drafter_name", "id"],
        right_on=["league_code", "short_name", "id"], how="left",
    ).merge(by_anyone, on=["league_code", "id"], how="left")

    frame["points_realised_by_drafter"] = frame["points_realised_by_drafter"].fillna(0)
    frame["points_realised_total"] = frame["points_realised_total"].fillna(0)
    # keep the stack within the player's actual total
    frame["points_realised_total"] = np.minimum(frame["points_realised_total"],
                                                frame["total_points"])
    frame["points_realised_by_drafter"] = np.minimum(frame["points_realised_by_drafter"],
                                                     frame["points_realised_total"])
    frame["points_realised_by_other"] = (
        frame["points_realised_total"] - frame["points_realised_by_drafter"]
    ).clip(lower=0)
    frame["points_unrealised"] = (
        frame["total_points"] - frame["points_realised_total"]
    ).clip(lower=0)

    current = (
        weekly_summary.loc[weekly_summary["gameweek"] == current_week,
                           ["league_code", "short_name", "id"]]
        .dropna().drop_duplicates(subset=["league_code", "id"], keep="first")
        .rename(columns={"short_name": "current_owner"})
    )
    frame = frame.merge(current, on=["league_code", "id"], how="left")
    frame["still_owned"] = frame["current_owner"].eq(frame["drafter_name"])

    return frame.drop(columns=["short_name"], errors="ignore").sort_values(
        ["league_code", "draft_index"]
    )


def _squad_player_points(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """
    Season points banked per (drafter, player), for every player they ever held.

    Includes non-scorers and players who never started — a squad slot that returned
    nothing is part of how concentrated the scoring was. Negative season totals are
    clipped to zero: a Lorenz curve is undefined over negative values, and only a
    handful of players ever finish a season net-negative for one drafter.
    """
    frame = (
        weekly_summary.groupby(["league_code", "short_name", "element", "web_name"],
                               as_index=False)["points_scored"].sum()
    )
    frame["points_scored"] = frame["points_scored"].clip(lower=0)
    return frame


def player_usage(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """
    Squad churn and scoring concentration per drafter.

    `gini` measures how unevenly banked points were spread across **every** player
    the drafter held, non-scorers and never-started included: 0 would be all squad
    members contributing equally, closer to 1 means a few players carried the team.
    Computed on `points_scored`, so it reflects points actually banked rather than
    squad potential.
    """
    used = (
        weekly_summary.groupby(["league_code", "short_name"], as_index=False)["element"]
        .nunique().rename(columns={"element": "unique_players_used"})
    )
    started = (
        weekly_summary[weekly_summary["place"] <= STARTING_XI]
        .groupby(["league_code", "short_name"], as_index=False)["element"]
        .nunique().rename(columns={"element": "unique_players_started"})
    )
    frame = used.merge(started, on=["league_code", "short_name"], how="left")

    per_player = _squad_player_points(weekly_summary)

    rows = []
    for (league, short), group in per_player.groupby(["league_code", "short_name"]):
        squad = group.sort_values("points_scored")
        best = group.loc[group["points_scored"].idxmax()] if len(group) else None
        total = float(group["points_scored"].sum())
        rows.append({
            "league_code": league,
            "short_name": short,
            # across the whole squad, not just those who scored
            "gini": _gini(squad["points_scored"].to_numpy(dtype=float)),
            "scoring_players": int((group["points_scored"] > 0).sum()),
            "top_player": None if best is None else best["web_name"],
            "top_player_points": 0 if best is None else int(best["points_scored"]),
            "top_player_pct": 0.0 if not total or best is None
                              else round(float(best["points_scored"]) / total, 4),
        })
    return frame.merge(pd.DataFrame(rows), on=["league_code", "short_name"], how="left")


def lorenz_curve(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """
    Concentration curve per drafter: how much of their scoring came from how much of
    their squad.

    Players are ordered **best first**, so the curve rises steeply through the few
    players who carried the team and then plateaus across the squad members who
    contributed little. A straight diagonal would mean every squad member
    contributed equally; the further the curve bows above it, the more concentrated
    the scoring.

    Long-form so the frontend can plot either axis. `player_index` counts players
    (1..n), `players_pct` is that as a share of the squad, and `points_pct` is the
    cumulative share of banked points.
    """
    per_player = _squad_player_points(weekly_summary)
    rows = []
    for (league, short), group in per_player.groupby(["league_code", "short_name"]):
        squad = group.sort_values("points_scored", ascending=False).reset_index(drop=True)
        total = float(squad["points_scored"].sum())
        n = len(squad)
        if not n:
            continue
        running = 0.0
        # origin, so the curve starts at (0, 0) rather than the first player
        rows.append({"league_code": league, "short_name": short, "player_index": 0,
                     "players_pct": 0.0, "points_pct": 0.0, "points_cumulative": 0,
                     "players_total": n, "web_name": None})
        for i, record in squad.iterrows():
            running += float(record["points_scored"])
            rows.append({
                "league_code": league,
                "short_name": short,
                "player_index": i + 1,
                "players_pct": round((i + 1) / n, 4),
                "points_pct": 0.0 if total <= 0 else round(running / total, 4),
                "points_cumulative": int(running),
                "players_total": n,
                "web_name": record["web_name"],
            })
    return pd.DataFrame(rows)


def _gini(values: np.ndarray) -> float:
    """
    Gini coefficient of a non-negative, ascending-sorted array.

    0 = perfectly even, approaching 1 = all of it concentrated in one place.
    Returns 0.0 for an empty or all-zero input rather than dividing by zero.
    """
    if values.size == 0:
        return 0.0
    total = values.sum()
    if total <= 0:
        return 0.0
    n = values.size
    index = np.arange(1, n + 1)
    return round(float((2 * index - n - 1).dot(values) / (n * total)), 4)


def points_distribution(weekly_summary: pd.DataFrame, cut: str) -> pd.DataFrame:
    """
    Share and average of a drafter's points broken down by `cut` — 'position' or
    'team_name'. Ported from cell 31, which only produced the percentage.
    """
    grouped = (
        weekly_summary.groupby(["league_code", "short_name", cut], as_index=False)
        .agg(points_scored=("points_scored", "sum"),
             appearances=("points_scored", "size"))
    )
    totals = grouped.groupby(["league_code", "short_name"], as_index=False)["points_scored"].sum()
    totals = totals.rename(columns={"points_scored": "total_points"})
    grouped = grouped.merge(totals, on=["league_code", "short_name"], how="left")
    grouped["pct_points"] = (grouped["points_scored"] / grouped["total_points"]).round(4)
    grouped["avg_points"] = (grouped["points_scored"] / grouped["appearances"]).round(2)
    return grouped.rename(columns={cut: "bucket"}).assign(cut=cut)


def draft_share(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """What share of a drafter's banked points came from their original picks."""
    frame = weekly_summary.copy()
    frame["draft_points"] = np.where(frame["in_original_draft"] == 1, frame["points_scored"], 0)
    out = frame.groupby(["league_code", "short_name"], as_index=False).agg(
        points_scored=("points_scored", "sum"), draft_points=("draft_points", "sum"),
    )
    out["pct_from_draft"] = (out["draft_points"] / out["points_scored"]).round(4)
    return out


def draft_share_by_gameweek(weekly_summary: pd.DataFrame) -> pd.DataFrame:
    """
    The same share, cumulative per gameweek — how reliance on the original draft
    decayed as squads churned through waivers and trades.
    """
    frame = weekly_summary.copy()
    frame["draft_points"] = np.where(frame["in_original_draft"] == 1, frame["points_scored"], 0)
    weekly = frame.groupby(["league_code", "short_name", "gameweek"], as_index=False).agg(
        points_scored=("points_scored", "sum"), draft_points=("draft_points", "sum"),
    ).sort_values(["league_code", "short_name", "gameweek"])

    keys = ["league_code", "short_name"]
    for column in ("points_scored", "draft_points"):
        weekly[column] = weekly.groupby(keys)[column].cumsum()
    weekly["pct_from_draft"] = (
        weekly["draft_points"] / weekly["points_scored"].replace(0, np.nan)
    ).round(4)
    return weekly


def available_form_players(weekly_points: pd.DataFrame, current_week: int,
                           form_games: int = FORM_GAMES,
                           per_position: int = AVAILABLE_PER_POSITION) -> pd.DataFrame:
    """
    Best undrafted players by recent form. Ported from cell 42, which computed this
    and never rendered it.
    """
    window = weekly_points[weekly_points["gameweek"] >= current_week - form_games + 1]
    form = (
        window.groupby(["league_code", "id", "web_name", "position", "team_name"], as_index=False)
        ["total_points"].mean().rename(columns={"total_points": "form_points"})
    )
    free = weekly_points[
        (weekly_points["gameweek"] == current_week)
        & (weekly_points["short_name"].astype(str).str.startswith("Not Drafted"))
    ][["league_code", "id"]].drop_duplicates()

    frame = form.merge(free, on=["league_code", "id"], how="inner")
    frame["form_points"] = frame["form_points"].round(2)
    frame["rank"] = (
        frame.groupby(["league_code", "position"])["form_points"]
        .rank(ascending=False, method="min").astype(int)
    )
    return frame[frame["rank"] <= per_position].sort_values(
        ["league_code", "position", "rank"]
    )


def fixture_lookahead(fixtures_by_team: pd.DataFrame, from_gameweek: int,
                      count: int = LOOKAHEAD_GAMEWEEKS) -> pd.DataFrame:
    """
    The next `count` gameweeks of fixtures per team, with difficulty.

    Anchored on a gameweek rather than "now", so it works for an archived season:
    viewing GW20 of a finished season shows what GW21-26 looked like from there.
    """
    if fixtures_by_team is None or fixtures_by_team.empty:
        return pd.DataFrame()
    upcoming = fixtures_by_team[
        (fixtures_by_team["gameweek"] > from_gameweek)
        & (fixtures_by_team["gameweek"] <= from_gameweek + count)
    ].copy()
    upcoming["gameweeks_ahead"] = upcoming["gameweek"] - from_gameweek
    return upcoming.sort_values(["team", "gameweek"])
