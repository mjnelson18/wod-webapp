"""Unit tests for the pieces that don't need a full season build."""

import json

import numpy as np
import pandas as pd
import pytest

from pipeline.config import League, Season, get_season, is_configured
from pipeline.fetchers import SnapshotSource
from pipeline.outputs import _clean, _dump
from pipeline.transforms.draft_picks import draft_picks_table
from pipeline.transforms.fixtures import fixtures_from_live
from pipeline.transforms.league import league_gaps, league_table
from pipeline.transforms.players import bootstrap_team_ids_agree
from pipeline.transforms.weekly import _picks_frame, points_scored_share


# --- config -----------------------------------------------------------------

def test_season_registry():
    assert get_season("2526").label == "2025/26"
    assert get_season(2526).season == "2526"      # accepts int
    with pytest.raises(KeyError):
        get_season("9999")


def test_live_season_without_league_codes_is_unconfigured():
    """
    A live season refuses to build until its codes are set.

    Deliberately synthetic. This used to assert on the real current season, which
    made it a test of today's config rather than of the behaviour — so filling in
    the 2627 codes on draft night turned it red for doing exactly what it was
    supposed to do.
    """
    def live(**codes):
        return Season(
            season="9999", label="future", default_source="live",
            leagues=tuple(
                League(code=code, name=code, league_code=value, size=6)
                for code, value in codes.items()
            ),
        )

    assert is_configured(live(Prem=None, Conf=None)) is False
    assert is_configured(live(Prem=19736, Conf=None)) is False   # one is not enough
    assert is_configured(live(Prem=19736, Conf=19116)) is True
    # archives carry no league codes at all and must never be gated on them
    assert is_configured(get_season("2526")) is True   # snapshot-backed
    assert is_configured(get_season("2425")) is True   # CSV-derived


def test_settled_structure_is_six_six_two_two():
    season = get_season("2526")
    assert [lg.size for lg in season.leagues] == [6, 6]
    assert season.league("Prem").relegated == 2
    assert season.league("Conf").promoted == 2


def test_excluded_entry_recorded_for_2526():
    assert get_season("2526").league("Prem").exclude_entries == (92234,)
    assert get_season("2526").excluded_entries == {92234}


# --- gameweek indexing ------------------------------------------------------

def test_snapshot_is_one_indexed():
    """GW1 is event/1. The notebook's event/{gw+1} was a loop artifact."""
    source = SnapshotSource("reference/raw_2526")
    first = source.event_live(1)
    assert first is not None
    events = {f["event"] for f in first["fixtures"]}
    assert events == {1}


def test_entry_picks_are_one_indexed():
    source = SnapshotSource("reference/raw_2526")
    picks = source.entry_event(177570, 1)
    assert picks is not None
    assert len(picks["picks"]) == 15


# --- the hybrid-bootstrap guard --------------------------------------------

def test_bootstrap_disagreement_is_detected():
    """
    The 2526 snapshot's draft bootstrap carries 2627 element->team ids while its
    own teams array is 2526. Joining them mislabels 39% of players' clubs, so the
    build must notice the hosts disagree.
    """
    source = SnapshotSource("reference/raw_2526")
    assert bootstrap_team_ids_agree(source.bootstrap_draft(), source.bootstrap_fantasy()) is False


def test_agreeing_bootstraps_pass_the_guard():
    same = {"teams": [{"short_name": "ARS"}, {"short_name": "LIV"}]}
    assert bootstrap_team_ids_agree(same, same) is True


# --- auto-subs --------------------------------------------------------------

def test_originally_starting_reverses_subs():
    """
    A player subbed on was benched originally; one subbed off was starting.

    element 99 is bench (place 12) but came on, so originally_starting = 0.
    element 5 started (place 5) but was subbed off, so originally_starting = 1.
    """
    payload = {
        "picks": [
            {"element": 5, "position": 5},
            {"element": 99, "position": 12},
            {"element": 7, "position": 7},
        ],
        "subs": [{"element_in": 99, "element_out": 5}],
    }
    frame = _picks_frame({(1, 1): payload}, {1: "MN"}, "Prem")
    by_element = frame.set_index("element")["originally_starting"].to_dict()
    assert by_element[99] == 0
    assert by_element[5] == 1
    assert by_element[7] == 1


