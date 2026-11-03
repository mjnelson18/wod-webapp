"""Weekly talking points: the per-gameweek sibling of the season review facts. Pure.

Feeds `weekly_beats.json`. Same philosophy as narrative.py — these are generated,
checkable numbers; every beat is optional and a quiet week emits nothing rather
than a confident filler line. The frontend renders each `kind` through a fixed
sentence template, so a beat is structured data, never prose.

Thresholds are deliberately blunt module constants: the point is "worth saying on
the podcast", not statistical rigour. Content is curated — adding or dropping a
beat kind goes through the user.
"""

import pandas as pd

from .narrative import _jsonable, _person

# A score this far from the drafter's own season-to-date average is a story.
PERSONAL_OUTLIER_MARGIN = 20
# ...but an average over a week or two is noise, so outliers need some history.
PERSONAL_OUTLIER_MIN_HISTORY = 4
# The week's worst optimal-XI gap only rates a mention when it really stung.
BENCH_PAIN_MIN = 10
# A transfer that paid this much in its first week was called right.
INSTANT_TRANSFER_MIN = 8
# Rank moves of a place happen constantly; two or more is movement.
RANK_SWING_MIN = 2
# In an H2H league, a win over a side this many places higher is an upset.
H2H_UPSET_RANK_GAP = 3

TRADE_PROCESSED = "p"
SUCCESSFUL = "successful"


def _beat(league: str, gameweek: int, kind: str, data: dict) -> dict:
    return {"league": league, "gameweek": int(gameweek), "kind": kind, "data": data}


def _lead_beats(rows: pd.DataFrame, league: str, names: dict) -> list[dict]:
    """A change at the top of the cumulative table, including into a tie."""
    out, previous = [], None
    for gameweek in sorted(rows["gameweek"].unique()):
        standing = rows[rows["gameweek"] == gameweek].sort_values(
            "cumulative_points", ascending=False)
        top = standing.iloc[0]
        lead = (int(top["cumulative_points"] - standing.iloc[1]["cumulative_points"])
                if len(standing) > 1 else 0)
        leader = str(top["short_name"])
        if previous is not None and leader != previous:
            out.append(_beat(league, gameweek, "lead_change", {
                "new": _person(names, league, leader),
                "previous": _person(names, league, previous),
                "lead": lead,
                "tied": bool(lead == 0 and len(standing) > 1),
            }))
        previous = leader
    return out


def _week_beats(week: pd.DataFrame, prior: pd.DataFrame, league: str,
                gameweek: int, names: dict) -> list[dict]:
    out = []

    # A new best or worst week for the whole league (needs history to beat).
    if len(prior):
        high = week.loc[week["points_scored"].idxmax()]
        if int(high["points_scored"]) > int(prior["points_scored"].max()):
            out.append(_beat(league, gameweek, "season_high", {
                **_person(names, league, str(high["short_name"])),
                "points": int(high["points_scored"]),
            }))
        low = week.loc[week["points_scored"].idxmin()]
        if int(low["points_scored"]) < int(prior["points_scored"].min()):
            out.append(_beat(league, gameweek, "season_low", {
                **_person(names, league, str(low["short_name"])),
                "points": int(low["points_scored"]),
            }))

    # A drafter far off their own established average, either way.
    for record in week.to_dict("records"):
        history = prior[prior["short_name"] == record["short_name"]]["points_scored"]
        if len(history) < PERSONAL_OUTLIER_MIN_HISTORY:
            continue
        average = float(history.mean())
        difference = float(record["points_scored"]) - average
        if abs(difference) >= PERSONAL_OUTLIER_MARGIN:
            out.append(_beat(league, gameweek, "personal_outlier", {
                **_person(names, league, str(record["short_name"])),
                "points": int(record["points_scored"]),
                "average": round(average, 1),
                "direction": "above" if difference > 0 else "below",
            }))

    # Rank swings of two or more places in one week.
    for record in week.to_dict("records"):
        before = int(record.get("previous_gameweek_rank") or 0)
        after = int(record.get("gameweek_rank") or 0)
        if before and after and abs(after - before) >= RANK_SWING_MIN:
            out.append(_beat(league, gameweek, "rank_swing", {
                **_person(names, league, str(record["short_name"])),
                "from": before, "to": after,
            }))
    return out


