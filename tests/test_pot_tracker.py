"""The Dunelmliga side pot: month mapping, settling, ties and the running total.

The rule is a group convention, not an FPL one: £20 buy-in each, then the lowest
scorer over each calendar month's gameweeks (by deadline date) adds £10. A month
only settles once every one of its gameweeks is finalised. Nothing here touches
the network.
"""

import json

import pandas as pd
import pytest

from pipeline.config import League, PotRules
from pipeline.transforms.pot import gameweek_calendar, pot_tracker


def event(gameweek, deadline, finished=True, checked=True):
    return {"id": gameweek, "deadline_time": deadline,
            "finished": finished, "data_checked": checked}


# August: GW1-2, both finalised. September: GW3 finalised, GW4 finished but not
# yet data-checked (bonus pending). October: GW5 not played.
EVENTS = {"events": {"data": [
    event(1, "2026-08-15T10:00:00Z"),
    event(2, "2026-08-22T10:00:00Z"),
    event(3, "2026-09-05T10:00:00Z"),
    event(4, "2026-09-19T10:00:00Z", finished=True, checked=False),
    event(5, "2026-10-03T10:00:00Z", finished=False, checked=False),
]}}

# August sums: AA 80, BB 75, CC 65 -> CC pays. September so far: AA 80, BB 65, CC 85.
POINTS = {
    (1, "AA"): 50, (1, "BB"): 40, (1, "CC"): 45,
    (2, "AA"): 30, (2, "BB"): 35, (2, "CC"): 20,
    (3, "AA"): 10, (3, "BB"): 60, (3, "CC"): 55,
    (4, "AA"): 70, (4, "BB"): 5, (4, "CC"): 30,
}


def by_week(points=POINTS):
    return pd.DataFrame([
        {"league_code": "DL", "short_name": short, "gameweek": gameweek,
         "points_scored": value}
        for (gameweek, short), value in points.items()
    ])


LEAGUE = League(code="DL", name="Dunelmliga", league_code=1, size=3, pot=PotRules())
NO_POT = League(code="Conf", name="Conference", league_code=2, size=6)


@pytest.fixture
def pot():
    return pot_tracker(by_week(), gameweek_calendar(EVENTS), LEAGUE)


def month(pot, key):
    return next(m for m in pot["months"] if m["month"] == key)


# --- the gameweek calendar ---------------------------------------------------

def test_gameweeks_map_to_months_by_deadline_date():
    cal = gameweek_calendar(EVENTS)
    assert list(cal["gameweek"]) == [1, 2, 3, 4, 5]
    assert list(cal["month"]) == ["2026-08", "2026-08", "2026-09", "2026-09", "2026-10"]


def test_finalised_needs_finished_and_data_checked():
    cal = gameweek_calendar(EVENTS).set_index("gameweek")
    assert bool(cal.loc[3, "finalised"]) is True
    assert bool(cal.loc[4, "finalised"]) is False     # bonus still pending
    assert bool(cal.loc[5, "finalised"]) is False


def test_an_empty_bootstrap_yields_an_empty_calendar():
    assert len(gameweek_calendar({})) == 0
    assert len(gameweek_calendar({"events": []})) == 0


# --- the pot -----------------------------------------------------------------

def test_a_league_without_the_rule_gets_nothing():
    assert pot_tracker(by_week(), gameweek_calendar(EVENTS), NO_POT) is None


def test_a_settled_month_names_its_loser(pot):
    august = month(pot, "2026-08")
    assert august["label"] == "August 2026"
    assert august["gameweeks"] == [1, 2]
    assert august["points"] == {"AA": 80, "BB": 75, "CC": 65}
    assert august["settled"] is True
    assert august["losers"] == ["CC"]
    assert august["tied"] is False


def test_an_unfinalised_gameweek_leaves_the_month_open(pot):
    september = month(pot, "2026-09")
    assert september["settled"] is False
    assert september["losers"] == []
    # The running scores still show, so "loser if the month ended today" works.
    assert september["points"] == {"AA": 80, "BB": 65, "CC": 85}


def test_a_future_month_is_an_upcoming_row(pot):
    october = month(pot, "2026-10")
    assert october["points"] == {}
    assert october["settled"] is False


def test_the_pot_counts_buy_ins_plus_settled_stakes(pot):
    assert pot["settled_months"] == 1
    assert pot["pot_total"] == 3 * 20 + 1 * 10
    assert pot["rules"] == {"buy_in": 20, "monthly_stake": 10, "currency": "£"}
    assert pot["drafters"] == ["AA", "BB", "CC"]


def test_a_tie_for_last_lists_everyone_and_still_takes_one_stake():
    tied = dict(POINTS)
    tied[(1, "AA")], tied[(2, "AA")] = 30, 35       # AA now 65, level with CC
    pot = pot_tracker(by_week(tied), gameweek_calendar(EVENTS), LEAGUE)
    august = month(pot, "2026-08")

    assert august["losers"] == ["AA", "CC"]
    assert august["tied"] is True
    assert pot["settled_months"] == 1               # one stake, settled offline
    assert pot["pot_total"] == 3 * 20 + 10


def test_the_payload_is_json_serialisable(pot):
    assert json.loads(json.dumps(pot, allow_nan=False))["league"] == "DL"
