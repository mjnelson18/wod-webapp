"""Season review facts: the story beats a written review is built from. Pure.

Feeds `season_review_facts.json`. The split is deliberate — these numbers are
generated and checkable, the prose written from them is not. The review tab
renders the honours strip straight from this file, so the headline figures can
never drift from the data even if the prose ages.

Every beat is optional. A season lacking what a beat needs (2425 has no trades)
omits the beat rather than emitting a confident zero.

Give this the **full** weekly_points, not the reduced table written to JSON: a
failed waiver on an undrafted player needs that player's rows to score the miss.
"""

import numpy as np
import pandas as pd

# A pick from the back half of the draft — the rounds where nobody expects a
# season-defining player.
LATE_ROUND_FRACTION = 0.5

# Trades are only real once processed; offers and rejections are noise here even
# though the table keeps them.
TRADE_PROCESSED = "p"

SUCCESSFUL = "successful"

# Two ways a move fails, and only one of them is a story. `di` means somebody
# else got there first; `do` means the player being dropped had already gone,
# which is an admin misfire, not a miss.
BEATEN_TO_HIM = "unsuccessful - player in already been picked up"


def _person(names: dict, league: str, short: str) -> dict:
    """
    Short name plus the real name, so prose doesn't have to decode initials.

    An excluded entry has no row in the league table, so `trades_table` labels it
    with its bare entry id. Flag that rather than letting a number reach the prose
    as if it were somebody's name.
    """
    if (league, short) not in names and str(short).isdigit():
        return {"short_name": short, "name": None, "excluded_entry": True}
    return {"short_name": short, "name": names.get((league, short))}


def _leader_board(by_week: pd.DataFrame, league: str) -> list[dict]:
    """Who led the league after each gameweek, and by how much."""
    rows = by_week[by_week["league_code"] == league]
    out = []
    for gameweek in sorted(rows["gameweek"].unique()):
        standing = rows[rows["gameweek"] == gameweek].sort_values(
            "cumulative_points", ascending=False
        )
        top = standing.iloc[0]
        lead = 0
        if len(standing) > 1:
            lead = int(top["cumulative_points"] - standing.iloc[1]["cumulative_points"])
        out.append({
            "gameweek": int(gameweek),
            "short_name": str(top["short_name"]),
            "total": int(top["cumulative_points"]),
            "lead": lead,
            # A shared lead is a genuine story beat, and the sort above picks the
            # tied leader arbitrarily — so say when the pick was arbitrary.
            "tied": bool(lead == 0 and len(standing) > 1),
        })
    return out


def _race(by_week: pd.DataFrame, league: str, champion: str, names: dict) -> dict:
    """How the title was won: lead changes, the longest spell top, the comeback."""
    board = _leader_board(by_week, league)
    if not board:
        return {}

    changes = sum(1 for a, b in zip(board, board[1:]) if a["short_name"] != b["short_name"])

    # Longest unbroken run at the top, by anyone.
    best_run, run_holder, current, holder = 0, None, 0, None
    for entry in board:
        if entry["short_name"] == holder:
            current += 1
        else:
            holder, current = entry["short_name"], 1
        if current > best_run:
            best_run, run_holder = current, holder

    # The gameweek from which the champion was never headed again.
    led_from = board[0]["gameweek"]
    for entry in board:
        if entry["short_name"] != champion:
            led_from = None
    if led_from is None:
        last_headed = max(e["gameweek"] for e in board if e["short_name"] != champion)
        led_from = last_headed + 1 if last_headed < board[-1]["gameweek"] else None

    # The champion's worst moment: the largest gap they were ever behind by.
    mine = by_week[(by_week["league_code"] == league) & (by_week["short_name"] == champion)]
    champion_by_week = dict(zip(mine["gameweek"], mine["cumulative_points"]))
    deficit = {"points": 0, "gameweek": None, "leader": None}
    for entry in board:
        behind = entry["total"] - int(champion_by_week.get(entry["gameweek"], 0))
        if behind > deficit["points"]:
            deficit = {"points": int(behind), "gameweek": entry["gameweek"],
                       "leader": entry["short_name"]}

    return {
        "leader_by_gameweek": board,
        "lead_changes": int(changes),
        "distinct_leaders": sorted({e["short_name"] for e in board}),
        "longest_spell_top": {**_person(names, league, run_holder),
                              "gameweeks": int(best_run)},
        "champion_led_unbroken_from": led_from,
        "wire_to_wire": bool(led_from == board[0]["gameweek"]),
        "biggest_deficit_overturned": (
            {**_person(names, league, champion), **deficit} if deficit["points"] else None
        ),
    }


