"""Weekly talking points: each beat kind on a tiny hand-worked season.

Like test_narrative, the fixture is small enough that every expected beat can be
checked by hand. A quiet week must emit nothing. Nothing touches the network.
"""

import json

import pandas as pd
import pytest

from pipeline.config import League, Season
from pipeline.transforms.beats import weekly_beats

SEASON = Season(
    season="9900", label="1999/00", total_gameweeks=5, default_source="csv",
    leagues=(League(code="L1", name="League One", league_code=None, size=3),),
)

# Five gameweeks, worked by hand:
#   GW2  B takes the lead from A.
#   GW3  C takes it from B, climbing 3rd -> 1st (a rank swing); C's 80 is a new
#        season high.
#   GW4  quiet.
#   GW5  A's 2 is a new season low AND ~29 below A's own average (outlier).
SCORES = {
    "AA": [50, 20, 30, 25, 2],
    "BB": [40, 45, 30, 35, 36],
    "CC": [30, 25, 80, 30, 31],
}


def build_by_week(scores, league="L1"):
    rows = [{"league_code": league, "short_name": short, "gameweek": gameweek,
             "points_scored": value}
            for short, series in scores.items()
            for gameweek, value in enumerate(series, start=1)]
    frame = pd.DataFrame(rows)
    frame["cumulative_points"] = (
        frame.groupby(["league_code", "short_name"])["points_scored"].cumsum())
    frame["gameweek_rank"] = (
        frame.groupby(["league_code", "gameweek"])["cumulative_points"]
        .rank(method="min", ascending=False).astype(int))
    frame["previous_gameweek_rank"] = (
        frame.groupby(["league_code", "short_name"])["gameweek_rank"]
        .shift(1).fillna(0).astype(int))
    return frame


def league_table(scores, league="L1"):
    return pd.DataFrame([{"league_code": league, "short_name": short,
                          "name": f"Name {short}"} for short in scores])


def summary_with_bench_pain():
    """Optimal equals scored everywhere except AA's GW2, which cost exactly 10."""
    rows = []
    for short, series in SCORES.items():
        for gameweek, value in enumerate(series, start=1):
            optimal = value + 10 if (short == "AA" and gameweek == 2) else value
            rows.append({"league_code": "L1", "short_name": short,
                         "gameweek": gameweek, "points_scored": value,
                         "optimal_points": optimal})
    return pd.DataFrame(rows)


def transfers():
    net = "net_points_of_transfer_in_week"
    return pd.DataFrame([
        {"league_code": "L1", "gameweek": 4, "short_name": "BB", "kind": "waiver",
         "result": "successful", "player_in": "Hauler", "player_out": "Dud", net: 12},
        {"league_code": "L1", "gameweek": 4, "short_name": "AA", "kind": "waiver",
         "result": "successful", "player_in": "Meh", "player_out": "Shrug", net: 5},
        {"league_code": "L1", "gameweek": 4, "short_name": "CC", "kind": "waiver",
         "result": "unsuccessful - player in already been picked up",
         "player_in": "Hauler", "player_out": "Dud", net: 50},
    ])


def trades():
    return pd.DataFrame([
        {"league_code": "L1", "gameweek": 3, "state": "p", "offered_by": "AA",
         "received_by": "BB", "player_in": "Swap1", "player_out": "Swap2"},
        {"league_code": "L1", "gameweek": 3, "state": "o", "offered_by": "AA",
         "received_by": "BB", "player_in": "Never", "player_out": "Happened"},
        {"league_code": "L1", "gameweek": 3, "state": "p", "offered_by": "AA",
         "received_by": "99999", "player_in": "Dud", "player_out": "Gift"},
    ])


@pytest.fixture(scope="module")
def beats():
    return weekly_beats(
        season=SEASON, league_table=league_table(SCORES),
        league_table_by_week=build_by_week(SCORES),
        weekly_summary=summary_with_bench_pain(),
        transfers=transfers(), trades=trades(), h2h_matches=None,
    )