def _bench_beat(summary: pd.DataFrame, league: str, gameweek: int,
                names: dict) -> list[dict]:
    """The week's worst optimal-XI gap, when it is painful enough to mention."""
    rows = summary[(summary["league_code"] == league)
                   & (summary["gameweek"] == gameweek)]
    if rows.empty or not rows["optimal_points"].notna().any():
        return []
    per = rows.groupby("short_name")[["optimal_points", "points_scored"]].sum()
    lost = per["optimal_points"] - per["points_scored"]
    worst = lost.idxmax()
    if float(lost[worst]) < BENCH_PAIN_MIN:
        return []
    return [_beat(league, gameweek, "bench_pain", {
        **_person(names, league, str(worst)),
        "points_lost": int(round(float(lost[worst]))),
    })]


def _move_beats(transfers: pd.DataFrame, trades: pd.DataFrame, league: str,
                gameweek: int, names: dict) -> list[dict]:
    out = []

    mine = transfers[(transfers["league_code"] == league)
                     & (transfers["gameweek"] == gameweek)
                     & (transfers["result"] == SUCCESSFUL)] if len(transfers) else transfers
    net_column = "net_points_of_transfer_in_week"
    if len(mine) and net_column in mine.columns and mine[net_column].notna().any():
        best = mine.loc[mine[net_column].idxmax()]
        if float(best[net_column]) >= INSTANT_TRANSFER_MIN:
            out.append(_beat(league, gameweek, "instant_transfer", {
                **_person(names, league, str(best["short_name"])),
                "kind": best.get("kind"),
                "player_in": best.get("player_in"),
                "player_out": best.get("player_out"),
                "net_points": int(best[net_column]),
            }))

    swaps = trades[(trades["league_code"] == league)
                   & (trades["gameweek"] == gameweek)
                   & (trades["state"] == TRADE_PROCESSED)] if len(trades) else trades
    for record in (swaps.to_dict("records") if len(swaps) else []):
        # A swap with an excluded entry is not a competitive trade (see narrative).
        if str(record["offered_by"]).isdigit() or str(record["received_by"]).isdigit():
            continue
        out.append(_beat(league, gameweek, "trade_executed", {
            "offered_by": _person(names, league, str(record["offered_by"])),
            "received_by": _person(names, league, str(record["received_by"])),
            "player_in": record.get("player_in"),
            "player_out": record.get("player_out"),
        }))
    return out


def _upset_beats(matches: pd.DataFrame, week: pd.DataFrame, league: str,
                 gameweek: int, names: dict) -> list[dict]:
    """An H2H win over a side well above you in the points table going in."""
    if matches is None or not len(matches):
        return []
    mine = matches[(matches["league_code"] == league)
                   & (matches["gameweek"] == gameweek)
                   & matches["started"]]
    if mine.empty:
        return []
    ranks = dict(zip(week["short_name"], week["previous_gameweek_rank"]))
    out = []
    for record in mine.to_dict("records"):
        winner = record.get("winner")
        if not winner:
            continue
        loser = record["away"] if winner == record["home"] else record["home"]
        winner_rank = int(ranks.get(winner) or 0)
        loser_rank = int(ranks.get(loser) or 0)
        if winner_rank and loser_rank and winner_rank - loser_rank >= H2H_UPSET_RANK_GAP:
            out.append(_beat(league, gameweek, "h2h_upset", {
                "winner": _person(names, league, str(winner)),
                "loser": _person(names, league, str(loser)),
                "winner_rank": winner_rank,
                "loser_rank": loser_rank,
                "provisional": not bool(record.get("finished")),
            }))
    return out


def weekly_beats(*, season, league_table: pd.DataFrame,
                 league_table_by_week: pd.DataFrame, weekly_summary: pd.DataFrame,
                 transfers: pd.DataFrame, trades: pd.DataFrame,
                 h2h_matches: pd.DataFrame | None = None) -> list[dict]:
    """Every talking point for every played gameweek, newest data included.

    Beats for the current gameweek are provisional by nature — they are recomputed
    every build, so a mid-gameweek outlier that fades simply disappears.
    """
    names = {(r["league_code"], r["short_name"]): r.get("name")
             for r in league_table.to_dict("records")}

    out = []
    for league in season.leagues:
        rows = league_table_by_week[league_table_by_week["league_code"] == league.code]
        if rows.empty:
            continue
        out.extend(_lead_beats(rows, league.code, names))
        for gameweek in sorted(rows["gameweek"].unique()):
            week = rows[rows["gameweek"] == gameweek]
            prior = rows[rows["gameweek"] < gameweek]
            out.extend(_week_beats(week, prior, league.code, int(gameweek), names))
            out.extend(_bench_beat(weekly_summary, league.code, int(gameweek), names))
            out.extend(_move_beats(transfers, trades, league.code, int(gameweek), names))
            out.extend(_upset_beats(h2h_matches, week, league.code, int(gameweek), names))

    out.sort(key=lambda b: (b["league"], b["gameweek"]))
    return _jsonable(out)
