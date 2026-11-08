"""A gameweek still being played: what the build says about it, and what it withholds.

Mid-gameweek the site updates every few minutes, but some figures cannot exist
yet — auto-subs happen at the final whistle of the last match, so the optimal
XI and the "points left on the bench" are measured against players who have
not kicked off. The pipeline marks the week in meta, carries who has played,
and keeps the week out of the season trends until it settles.
"""

import pandas as pd

from pipeline.build import _live_gameweek
from pipeline.transforms.weekly import _fixture_state, _points_frame


# --- which week is live -----------------------------------------------------

def test_an_open_gameweek_is_live():
    assert _live_gameweek({"current_event": 11, "current_event_finished": False}, 11) == 11


def test_a_finished_gameweek_is_not_live_even_while_it_is_current():
    # Between gameweeks current_event stays put with the finished flag set.
    assert _live_gameweek({"current_event": 11, "current_event_finished": True}, 11) is None


def test_the_archives_payload_is_never_live():
    # The 2526 snapshot: GW38 done, and a payload that omits the flag altogether.
    assert _live_gameweek({"current_event": 38, "current_event_finished": True,
                           "next_event": None}, 38) is None
    assert _live_gameweek({"current_event": 38}, 38) is None
    assert _live_gameweek({}, 38) is None


def test_live_needs_the_current_event_to_be_the_week_built():
    # A forced gameweek count other than the API's current week is a rebuild.
    assert _live_gameweek({"current_event": 11, "current_event_finished": False}, 9) is None
    assert _live_gameweek({"current_event": 11, "current_event_finished": False}, 0) is None


# --- who has played ---------------------------------------------------------

LIVE = {
    3: {
        "elements": {
            "1": {"stats": {"total_points": 6, "minutes": 90}},
            "2": {"stats": {"total_points": 0, "minutes": 0}},
            "3": {"stats": {"total_points": 2}},            # no minutes key
        },
        "fixtures": [
            {"team_h": 10, "team_a": 20, "finished": True, "finished_provisional": True},
            {"team_h": 30, "team_a": 40, "finished": False, "finished_provisional": True},
            {"team_h": 50, "team_a": 60, "started": True, "finished": False,
             "finished_provisional": False},
            {"team_h": 10, "team_a": 70, "finished": False, "finished_provisional": False},
        ],
    },
    4: {"elements": {"1": {"stats": {"total_points": 1, "minutes": 10}}}},   # no fixture list
}


def test_minutes_ride_along_with_the_points():
    frame = _points_frame(LIVE, "L1").set_index(["gameweek", "id"])
    assert frame.loc[(3, 1), "minutes"] == 90
    assert frame.loc[(3, 2), "minutes"] == 0
    assert pd.isna(frame.loc[(3, 3), "minutes"])
    assert frame.loc[(4, 1), "minutes"] == 10


def test_a_club_is_finished_only_when_every_match_that_week_is():
    state, known = _fixture_state(LIVE)
    done = state.set_index(["gameweek", "team_id"])["fixture_finished"].to_dict()
    assert done[(3, 20)] is True                 # one match, over
    assert done[(3, 30)] is True                 # full time counts, before the bonus is confirmed
    assert done[(3, 50)] is False                # in play
    assert done[(3, 10)] is False                # a double: one done, one not
    assert done[(3, 70)] is False
    # GW4's payload had no fixture list, so it says nothing about anyone.
    assert known == {3}
    assert not (state["gameweek"] == 4).any()