# --- draft pick renumbering ------------------------------------------------

def test_renumbering_closes_gaps_from_excluded_entries():
    """
    An excluded entry that drafted for real leaves gaps in `index`. Survivors must
    be renumbered before `round` is derived, or rounds come out wrong.
    """
    # 3 drafters x 2 rounds, but picks 3 and 4 belonged to an excluded entry
    choices = {"choices": [
        {"index": 1, "pick": 1, "element": 10, "entry": 100},
        {"index": 2, "pick": 2, "element": 11, "entry": 200},
        {"index": 5, "pick": 1, "element": 12, "entry": 200},
        {"index": 6, "pick": 2, "element": 13, "entry": 100},
    ]}
    players = pd.DataFrame({
        "id": [10, 11, 12, 13], "web_name": list("abcd"), "position": ["MID"] * 4,
        "draft_rank": [1, 2, 3, 4], "now_cost": [5.0] * 4,
        "selected_by_percent": [1.0] * 4, "team": [1] * 4, "team_name": ["ARS"] * 4,
    })
    table = pd.DataFrame({
        "entry_id": [100, 200], "short_name": ["AA", "BB"],
        "first_name": ["A", "B"], "last_name": ["A", "B"],
    })
    picks = draft_picks_table(choices, players, table, league_code="Prem", drafters=2)
    assert picks["index"].tolist() == [1, 2, 3, 4]
    assert picks["round"].tolist() == [1, 1, 2, 2]
    # `pick` is left as the raw within-round position, as the notebook did
    assert picks["pick"].tolist() == [1, 2, 1, 2]


def test_round_size_comes_from_config_not_a_hardcoded_six():
    choices = {"choices": [
        {"index": i + 1, "pick": (i % 3) + 1, "element": 10 + i, "entry": 100 + (i % 3)}
        for i in range(9)
    ]}
    players = pd.DataFrame({
        "id": list(range(10, 19)), "web_name": list("abcdefghi"),
        "position": ["MID"] * 9, "draft_rank": list(range(9)), "now_cost": [5.0] * 9,
        "selected_by_percent": [1.0] * 9, "team": [1] * 9, "team_name": ["ARS"] * 9,
    })
    table = pd.DataFrame({
        "entry_id": [100, 101, 102], "short_name": ["A", "B", "C"],
        "first_name": list("ABC"), "last_name": list("ABC"),
    })
    picks = draft_picks_table(choices, players, table, league_code="Conf", drafters=3)
    assert picks["round"].tolist() == [1, 1, 1, 2, 2, 2, 3, 3, 3]


# --- promotion / relegation gaps -------------------------------------------

def test_league_gaps_use_configured_counts():
    """2 down means the safety line sits at rank 4 in a 6-team league."""
    season = get_season("2526")
    table = pd.DataFrame({
        "league_code": ["Prem"] * 6,
        "short_name": list("ABCDEF"),
        "rank": [1, 2, 3, 4, 5, 6],
        "total": [100, 90, 80, 70, 60, 50],
    })
    gaps = league_gaps(table, season.league("Prem"))
    assert gaps["points_from_top"].tolist() == [0, 10, 20, 30, 40, 50]
    # last safe rank is 4 (6 - 2)
    assert gaps.loc[gaps["rank"] == 6, "points_from_safety"].iloc[0] == 20
    assert gaps.loc[gaps["rank"] == 1, "points_above_relegation"].iloc[0] == 40