def _extremes(by_week: pd.DataFrame, league: str, names: dict) -> dict:
    """The best and worst single weeks, and the widest gap between two managers."""
    rows = by_week[by_week["league_code"] == league]
    if rows.empty:
        return {}

    def week(record) -> dict:
        return {**_person(names, league, str(record["short_name"])),
                "gameweek": int(record["gameweek"]),
                "points": int(record["points_scored"])}

    high = week(rows.loc[rows["points_scored"].idxmax()])
    low = week(rows.loc[rows["points_scored"].idxmin()])

    # Week-on-week movement per drafter — the collapse and the bounce.
    swings = rows.sort_values(["short_name", "gameweek"]).copy()
    swings["change"] = swings.groupby("short_name")["points_scored"].diff()
    swings = swings.dropna(subset=["change"])

    rise = fall = None
    if not swings.empty:
        def swing(record) -> dict:
            return {**_person(names, league, str(record["short_name"])),
                    "gameweek": int(record["gameweek"]),
                    "points": int(record["points_scored"]),
                    "change": int(record["change"])}
        rise = swing(swings.loc[swings["change"].idxmax()])
        fall = swing(swings.loc[swings["change"].idxmin()])

    # The week someone got taken apart by a rival.
    gap = {"gap": 0}
    for gameweek in sorted(rows["gameweek"].unique()):
        standing = rows[rows["gameweek"] == gameweek]
        best = standing.loc[standing["points_scored"].idxmax()]
        worst = standing.loc[standing["points_scored"].idxmin()]
        spread = int(best["points_scored"] - worst["points_scored"])
        if spread > gap["gap"]:
            gap = {"gameweek": int(gameweek), "gap": spread,
                   "high": week(best), "low": week(worst)}

    return {"highest_gameweek": high, "lowest_gameweek": low,
            "biggest_rise": rise, "biggest_fall": fall,
            "widest_gap_in_a_week": gap if gap["gap"] else None}


def _draft(draft_picks: pd.DataFrame, draft_performance: pd.DataFrame,
           league: str, names: dict) -> dict:
    """The pick that won a season, the one from nowhere, and the round-one dud."""
    picks = draft_picks[draft_picks["league_code"] == league]
    if picks.empty or draft_performance is None or draft_performance.empty:
        return {}

    realised = draft_performance[draft_performance["league_code"] == league][
        ["id", "points_realised_by_drafter", "total_points"]
    ].rename(columns={"id": "element"})
    frame = picks.merge(realised, on="element", how="left", suffixes=("", "_season"))
    frame["points_realised_by_drafter"] = frame["points_realised_by_drafter"].fillna(0)
    if "total_points_season" in frame.columns:
        frame["total_points"] = frame["total_points_season"].fillna(frame["total_points"])
    frame = frame.dropna(subset=["total_points"])
    if frame.empty:
        return {}

    def pick(record) -> dict:
        return {
            **_person(names, league, str(record["short_name"])),
            "player": str(record["web_name"]),
            "position": record.get("position"),
            "index": int(record["index"]),
            "round": None if pd.isna(record.get("round")) else int(record["round"]),
            "player_total_points": int(record["total_points"]),
            "points_realised_by_drafter": int(record["points_realised_by_drafter"]),
        }

    best = pick(frame.loc[frame["points_realised_by_drafter"].idxmax()])

    late = None
    if frame["round"].notna().any():
        cutoff = frame["round"].max() * LATE_ROUND_FRACTION
        tail = frame[frame["round"] > cutoff]
        if not tail.empty:
            late = pick(tail.loc[tail["points_realised_by_drafter"].idxmax()])

    # A first-round pick who returned nothing is the funniest number in the data.
    bust = None
    first_round = frame[frame["round"] == 1] if frame["round"].notna().any() else frame.nsmallest(
        len(names), "index"
    )
    if not first_round.empty:
        bust = pick(first_round.loc[first_round["total_points"].idxmin()])

    return {"best_pick": best, "best_late_pick": late, "round_one_bust": bust}