def of_kind(beats, kind):
    return [b for b in beats if b["kind"] == kind]


def test_lead_changes_name_both_drafters(beats):
    changes = of_kind(beats, "lead_change")
    assert [(b["gameweek"], b["data"]["new"]["short_name"],
             b["data"]["previous"]["short_name"]) for b in changes] == [
        (2, "BB", "AA"), (3, "CC", "BB")]


def test_season_high_and_low_need_history_to_beat(beats):
    highs = of_kind(beats, "season_high")
    lows = of_kind(beats, "season_low")
    assert [(b["gameweek"], b["data"]["short_name"], b["data"]["points"])
            for b in highs] == [(3, "CC", 80)]
    # AA's 20 undercuts GW1's floor, then their 2 undercuts that.
    assert [(b["gameweek"], b["data"]["short_name"], b["data"]["points"])
            for b in lows] == [(2, "AA", 20), (5, "AA", 2)]


def test_a_personal_outlier_measures_against_their_own_average(beats):
    outliers = of_kind(beats, "personal_outlier")
    assert len(outliers) == 1
    beat = outliers[0]
    assert (beat["gameweek"], beat["data"]["short_name"]) == (5, "AA")
    assert beat["data"]["direction"] == "below"
    # AA's prior mean is exactly 31.25; round(…, 1) banker-rounds it to 31.2.
    assert beat["data"]["average"] == pytest.approx(31.25, abs=0.06)


def test_a_rank_swing_needs_two_places(beats):
    swings = of_kind(beats, "rank_swing")
    assert [(b["gameweek"], b["data"]["short_name"], b["data"]["from"], b["data"]["to"])
            for b in swings] == [(3, "CC", 3, 1)]


def test_bench_pain_fires_at_the_threshold_only(beats):
    pain = of_kind(beats, "bench_pain")
    assert [(b["gameweek"], b["data"]["short_name"], b["data"]["points_lost"])
            for b in pain] == [(2, "AA", 10)]


def test_the_best_transfer_of_the_week_must_clear_the_bar(beats):
    moves = of_kind(beats, "instant_transfer")
    assert len(moves) == 1
    data = moves[0]["data"]
    assert (moves[0]["gameweek"], data["short_name"], data["net_points"]) == (4, "BB", 12)


def test_only_processed_competitive_trades_are_beats(beats):
    swaps = of_kind(beats, "trade_executed")
    assert len(swaps) == 1                     # not the offer, not the excluded entry
    assert swaps[0]["data"]["received_by"]["short_name"] == "BB"


def test_a_quiet_week_emits_nothing(beats):
    assert [b for b in beats if b["gameweek"] == 4 and b["kind"] != "instant_transfer"] == []


def test_h2h_upsets_use_the_table_going_in():
    scores = {"AA": [40, 10], "BB": [30, 10], "CC": [20, 10], "DD": [10, 50]}
    matches = pd.DataFrame([{
        "league_code": "L1", "gameweek": 2, "home": "DD", "away": "AA",
        "home_points": 50, "away_points": 10, "started": True, "finished": True,
        "result": "W", "winner": "DD",
    }])
    season = Season(season="9900", label="1999/00", total_gameweeks=2,
                    default_source="csv",
                    leagues=(League(code="L1", name="League One",
                                    league_code=None, size=4),))
    beats = weekly_beats(
        season=season, league_table=league_table(scores),
        league_table_by_week=build_by_week(scores),
        weekly_summary=pd.DataFrame(), transfers=pd.DataFrame(),
        trades=pd.DataFrame(), h2h_matches=matches,
    )
    upsets = of_kind(beats, "h2h_upset")
    assert len(upsets) == 1
    data = upsets[0]["data"]
    assert data["winner"]["short_name"] == "DD"
    assert (data["winner_rank"], data["loser_rank"]) == (4, 1)
    assert data["provisional"] is False


def test_beats_are_json_serialisable(beats):
    assert isinstance(json.loads(json.dumps(beats, allow_nan=False)), list)
