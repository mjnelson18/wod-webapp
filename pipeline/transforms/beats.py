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
# Starting the wrong one of two keepers is only worth a line when it cost this
# much in the week...
KEEPER_CALL_MIN = 5
# ...or when it has become a habit: this many wrong calls in a row.
KEEPER_STREAK_MIN = 3

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
                gameweek: int, names: dict, live: bool = False) -> list[dict]:
    """
    Points can only climb while a gameweek is in play, so a week that is
    already the season's best, or already well above someone's average, is a
    fact worth saying on Saturday night. A low week is not: the games still to
    come may fix it. Those wait for the final whistle.
    """
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
        if not live and int(low["points_scored"]) < int(prior["points_scored"].min()):
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
        if live and difference < 0:
            continue
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
                names: dict, live: bool = False) -> list[dict]:
    """The week's worst optimal-XI gap, when it is painful enough to mention.

    Nothing to say while the week is in play: auto-subs have not happened and
    the optimal XI is measured against players who have not kicked off.
    """
    if live or not len(summary):
        # A columnless empty frame (preseason, or an H2H build with no summary
        # yet) would KeyError on the column lookups below.
        return []
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


def _keeper_beats(summary: pd.DataFrame, league: str, gameweek: int,
                  names: dict, live: bool = False) -> list[dict]:
    """The wrong one of two keepers started — when it hurt, or when it's a habit.

    Same rules as narrative._keepers: a week only counts as a call when exactly
    one keeper started and at least one sat on the bench, and an equal score is
    the right call. The season-to-date record and the current streak ride along
    so the sentence can say "nine weeks out of nine" rather than just "again".

    In a week still being played the call is settled as soon as every one of
    the drafter's keepers has finished his match — which can be Saturday
    teatime — so it is said then, and not before.
    """
    needed = {"position", "place", "total_points", "short_name", "gameweek"}
    if not len(summary) or not needed.issubset(summary.columns):
        return []
    rows = summary[(summary["league_code"] == league)
                   & (summary["position"] == "GKP")
                   & (summary["gameweek"] <= gameweek)]
    if rows.empty:
        return []

    points = lambda value: 0.0 if pd.isna(value) else float(value)  # noqa: E731
    out = []
    for short, mine in rows.groupby("short_name"):
        weeks = wrong = streak = 0
        this_week = None
        for week_no, week in sorted(mine.groupby("gameweek"), key=lambda kv: kv[0]):
            started = week[week["place"] <= 11]
            benched = week[week["place"] > 11]
            if len(started) != 1 or benched.empty:
                continue
            weeks += 1
            start_points = points(started.iloc[0]["total_points"])
            best_benched = benched.loc[benched["total_points"].idxmax()]
            bench_points = points(best_benched["total_points"])
            if start_points >= bench_points:
                streak = 0
                continue
            wrong += 1
            streak += 1
            if int(week_no) == gameweek and not (live and not _all_finished(week)):
                this_week = {
                    "started": str(started.iloc[0].get("web_name", "")),
                    "started_points": int(round(start_points)),
                    "benched": str(best_benched.get("web_name", "")),
                    "benched_points": int(round(bench_points)),
                    "points_lost": int(round(bench_points - start_points)),
                }
        if this_week is None:
            continue
        if this_week["points_lost"] < KEEPER_CALL_MIN and streak < KEEPER_STREAK_MIN:
            continue
        out.append(_beat(league, gameweek, "keeper_call", {
            **_person(names, league, str(short)),
            **this_week,
            "wrong": int(wrong),
            "weeks": int(weeks),
            "streak": int(streak),
        }))
    return out


def _all_finished(rows: pd.DataFrame) -> bool:
    """Every player in `rows` has a finished (or blank) fixture this week."""
    if "fixture_finished" not in rows.columns or rows.empty:
        return False
    return bool(rows["fixture_finished"].fillna(False).astype(bool).all())


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
                 h2h_matches: pd.DataFrame | None = None,
                 live_gameweek: int | None = None) -> list[dict]:
    """Every talking point for every played gameweek, newest data included.

    `live_gameweek` is the week still being played, if any. Its beats are
    recomputed every build, so one that fades simply disappears — but some can
    never hold mid-week (a season low, a bench-pain figure before auto-subs) and
    are not emitted, while a keeper call waits until both keepers have played.
    The ones that are emitted carry `provisional: true` so the sentence can say
    "so far".
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
            live = live_gameweek is not None and int(gameweek) == int(live_gameweek)
            out.extend(_week_beats(week, prior, league.code, int(gameweek), names, live=live))
            out.extend(_bench_beat(weekly_summary, league.code, int(gameweek), names, live=live))
            out.extend(_keeper_beats(weekly_summary, league.code, int(gameweek), names, live=live))
            out.extend(_move_beats(transfers, trades, league.code, int(gameweek), names))
            out.extend(_upset_beats(h2h_matches, week, league.code, int(gameweek), names))

    if live_gameweek is not None:
        for beat in out:
            if beat["gameweek"] == int(live_gameweek):
                beat["provisional"] = True

    out.sort(key=lambda b: (b["league"], b["gameweek"]))
    return _jsonable(out)