def _points_since(weekly_points: pd.DataFrame, frame: pd.DataFrame,
                  element_column: str, gameweek_column: str = "gameweek") -> pd.Series:
    """
    Sum a player's points from a gameweek to the end of the season.

    Same definition `finalise_trades` uses, so a waiver and a trade are measured
    the same way — points the move could have banked, whoever ended up holding them.

    Element ids are coerced because 2425's CSV-derived transfers carry them as
    strings, and pandas refuses to merge object against int64.
    """
    points = weekly_points[["league_code", "id", "gameweek", "total_points"]].copy()
    points["id"] = pd.to_numeric(points["id"], errors="coerce")

    base = frame[["league_code", gameweek_column, element_column]].reset_index(names="_row")
    base[element_column] = pd.to_numeric(base[element_column], errors="coerce")
    base[gameweek_column] = pd.to_numeric(base[gameweek_column], errors="coerce")

    merged = base.merge(points, left_on=["league_code", element_column],
                        right_on=["league_code", "id"], how="left",
                        suffixes=("_move", "_row"))
    merged = merged[merged[f"{gameweek_column}_move"] <= merged["gameweek_row"]]
    return merged.groupby("_row")["total_points"].sum()


def _resolve_elements(frame: pd.DataFrame, weekly_points: pd.DataFrame, league: str,
                      column: str, name_column: str) -> pd.Series:
    """
    Element ids for a move, recovered from the player's name where the id is absent.

    2425's CSV transfers record names and no ids at all, so without this every
    2425 move scores zero and the beats read as real. Only unambiguous names are
    resolved — if two players in the league share a `web_name` the row stays
    unresolved and drops out of the valued beats rather than joining to a guess.
    """
    ids = pd.to_numeric(frame.get(column), errors="coerce")
    if ids.notna().any() or name_column not in frame.columns:
        return ids

    pool = weekly_points[weekly_points["league_code"] == league]
    counts = pool.groupby("web_name")["id"].nunique()
    unique = pool.drop_duplicates("web_name").set_index("web_name")["id"]
    lookup = unique[counts[unique.index] == 1]
    return pd.to_numeric(frame[name_column].map(lookup), errors="coerce")


