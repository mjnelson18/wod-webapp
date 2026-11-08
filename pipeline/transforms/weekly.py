"""weekly_summary and weekly_points — the richest tables. Ported from notebook cell 12. Pure.

The notebook fetched inline inside this logic; here fetching happens in build.py
and the transform receives raw payloads keyed by gameweek and entry, which is what
makes it testable against the snapshot.

Gameweeks are 1-indexed: `live_by_gameweek[1]` is `event/1`.
"""

import numpy as np
import pandas as pd

from .optimal import add_optimal_points

STARTING_XI = 11
NOT_DRAFTED = "Not Drafted"
NOT_ORIGINALLY_DRAFTED = "Not Originally Drafted"


def points_scored_share(scored: pd.Series, totals: pd.Series) -> pd.Series:
    """
    Each player's share of the drafter's league points.

    `totals` is the drafter's season points, which stays 0 until their first
    fixture is scored — so during a live GW1 the plain division yields inf, and
    inf reaches the JSON as the bare token `Infinity`, which the browser refuses
    to parse. Nobody's share of an unscored season is anything but zero; a
    genuinely missing total stays missing.
    """
    return (scored / totals).where(totals != 0, 0.0)


def _picks_frame(picks_by_entry_gameweek: dict, entry_names: dict, league_code) -> pd.DataFrame:
    """
    One row per entry per squad slot per gameweek.

    `originally_starting` is the lineup *before* auto-subs: place <= 11, then each
    sub reverses its two players — the one brought on was benched, the one taken
    off was starting.
    """
    rows = []
    for (entry_id, gameweek), payload in sorted(picks_by_entry_gameweek.items()):
        if not payload:
            continue
        short_name = entry_names.get(int(entry_id))
        if short_name is None:
            continue
        subs = payload.get("subs") or []
        subbed_in = {s["element_in"] for s in subs}
        subbed_out = {s["element_out"] for s in subs}
        for pick in payload.get("picks", []):
            element = pick["element"]
            place = pick["position"]
            starting = 1 if place <= STARTING_XI else 0
            if element in subbed_in:
                starting = 0
            elif element in subbed_out:
                starting = 1
            rows.append({
                "element": element,
                "place": place,
                "gameweek": int(gameweek),
                "short_name": short_name,
                "league_code": league_code,
                "originally_starting": starting,
            })
    return pd.DataFrame(rows, columns=[
        "element", "place", "gameweek", "short_name", "league_code", "originally_starting",
    ])


def _points_frame(live_by_gameweek: dict, league_code) -> pd.DataFrame:
    """One row per element per gameweek, for every element the API reported.

    `minutes` rides along so a week in play can say who has actually featured
    yet; it is null when the payload does not carry it.
    """
    rows = []
    for gameweek, payload in sorted(live_by_gameweek.items()):
        for element_id, details in (payload or {}).get("elements", {}).items():
            rows.append({
                "id": int(element_id),
                "total_points": details["stats"].get("total_points", 0),
                "minutes": details["stats"].get("minutes"),
                "gameweek": int(gameweek),
            })
    frame = pd.DataFrame(rows, columns=["id", "total_points", "minutes", "gameweek"])
    frame["league_code"] = league_code
    return frame


def _fixture_state(live_by_gameweek: dict) -> tuple[pd.DataFrame, set[int]]:
    """
    Per (gameweek, club): has every one of its matches that week finished?

    From the fixture list the live payload carries beside the scores. A match is
    done at the final whistle (`finished_provisional`), before the bonus is
    confirmed — for "has this player played yet" that is the right moment. Also
    returns the gameweeks that carried a fixture list at all: a club absent from
    a known list has a blank week (nothing left to play), while a payload with
    no list says nothing either way.
    """
    rows, known = [], set()
    for gameweek, payload in sorted(live_by_gameweek.items()):
        fixtures = (payload or {}).get("fixtures")
        if fixtures is None:
            continue
        known.add(int(gameweek))
        done: dict[int, bool] = {}
        for fixture in fixtures:
            finished = bool(fixture.get("finished_provisional") or fixture.get("finished"))
            for team in (fixture.get("team_h"), fixture.get("team_a")):
                if team is None:
                    continue
                done[int(team)] = done.get(int(team), True) and finished
        rows.extend({"gameweek": int(gameweek), "team_id": team, "fixture_finished": finished}
                    for team, finished in done.items())
    return pd.DataFrame(rows, columns=["gameweek", "team_id", "fixture_finished"]), known


def _player_details(players: pd.DataFrame, draft_picks: pd.DataFrame,
                    league_code) -> pd.DataFrame:
    """Player lookup plus who originally drafted them *in this league*."""
    details = players[["id", "web_name", "position", "team", "team_name"]].rename(
        columns={"id": "element", "team": "team_id"}
    )
    league_picks = draft_picks[draft_picks["league_code"] == league_code]
    details = details.merge(
        league_picks[["element", "short_name", "index"]], on="element", how="left"
    ).rename(columns={"short_name": "drafter_name", "index": "draft_index"})
    details["drafter_name"] = details["drafter_name"].fillna(NOT_ORIGINALLY_DRAFTED)
    return details


