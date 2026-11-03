"""Per-player points breakdowns, read from the explain arrays in event/live.

The squads view shows what a score was made of; only owned players (those in
that gameweek's weekly_summary) are emitted, and a double gameweek yields one
entry per fixture. Nothing here touches the network.
"""

import json

import pandas as pd

from pipeline.transforms.breakdown import points_breakdown


def minutes(points, value):
    return {"name": "Minutes played", "points": points, "value": value, "stat": "minutes"}


def goal(points=4):
    return {"name": "Goals scored", "points": points, "value": 1, "stat": "goals_scored"}


LIVE = {
    1: {"elements": {
        # Owned, one fixture: 2 + 4 = 6.
        "10": {"explain": [[[minutes(2, 90), goal()], 7]], "stats": {"total_points": 6}},
        # Owned but blank explain (didn't feature) — omitted.
        "11": {"explain": [], "stats": {"total_points": 0}},
        # Not owned by anyone that week — omitted however well he scored.
        "99": {"explain": [[[minutes(2, 90), goal(8)], 7]], "stats": {"total_points": 10}},
    }},
    2: {"elements": {
        # A double gameweek: two [items, fixture] entries, own subtotals.
        "10": {"explain": [[[minutes(2, 90)], 20], [[minutes(1, 45), goal()], 21]],
               "stats": {"total_points": 7}},
    }},
}


def summary():
    return pd.DataFrame([
        {"gameweek": 1, "element": 10},
        {"gameweek": 1, "element": 11},
        {"gameweek": 2, "element": 10},
    ])


def test_only_owned_players_are_emitted():
    out = points_breakdown(LIVE, summary())
    assert [r["element"] for r in out[1]] == [10]    # 99 unowned, 11 blank


def test_fixture_totals_sum_the_stat_lines():
    record = points_breakdown(LIVE, summary())[1][0]
    fixture = record["fixtures"][0]
    assert fixture["fixture"] == 7
    assert fixture["total"] == 6
    assert [item["stat"] for item in fixture["items"]] == ["minutes", "goals_scored"]
    assert fixture["items"][1]["value"] == 1


def test_a_double_gameweek_keeps_one_entry_per_fixture():
    record = points_breakdown(LIVE, summary())[2][0]
    assert [f["fixture"] for f in record["fixtures"]] == [20, 21]
    assert [f["total"] for f in record["fixtures"]] == [2, 5]
    assert sum(f["total"] for f in record["fixtures"]) == 7   # matches stats.total_points


def test_empty_inputs_come_back_empty():
    assert points_breakdown({}, summary()) == {}
    assert points_breakdown(LIVE, pd.DataFrame()) == {}
    assert points_breakdown({1: {"elements": {}}}, summary()) == {}


def test_the_output_is_strict_json_safe():
    out = points_breakdown(LIVE, summary())
    assert json.loads(json.dumps(out[1], allow_nan=False))[0]["element"] == 10