def _moves(transfers: pd.DataFrame, trades: pd.DataFrame, weekly_points: pd.DataFrame,
           league: str, names: dict) -> dict:
    """Waivers that paid, waivers that got away, and trades that aged badly."""
    out = {}

    mine = transfers[transfers["league_code"] == league].copy() if len(transfers) else transfers
    if len(mine):
        mine["element_in"] = _resolve_elements(mine, weekly_points, league,
                                               "element_in", "player_in")
        mine["element_out"] = _resolve_elements(mine, weekly_points, league,
                                                "element_out", "player_out")
        mine["_in_since"] = _points_since(weekly_points, mine, "element_in").reindex(mine.index)
        mine["_out_since"] = _points_since(weekly_points, mine, "element_out").reindex(mine.index)
        mine[["_in_since", "_out_since"]] = mine[["_in_since", "_out_since"]].fillna(0)
        mine["_net_since"] = mine["_in_since"] - mine["_out_since"]

        # A move whose players couldn't be identified scores zero, and a zero would
        # win "worst transfer" outright. Keep it out of the valued beats entirely.
        valued = mine.dropna(subset=["element_in", "element_out"])

        def move(record) -> dict:
            return {
                **_person(names, league, str(record["short_name"])),
                "gameweek": int(record["gameweek"]),
                "kind": record.get("kind"),
                "player_in": record.get("player_in"),
                "player_out": record.get("player_out"),
                "player_in_points_since": int(record["_in_since"]),
                "player_out_points_since": int(record["_out_since"]),
                "net_points_since": int(record["_net_since"]),
            }

        done = valued[valued["result"] == SUCCESSFUL]
        if not done.empty:
            out["best_transfer"] = move(done.loc[done["_net_since"].idxmax()])
            out["worst_transfer"] = move(done.loc[done["_net_since"].idxmin()])

        # The one that got away: beaten to a player who then scored all season for
        # somebody else. Only `di` qualifies — see BEATEN_TO_HIM.
        missed = valued[valued["result"] == BEATEN_TO_HIM]
        if not missed.empty:
            record = missed.loc[missed["_in_since"].idxmax()]
            out["worst_miss"] = {
                **_person(names, league, str(record["short_name"])),
                "gameweek": int(record["gameweek"]),
                "player": record.get("player_in"),
                "reason": record.get("result"),
                "points_since": int(record["_in_since"]),
            }

        out["counts"] = {
            "successful": int((mine["result"] == SUCCESSFUL).sum()),
            "failed": int((mine["result"].notna() & (mine["result"] != SUCCESSFUL)).sum()),
            "beaten_to_a_player": int((mine["result"] == BEATEN_TO_HIM).sum()),
            "waivers": int((mine["kind"] == "waiver").sum()),
            "free_agents": int((mine["kind"] == "free agent").sum()),
            # How many could actually be scored. Below the total means some moves
            # named players this season's data can't identify.
            "valued": int(len(valued)),
        }

    swaps = trades[(trades["league_code"] == league)] if len(trades) else trades
    if len(swaps):
        swaps = swaps[swaps["state"] == TRADE_PROCESSED]
    if len(swaps):
        # A swap with an excluded entry is not a competitive trade. That squad is a
        # deliberate non-participant whose owner auto-accepts, so its players were
        # effectively free agents the whole league could have waivered. Counted, so
        # the total is honest, but never ranked as the best or worst deal of a season.
        involves_excluded = swaps.apply(
            lambda r: str(r["offered_by"]).isdigit() or str(r["received_by"]).isdigit(),
            axis=1,
        )
        out["trade_items_with_excluded_entry"] = int(involves_excluded.sum())
        swaps = swaps[~involves_excluded]

    if len(swaps):
        def swap(record) -> dict:
            return {
                "offered_by": _person(names, league, str(record["offered_by"])),
                "received_by": _person(names, league, str(record["received_by"])),
                "gameweek": int(record["gameweek"]),
                "player_in": record.get("player_in"),
                "player_out": record.get("player_out"),
                "net_points": int(record["net_points_from_trade"]),
            }
        out["best_trade"] = swap(swaps.loc[swaps["net_points_from_trade"].idxmax()])
        out["worst_trade"] = swap(swaps.loc[swaps["net_points_from_trade"].idxmin()])
        out["trade_count"] = int(len(swaps))

    return out


def _bench(weekly_summary: pd.DataFrame, league: str, names: dict) -> dict:
    """Points left on the bench — the self-inflicted wound the whole group enjoys."""
    rows = weekly_summary[weekly_summary["league_code"] == league]
    if rows.empty or not rows["optimal_points"].notna().any():
        return {}

    weekly = rows.groupby(["short_name", "gameweek"], as_index=False)[
        ["optimal_points", "points_scored"]
    ].sum()
    weekly["lost"] = weekly["optimal_points"] - weekly["points_scored"]

    worst = weekly.loc[weekly["lost"].idxmax()]
    season = weekly.groupby("short_name", as_index=False)["lost"].sum().sort_values(
        "lost", ascending=False
    )

    return {
        "worst_week": {**_person(names, league, str(worst["short_name"])),
                       "gameweek": int(worst["gameweek"]),
                       "points_lost": int(round(worst["lost"]))},
        "season_lost": [{**_person(names, league, str(r["short_name"])),
                         "points_lost": int(round(r["lost"]))}
                        for r in season.to_dict("records")],
    }