def weekly_tables(*, picks_by_entry_gameweek: dict, live_by_gameweek: dict,
                  players: pd.DataFrame, draft_picks: pd.DataFrame,
                  standings: pd.DataFrame, entry_names: dict, league_code):
    """
    Build (weekly_summary, weekly_points) for one league.

    weekly_points covers *every* element, not just owned ones, and is emitted per
    league. That duplication is intentional: a footballer can be owned by different
    drafters in each league, so each league needs its own ownership view.
    """
    picks = _picks_frame(picks_by_entry_gameweek, entry_names, league_code)
    points = _points_frame(live_by_gameweek, league_code)

    summary = picks.merge(
        points[["id", "total_points", "minutes", "gameweek"]],
        left_on=["element", "gameweek"], right_on=["id", "gameweek"], how="inner",
    )
    summary["total_points"] = pd.to_numeric(summary["total_points"])
    summary["minutes"] = pd.to_numeric(summary["minutes"], errors="coerce").astype("Int64")
    summary["points_before_auto_subs"] = np.where(
        summary["originally_starting"] == 1, summary["total_points"], 0
    )

    # a player's own season total, across every gameweek fetched
    season_totals = (
        points.groupby("id", as_index=False)["total_points"].sum()
        .rename(columns={"total_points": "player_total_points", "id": "element"})
    )
    summary = summary.merge(season_totals, on="element", how="left")

    details = _player_details(players, draft_picks, league_code)
    summary = summary.merge(details, on="element", how="left")

    # Whether the player's club has finished its matches this week. Null where
    # the payload had no fixture list; a club missing from a list that exists
    # has a blank gameweek, which counts as finished.
    state, known = _fixture_state(live_by_gameweek)
    summary = summary.merge(state, on=["gameweek", "team_id"], how="left")
    blank = summary["gameweek"].isin(known) & summary["fixture_finished"].isna()
    summary.loc[blank, "fixture_finished"] = True
    summary["fixture_finished"] = summary["fixture_finished"].astype("boolean")

    # what the drafter actually banked: only the final starting XI counts
    summary["points_scored"] = np.where(
        summary["place"] <= STARTING_XI, summary["total_points"], 0
    )

    summary = summary.merge(
        draft_picks[["element", "short_name", "index", "round"]],
        on=["element", "short_name"], how="left",
    )
    summary["in_original_draft"] = np.where(summary["index"].isna(), 0, 1)

    summary = add_optimal_points(summary, group_keys=("short_name", "gameweek"))

    summary = summary.merge(
        standings[["league_code", "short_name", "total"]],
        on=["league_code", "short_name"], how="left",
    )
    summary["points_scored_pct"] = points_scored_share(
        summary["points_scored"], summary["total"]
    )

    for column in ("index", "round", "points_scored", "player_total_points"):
        summary[column] = summary[column].fillna(0).astype(int)

    summary = summary.sort_values(["league_code", "short_name", "id", "gameweek"])
    summary["points_scored_cumulative"] = (
        summary.groupby(["league_code", "short_name", "id"])["points_scored"].cumsum()
    )

    weekly_points = _weekly_points(points, summary, details)
    return summary, weekly_points


def _weekly_points(points: pd.DataFrame, summary: pd.DataFrame,
                   details: pd.DataFrame) -> pd.DataFrame:
    """
    One row per element per gameweek with current owner and in-week rank.

    `rank_in_week` is across all elements, method='min' descending. Unowned players
    read 'Not Drafted'; benched owners get a ' (Benched)' suffix, matching the
    notebook so the charts keyed on it still work.
    """
    frame = points.sort_values(["gameweek", "total_points"], ascending=[True, False]).copy()
    frame["rank_in_week"] = (
        frame.groupby("gameweek")["total_points"]
        .rank(method="min", ascending=False).astype(int)
    )
    frame = frame.merge(
        summary[["element", "gameweek", "short_name", "place"]],
        left_on=["id", "gameweek"], right_on=["element", "gameweek"], how="left",
    )
    frame["short_name"] = frame["short_name"].fillna(NOT_DRAFTED)
    frame["isBenched"] = np.where(frame["place"] > STARTING_XI, 1, 0)
    frame["short_name"] = np.where(
        frame["isBenched"] == 1, frame["short_name"] + " (Benched)", frame["short_name"]
    )
    return frame.merge(details, left_on="id", right_on="element", how="left",
                       suffixes=("", "_details"))


def attach_fixtures(frame: pd.DataFrame, fixtures_by_team: pd.DataFrame) -> pd.DataFrame:
    """Left-join per-team-per-gameweek fixture context on (gameweek, team_name)."""
    if fixtures_by_team is None or fixtures_by_team.empty:
        return frame
    return frame.merge(
        fixtures_by_team, left_on=["gameweek", "team_name"],
        right_on=["gameweek", "team"], how="left",
    )
