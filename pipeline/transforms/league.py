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

    # Two standings shapes, because FPL runs two kinds of draft league.
    #
    #   classic ('c')          event_total, total          — points banked
    #   head-to-head ('h')     matches_won/drawn/lost,     — a fixture table;
    #                          points_for, points_against,   `total` is league
    #                          total                          points, not FPL ones
    #
    # Only the columns common to both are taken, and a head-to-head league's
    # `total` is not read as a points total: live_league_table recomputes every
    # figure here from the weekly rows anyway, so this frame is identity plus a
    # seed. What it does mean is that a head-to-head league is ranked on points
    # scored rather than on the fixtures it actually plays — an honest table, but
    # not that league's official one. See the README.
    frame = pd.json_normalize(details["standings"])
    standings = pd.DataFrame({
        "league_entry": frame["league_entry"],
        "gameweek_points": frame.get("event_total", 0),
        "total": frame.get("total", 0),
        "rank": frame.get("rank"),
        "last_rank": frame.get("last_rank"),
    })
    # Nulls until the first result is in, on either shape.
    for column in ("gameweek_points", "total", "rank", "last_rank"):
        standings[column] = pd.to_numeric(standings[column], errors="coerce").fillna(0).astype(int)

    standings = standings.merge(mapping, left_on="league_entry", right_on="id", how="inner")
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


# --- head-to-head leagues ---------------------------------------------------
# Some draft leagues are played as weekly fixtures rather than on points banked.
# FPL calls this `scoring: 'h'` and awards the usual 3 / 1 / 0. The league's own
# `standings` payload carries the resulting table, but only once a gameweek has
# finished: mid-gameweek every figure in it is last week's, and before the first
# result it is all zeroes with a null rank. So the table is rebuilt from
# `matches` — the same choice live_league_table makes for a classic league, and
# for the same reason.
#
# reconcile_head_to_head checks the rebuild against the API's own table as soon
# as there are finished matches to check against, so the 3/1/0 assumption cannot
# quietly be wrong.
H2H_WIN, H2H_DRAW, H2H_LOSS = 3, 1, 0

H2H_MATCH_COLUMNS = [
    "gameweek", "league_code", "home", "away", "home_points", "away_points",
    "started", "finished", "result", "winner",
]

H2H_TABLE_COLUMNS = [
    "league_code", "short_name", "played", "won", "drawn", "lost",
    "points_for", "points_against", "h2h_points", "rank", "last_rank",
    "provisional",
]


def is_head_to_head(details: dict) -> bool:
    """Does this league play weekly fixtures? Read from the API, never assumed."""
    return ((details.get("league") or {}).get("scoring")) == "h"


def head_to_head_matches(details: dict, standings: pd.DataFrame, *,
                         league_code) -> pd.DataFrame:
    """
    One row per fixture, home side first, named by drafter.

    The whole 38-gameweek fixture list is published up front, so this covers
    matches nobody has played yet; `started` says which are real.
    """
    rows = details.get("matches") or []
    if not rows:
        return pd.DataFrame(columns=H2H_MATCH_COLUMNS)

    names = dict(zip(standings["id"], standings["short_name"]))
    frame = pd.json_normalize(rows)
    out = pd.DataFrame({
        "gameweek": pd.to_numeric(frame["event"]).astype(int),
        "league_code": league_code,
        "home": frame["league_entry_1"].map(names),
        "away": frame["league_entry_2"].map(names),
        "home_points": pd.to_numeric(frame["league_entry_1_points"],
                                     errors="coerce").fillna(0).astype(int),
        "away_points": pd.to_numeric(frame["league_entry_2_points"],
                                     errors="coerce").fillna(0).astype(int),
        "started": frame["started"].fillna(False).astype(bool),
        "finished": frame["finished"].fillna(False).astype(bool),
    })
    # An excluded entry would leave its fixtures half-named. Drop them rather
    # than carry a match with one side into the table.
    out = out.dropna(subset=["home", "away"])

    margin = out["home_points"] - out["away_points"]
    out["result"] = margin.map(lambda m: "D" if m == 0 else ("W" if m > 0 else "L"))
    out.loc[~out["started"], "result"] = None
    out["winner"] = None
    out.loc[out["result"] == "W", "winner"] = out["home"]
    out.loc[out["result"] == "L", "winner"] = out["away"]
    return out[H2H_MATCH_COLUMNS].sort_values(["gameweek", "home"]).reset_index(drop=True)


