"""A season that exists but has not kicked off.

The leagues are created weeks before GW1, and draft night lands in the middle of
that gap. Three stages have to work, in order:

  pre_draft   leagues and drafters exist, nothing has been picked
  drafted     picks exist, still no gameweeks
  live        GW1 has opened; the normal build takes over

This window broke the build once already: filling in the 2627 league codes let the
current-season build run for the first time, and it died on `standings: []`. The
API answers with empty lists, not errors, so every transform in the path has to
treat "empty" as a real answer.

Nothing here touches the network.
"""

import json

import pandas as pd
import pytest

from pipeline import outputs, schedule
from pipeline.build import _current_week
from pipeline.config import get_season
from pipeline.schedule import MINIMUM_INTERVAL, decide
from pipeline.transforms import draft_picks_table, league_table

# Two drafters, shaped like the real league details payload.
DETAILS = {
    "league": {"id": 19116, "name": "What's on Draft? Conference"},
    "league_entries": [
        {"entry_id": 168968, "entry_name": "Chronic wAIvering", "id": 169773,
         "short_name": "mn", "player_first_name": "mike", "player_last_name": "nelson"},
        {"entry_id": 96854, "entry_name": "Prem Outcasterisk*", "id": 97121,
         "short_name": "pv", "player_first_name": "peter", "player_last_name": "vickers"},
    ],
    "standings": [],
}


class FakeGame:
    """Just the bit of the source that _current_week reads."""

    def __init__(self, **game):
        self._game = game

    def game(self):
        return self._game


# --- the gameweek count ----------------------------------------------------

def test_no_current_gameweek_before_the_season_starts():
    """
    Zero, not 38. The old fallback assumed a missing current_event meant a finished
    archive, so a pre-season build fetched 38 empty live payloads and 404ed every
    entry/gameweek pair.
    """
    season = get_season("2627")
    assert _current_week(FakeGame(current_event=None, next_event=1), season) == 0


def test_finished_season_still_falls_back_to_the_full_season():
    """The 2526 snapshot reports GW38 done with no next event."""
    season = get_season("2526")
    assert _current_week(FakeGame(current_event=38, next_event=None), season) == 38
    # a payload that omits the field entirely is still treated as a full season
    assert _current_week(FakeGame(), season) == season.total_gameweeks


def test_open_gameweek_wins_over_everything():
    assert _current_week(FakeGame(current_event=3, next_event=4), get_season("2627")) == 3


# --- empty payloads are real answers --------------------------------------

def test_league_table_survives_empty_standings():
    """
    The crash that took the build down. json_normalize([]) has no columns, so
    selecting them raised KeyError. The drafters exist, so report them at zero.
    """
    table = league_table(DETAILS, league_code="Conf")

    assert len(table) == 2
    assert set(table["short_name"]) == {"MN", "PV"}
    assert table["first_name"].tolist() == ["Mike", "Peter"]   # still capitalised
    assert table["total"].tolist() == [0, 0]
    assert table["rank"].tolist() == [0, 0]
    assert set(table["league_code"]) == {"Conf"}


def test_league_table_still_excludes_entries_when_standings_are_empty():
    table = league_table(DETAILS, league_code="Conf", exclude_entries=(97121,))
    assert table["short_name"].tolist() == ["MN"]


def test_draft_picks_table_survives_empty_choices():
    """Before draft night: no picks, but the frame must keep its shape so the
    per-league concat downstream still lines up."""
    picks = draft_picks_table({"choices": [], "element_status": []},
                              pd.DataFrame(), pd.DataFrame(),
                              league_code="Conf", drafters=6)

    assert len(picks) == 0
    assert "element" in picks.columns and "round" in picks.columns


# --- the gate -------------------------------------------------------------

def stub_game(monkeypatch, **game):
    monkeypatch.setattr(schedule, "get_json",
                        lambda url, **kwargs: [] if "fixtures" in url else game)


def test_pre_season_is_its_own_state(monkeypatch):
    """
    Distinct from off_season, which means the season is *over*. Conflating them
    gave the pre-season a 7-day interval — long enough to hide draft night for a
    week.
    """
    stub_game(monkeypatch, current_event=None, current_event_finished=False, next_event=1)
    result = decide("2627", force=True)

    assert result["state"] == "pre_season"
    assert result["should_build"] is True
    assert result["season_ready"] is True      # there IS something to write now
    assert MINIMUM_INTERVAL["pre_season"] < MINIMUM_INTERVAL["off_season"]


def test_finished_season_is_still_off_season(monkeypatch):
    stub_game(monkeypatch, current_event=38, current_event_finished=True, next_event=None)
    assert decide("2526", force=True)["state"] == "off_season"


# --- what gets written ----------------------------------------------------

def preseason_tables(stage_picks):
    return {
        "season": get_season("2627"),
        "current_week": 0,
        "stage": "drafted" if len(stage_picks) else "pre_draft",
        "teams": pd.DataFrame([{"team_id": 1, "team": "Arsenal"}]),
        "players": pd.DataFrame([{"id": 1, "web_name": "Saka", "now_cost": 95}]),
        "standings": league_table(DETAILS, league_code="Conf"),
        "draft_picks": stage_picks,
    }


def test_pre_draft_season_writes_names_and_nothing_else(tmp_path):
    out = outputs.write_season(preseason_tables(pd.DataFrame()), out_dir=str(tmp_path / "2627"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))

    assert meta["stage"] == "pre_draft"
    assert meta["current_gameweek"] == 0
    assert meta["gameweeks"] == []
    assert meta["complete"] is False
    # the one thing the user should see at this stage: who is in which league
    assert [lg["name"] for lg in meta["leagues"]] == ["Premiership", "Conference"]
    assert {d["name"] for d in meta["drafters"]} == {"Mike Nelson", "Peter Vickers"}
    # nothing gameweek-derived claims to be available
    assert meta["capabilities"]["cumulative"] is False
    assert meta["capabilities"]["optimal_points"] is False
    assert json.loads((out / "weekly_summary.json").read_text(encoding="utf-8")) == []


def test_drafted_season_publishes_the_picks(tmp_path):
    picks = pd.DataFrame([{
        "element": 1, "short_name": "MN", "index": 1, "pick": 1, "round": 1,
        "web_name": "Saka", "league_code": "Conf", "position": "MID",
    }])
    out = outputs.write_season(preseason_tables(picks), out_dir=str(tmp_path / "2627"))

    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    written = json.loads((out / "draft_picks.json").read_text(encoding="utf-8"))

    assert meta["stage"] == "drafted"
    assert len(written) == 1
    assert written[0]["web_name"] == "Saka"
    # not yet earned anything — the column exists but is honestly empty
    assert written[0]["total_points"] is None


def test_a_season_with_no_data_is_not_the_landing_page(tmp_path):
    """
    2627 appears in the selector the moment its leagues exist, but opening the site
    on its holding screen would bury 2526's completed season for weeks.
    """
    for season, stage in (("2526", "live"), ("2627", "pre_draft")):
        directory = tmp_path / season
        directory.mkdir()
        (directory / "meta.json").write_text(json.dumps({
            "season": season, "label": season, "stage": stage,
            "current_gameweek": 38 if stage == "live" else 0,
            "complete": stage == "live",
        }), encoding="utf-8")

    payload = json.loads(
        outputs.write_seasons_index(tmp_path).read_text(encoding="utf-8"))

    assert [s["season"] for s in payload["seasons"]] == ["2627", "2526"]  # both listed
    assert payload["default"] == "2526"                                  # but land here