def test_league_gaps_handle_2425_three_up_one_down():
    season = get_season("2425")
    table = pd.DataFrame({
        "league_code": ["Conf"] * 7,
        "short_name": list("ABCDEFG"),
        "rank": [1, 2, 3, 4, 5, 6, 7],
        "total": [100, 95, 90, 85, 80, 75, 70],
    })
    gaps = league_gaps(table, season.league("Conf"))
    # 3 promoted, so the promotion line is rank 3
    assert gaps.loc[gaps["rank"] == 4, "points_from_promotion"].iloc[0] == 5
    assert gaps.loc[gaps["rank"] == 1, "points_above_last"].iloc[0] == 30


# --- fixtures from the draft API ------------------------------------------

def test_fixtures_from_live_collapses_double_gameweeks():
    teams = pd.DataFrame({"team": [1, 2, 3], "team_name": ["ARS", "LIV", "MCI"]})
    live = {1: {"fixtures": [
        {"event": 1, "team_h": 1, "team_a": 2, "team_h_score": 2, "team_a_score": 1,
         "kickoff_time": "2025-08-16T14:00:00Z"},
        {"event": 1, "team_h": 3, "team_a": 1, "team_h_score": 0, "team_a_score": 4,
         "kickoff_time": "2025-08-17T14:00:00Z"},
    ]}}
    _, by_team = fixtures_from_live(live, teams)
    arsenal = by_team[by_team["team"] == "ARS"].iloc[0]
    assert arsenal["gameweek_matches"] == 2
    assert arsenal["opposition"] == "LIV-MCI"
    assert arsenal["home_away"] == "HA"
    assert arsenal["team_score"] == pytest.approx(3.0)      # mean of 2 and 4
    # difficulty is unavailable from the draft API
    assert pd.isna(arsenal["team_difficulty"])


# --- league table exclusion ------------------------------------------------

def test_league_table_drops_excluded_entries():
    details = {
        "league_entries": [
            {"entry_id": 1, "entry_name": "Real", "id": 11, "short_name": "aa",
             "player_first_name": "ann", "player_last_name": "smith"},
            {"entry_id": 2, "entry_name": "Dud", "id": 22, "short_name": "pv",
             "player_first_name": "peter", "player_last_name": "vickers"},
        ],
        "standings": [
            {"league_entry": 11, "event_total": 40, "total": 900, "rank": 1, "last_rank": 1},
            {"league_entry": 22, "event_total": 10, "total": 100, "rank": 2, "last_rank": 2},
        ],
    }
    table = league_table(details, league_code="Prem", exclude_entries=(22,))
    assert table["short_name"].tolist() == ["AA"]
    assert table["first_name"].tolist() == ["Ann"]     # capitalised


# --- JSON has no Infinity ---------------------------------------------------

def test_points_scored_share_survives_a_drafter_on_zero():
    """
    GW1 kicked off and the whole site went blank.

    A drafter's league total is 0 until their first fixture is scored, so the
    share of players already banking live points divided by zero. `Infinity` is
    valid Python and invalid JSON, so one such row made weekly_summary.json
    unparseable and every view failed to load.
    """
    scored = pd.Series([9.0, 1.0, 0.0, 5.0])
    totals = pd.Series([30.0, 0.0, 0.0, float("nan")])

    share = points_scored_share(scored, totals)

    assert share[0] == pytest.approx(0.3)   # the ordinary case is untouched
    assert share[1] == 0.0                  # was inf
    assert share[2] == 0.0                  # was nan, from 0/0
    assert pd.isna(share[3])                # a missing total stays missing
    assert np.isfinite(share.dropna()).all()


def test_clean_nulls_non_finite_floats():
    assert _clean(float("inf")) is None
    assert _clean(float("-inf")) is None
    assert _clean(float("nan")) is None
    assert _clean(0.5) == 0.5


def test_dump_refuses_to_write_unparseable_json():
    """
    The backstop for payloads that never pass through `_clean` (meta, review
    facts). Failing the build keeps the last good site live; writing `Infinity`
    would publish a file no browser can read.
    """
    with pytest.raises(ValueError):
        _dump({"pct": float("inf")})
    assert json.loads(_dump({"pct": 0.5})) == {"pct": 0.5}