def _cross_league(by_week: pd.DataFrame, table: pd.DataFrame, leagues: list) -> dict:
    """
    Prem v Conf, on **mean** points per drafter.

    Totals would be meaningless for 2425, where the Conference ran seven squads to
    the Premiership's five and would win nearly every week on headcount alone.
    """
    codes = [lg.code for lg in leagues]
    if len(codes) < 2:
        return {}

    means = by_week.groupby(["league_code", "gameweek"], as_index=False)["points_scored"].mean()
    weekly, record = [], {code: 0 for code in codes}
    for gameweek in sorted(means["gameweek"].unique()):
        week = means[means["gameweek"] == gameweek]
        scores = {str(r["league_code"]): round(float(r["points_scored"]), 1)
                  for r in week.to_dict("records")}
        winner = max(scores, key=scores.get) if scores else None
        if winner and len(set(scores.values())) > 1:
            record[winner] = record.get(winner, 0) + 1
        weekly.append({"gameweek": int(gameweek), "mean_points": scores, "winner": winner})

    season_mean = {
        str(r["league_code"]): round(float(r["points_scored"]), 1)
        for r in means.groupby("league_code", as_index=False)["points_scored"].mean()
        .to_dict("records")
    }

    # Would the Conference champion have troubled the Premiership? The question
    # the promoted side gets asked all summer.
    crossover = []
    for league in codes:
        mine = table[table["league_code"] == league].sort_values("rank")
        if mine.empty:
            continue
        champion = mine.iloc[0]
        for other in codes:
            if other == league:
                continue
            theirs = table[table["league_code"] == other]["total"].dropna()
            if theirs.empty:
                continue
            placing = int((theirs > champion["total"]).sum()) + 1
            crossover.append({
                "champion_of": league,
                "short_name": str(champion["short_name"]),
                "name": champion.get("name"),
                "total": int(champion["total"]),
                "would_rank_in": other,
                "would_rank": placing,
                "of": int(len(theirs)),
            })

    return {"weekly": weekly, "record": record, "season_mean_points": season_mean,
            "champion_crossover": crossover}


def _honours(table: pd.DataFrame, league) -> dict:
    """Final table plus who went up, who went down, and who wears the chicken suit."""
    rows = table[table["league_code"] == league.code].sort_values("rank")
    if rows.empty:
        return {}

    def entry(record) -> dict:
        return {"rank": int(record["rank"]), "short_name": str(record["short_name"]),
                "name": record.get("name"), "entry_name": record.get("entry_name"),
                "total": int(record["total"])}

    final = [entry(r) for r in rows.to_dict("records")]
    champion, runner_up = final[0], final[1] if len(final) > 1 else None

    promoted = final[:league.promoted] if league.promoted else []
    relegated = final[-league.relegated:] if league.relegated else []

    return {
        "final_table": final,
        "champion": champion,
        "runner_up": runner_up,
        "title_margin": (champion["total"] - runner_up["total"]) if runner_up else None,
        "promoted": promoted,
        "relegated": relegated,
        # Last place. In the bottom league that also means the chicken suit, which
        # is the league's business rather than something to infer here.
        "wooden_spoon": final[-1],
        "spread": champion["total"] - final[-1]["total"],
    }


def _jsonable(value):
    """numpy scalars and NaN are not JSON serialisable; this is written straight out."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is pd.NaT:
        return None
    return value


def season_review_facts(*, season, current_week: int, league_table: pd.DataFrame,
                        league_table_by_week: pd.DataFrame, weekly_summary: pd.DataFrame,
                        weekly_points: pd.DataFrame, draft_picks: pd.DataFrame,
                        draft_performance: pd.DataFrame, transfers: pd.DataFrame,
                        trades: pd.DataFrame) -> dict:
    """
    Every story beat for one season, as data.

    Read this, then write the review — don't compute anything from the prose side.
    """
    names = {(r["league_code"], r["short_name"]): r.get("name")
             for r in league_table.to_dict("records")}

    leagues = []
    for league in season.leagues:
        honours = _honours(league_table, league)
        if not honours:
            continue
        champion = honours["champion"]["short_name"]
        leagues.append({
            "code": league.code,
            "name": league.name,
            "size": league.size,
            **honours,
            "race": _race(league_table_by_week, league.code, champion, names),
            "extremes": _extremes(league_table_by_week, league.code, names),
            "draft": _draft(draft_picks, draft_performance, league.code, names),
            "moves": _moves(transfers, trades, weekly_points, league.code, names),
            "bench": _bench(weekly_summary, league.code, names),
        })

    return _jsonable({
        "season": season.season,
        "label": season.label,
        "current_gameweek": int(current_week),
        "complete": bool(current_week >= season.total_gameweeks),
        "leagues": leagues,
        "cross_league": _cross_league(league_table_by_week, league_table, season.leagues),
    })