def head_to_head_table(matches: pd.DataFrame, standings: pd.DataFrame, *,
                       league_code, current_week: int):
    """
    The league's own table, and the per-drafter per-gameweek rows behind it.

    Ranked on head-to-head points and then on points scored, which is how FPL
    separates two drafters on the same total. A gameweek that has started but not
    finished still counts: this site is near-live by design, and `provisional`
    marks the rows that depend on it so a view can say so rather than quietly
    disagreeing with the official table.
    """
    played = matches[matches["started"] & (matches["gameweek"] <= current_week)]

    # A match becomes two symmetrical rows, one per side, so everything below is
    # a plain group-by rather than two near-identical home and away branches.
    flipped = {"W": "L", "L": "W", "D": "D"}
    sides = []
    for side, other, scored, conceded in (("home", "away", "home_points", "away_points"),
                                          ("away", "home", "away_points", "home_points")):
        rows = pd.DataFrame({
            "league_code": league_code,
            "gameweek": played["gameweek"],
            "short_name": played[side],
            "opponent": played[other],
            "points_for": played[scored],
            "points_against": played[conceded],
            "finished": played["finished"],
            # `result` is written from the home side's point of view.
            "result": played["result"] if side == "home" else played["result"].map(flipped),
        })
        sides.append(rows)

    by_week = pd.concat(sides, ignore_index=True)
    if len(by_week):
        by_week["h2h_points"] = (by_week["result"]
                                 .map({"W": H2H_WIN, "D": H2H_DRAW, "L": H2H_LOSS})
                                 .fillna(0).astype(int))
        by_week = by_week.sort_values(["short_name", "gameweek"]).reset_index(drop=True)

    drafters = list(standings["short_name"])
    table = pd.DataFrame([_h2h_totals(by_week, name, league_code) for name in drafters])
    table["rank"] = _h2h_rank(table)
    table["last_rank"] = _h2h_rank_at(by_week, drafters, current_week - 1)
    return table[H2H_TABLE_COLUMNS], by_week


def _h2h_totals(by_week: pd.DataFrame, name: str, league_code) -> dict:
    mine = by_week[by_week["short_name"] == name] if len(by_week) else by_week
    counts = mine["result"].value_counts() if len(mine) else {}
    return {
        "league_code": league_code,
        "short_name": name,
        "played": int(len(mine)),
        "won": int(counts.get("W", 0)),
        "drawn": int(counts.get("D", 0)),
        "lost": int(counts.get("L", 0)),
        "points_for": int(mine["points_for"].sum()) if len(mine) else 0,
        "points_against": int(mine["points_against"].sum()) if len(mine) else 0,
        "h2h_points": int(mine["h2h_points"].sum()) if len(mine) else 0,
        "provisional": bool((~mine["finished"]).any()) if len(mine) else False,
    }


def _h2h_rank(table: pd.DataFrame) -> pd.Series:
    """Points, then points scored — FPL's own tie-break. Ties share the better rank."""
    order = list(zip(table["h2h_points"], table["points_for"]))
    return pd.Series([sum(1 for other in order if other > mine) + 1 for mine in order],
                     index=table.index, dtype=int)


def _h2h_rank_at(by_week: pd.DataFrame, drafters, gameweek: int) -> pd.Series:
    """Where the table stood after `gameweek`. Zero before a ball was kicked."""
    if gameweek < 1 or not len(by_week):
        return pd.Series([0] * len(drafters), dtype=int)
    upto = by_week[by_week["gameweek"] <= gameweek]
    frame = pd.DataFrame([{
        "h2h_points": int(upto[upto["short_name"] == name]["h2h_points"].sum()),
        "points_for": int(upto[upto["short_name"] == name]["points_for"].sum()),
    } for name in drafters])
    return _h2h_rank(frame)


def reconcile_head_to_head(table: pd.DataFrame, details: dict,
                           standings: pd.DataFrame) -> list[str]:
    """
    Compare the rebuilt table against the API's own, on settled rows only.

    3 / 1 / 0 is FPL's documented rule rather than anything visible in the
    payload, so it is checked against the source of truth the moment there is
    one. Returns human-readable differences; empty means the rebuild agrees.
    Never raises — a mismatch is worth reporting loudly, not worth dropping a
    whole build over.
    """
    official = {row["league_entry"]: row for row in (details.get("standings") or [])}
    if not any(row.get("matches_played") for row in official.values()):
        return []                       # nothing settled yet, nothing to check against

    names = dict(zip(standings["id"], standings["short_name"]))
    mine = table.set_index("short_name")
    notes = []
    for entry, row in official.items():
        name = names.get(entry)
        if name is None or name not in mine.index:
            continue
        ours = mine.loc[name]
        # The API counts finished matches only, so a provisional row is expected
        # to be ahead of it. That is not a disagreement.
        if bool(ours["provisional"]):
            continue
        for ours_column, api_column in (("h2h_points", "total"), ("won", "matches_won"),
                                        ("drawn", "matches_drawn"),
                                        ("points_for", "points_for")):
            if int(ours[ours_column]) != int(row.get(api_column, 0)):
                notes.append(f"{name}: {ours_column}={int(ours[ours_column])} but the "
                             f"API says {api_column}={row.get(api_column)}")
    return notes
