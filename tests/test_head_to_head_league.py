"""A league played as weekly fixtures rather than on points banked.

FPL calls this `scoring: 'h'`. Dunelmliga is one; both WOD leagues are classic.
The official table is what the league is actually won on, so it has to be right —
and it cannot simply be read off the API, because `standings` only moves once a
gameweek has finished. Before the first result it is all zeroes with a null rank,
and mid-gameweek it is still last week's table.

Nothing here touches the network.
"""

import pytest

from pipeline.transforms.league import (
    head_to_head_matches,
    head_to_head_table,
    is_head_to_head,
    league_table,
    reconcile_head_to_head,
)

ENTRIES = [
    {"entry_id": 1, "entry_name": "A FC", "id": 101, "short_name": "aa",
     "player_first_name": "ann", "player_last_name": "adams"},
    {"entry_id": 2, "entry_name": "B FC", "id": 102, "short_name": "bb",
     "player_first_name": "ben", "player_last_name": "brown"},
    {"entry_id": 3, "entry_name": "C FC", "id": 103, "short_name": "cc",
     "player_first_name": "cai", "player_last_name": "clark"},
    {"entry_id": 4, "entry_name": "D FC", "id": 104, "short_name": "dd",
     "player_first_name": "dee", "player_last_name": "dunn"},
]


def match(event, home, away, home_points, away_points, *, started=True, finished=True):
    return {"event": event, "league_entry_1": home, "league_entry_2": away,
            "league_entry_1_points": home_points, "league_entry_2_points": away_points,
            "started": started, "finished": finished,
            "winning_league_entry": None, "winning_method": None}


# GW1   AA 50-40 BB (AA win)     CC 30-30 DD (draw)
# GW2   AA 20-60 CC (CC win)     BB 45-45 DD (draw)
# GW3   published, not yet played
MATCHES = [
    match(1, 101, 102, 50, 40),
    match(1, 103, 104, 30, 30),
    match(2, 101, 103, 20, 60),
    match(2, 102, 104, 45, 45),
    match(3, 101, 104, 0, 0, started=False, finished=False),
    match(3, 102, 103, 0, 0, started=False, finished=False),
]


def details(scoring="h", matches=None, standings=None):
    return {
        "league": {"scoring": scoring},
        "league_entries": ENTRIES,
        "standings": standings if standings is not None else [],
        "matches": MATCHES if matches is None else matches,
    }


@pytest.fixture
def standings():
    return league_table(details(), league_code="DL")


def table_at(standings, gameweek, matches=None):
    fixtures = head_to_head_matches(details(matches=matches), standings, league_code="DL")
    table, _ = head_to_head_table(fixtures, standings,
                                  league_code="DL", current_week=gameweek)
    return table.set_index("short_name")


def test_the_scoring_mode_is_read_from_the_payload():
    assert is_head_to_head(details(scoring="h")) is True
    assert is_head_to_head(details(scoring="c")) is False
    assert is_head_to_head({}) is False        # a CSV archive has no payload at all


def test_fixtures_are_named_and_scored(standings):
    fixtures = head_to_head_matches(details(), standings, league_code="DL")

    assert len(fixtures) == 6
    won = fixtures[(fixtures["gameweek"] == 1) & (fixtures["home"] == "AA")].iloc[0]
    assert (won["away"], won["home_points"], won["away_points"]) == ("BB", 50, 40)
    assert (won["result"], won["winner"]) == ("W", "AA")

    drawn = fixtures[(fixtures["gameweek"] == 1) & (fixtures["home"] == "CC")].iloc[0]
    assert drawn["result"] == "D"
    assert drawn["winner"] is None


def test_an_unplayed_fixture_has_no_result(standings):
    """The whole 38-week fixture list ships up front, so most of it hasn't happened."""
    fixtures = head_to_head_matches(details(), standings, league_code="DL")
    future = fixtures[fixtures["gameweek"] == 3]

    assert len(future) == 2
    assert future["result"].isna().all()
    assert not future["started"].any()


def test_the_table_counts_three_for_a_win_and_one_for_a_draw(standings):
    rows = table_at(standings, 2)
    record = ["played", "won", "drawn", "lost", "h2h_points"]

    assert list(rows.loc["AA", record]) == [2, 1, 0, 1, 3]   # beat BB, lost to CC
    assert list(rows.loc["CC", record]) == [2, 1, 1, 0, 4]   # drew DD, beat AA
    assert list(rows.loc["DD", record]) == [2, 0, 2, 0, 2]   # two draws
    assert list(rows.loc["BB", record]) == [2, 0, 1, 1, 1]   # lost to AA, drew DD


def test_points_for_and_against_are_the_scores_not_the_league_points(standings):
    rows = table_at(standings, 2)

    assert rows.loc["AA", "points_for"] == 70          # 50 + 20
    assert rows.loc["AA", "points_against"] == 100     # 40 + 60


def test_a_tie_on_points_is_broken_by_points_scored(standings):
    """FPL separates equal records on points scored, so the table has to as well."""
    rows = table_at(standings, 2).sort_values("rank")

    assert list(rows.index) == ["CC", "AA", "DD", "BB"]
    assert list(rows["rank"]) == [1, 2, 3, 4]
    assert list(rows["h2h_points"]) == [4, 3, 2, 1]


def test_the_table_can_be_asked_for_an_earlier_gameweek(standings):
    """The gameweek view can be pointed at any week, not just the latest."""
    rows = table_at(standings, 1)

    assert rows.loc["AA", "played"] == 1
    assert rows.loc["AA", "h2h_points"] == 3
    # Nothing behind GW1, so nobody has a previous position to have moved from.
    assert (rows["last_rank"] == 0).all()


def test_last_rank_is_where_the_table_stood_a_week_ago(standings):
    rows = table_at(standings, 2)

    # After GW1 only AA had won and only BB had lost.
    assert rows.loc["AA", "last_rank"] == 1
    assert rows.loc["BB", "last_rank"] == 4


def test_an_unfinished_gameweek_is_marked_provisional(standings):
    """
    Bonus points can still move a result, so the site has to say it is ahead of
    the official table rather than quietly disagreeing with it.
    """
    live = [match(1, 101, 102, 50, 40, started=True, finished=False),
            match(1, 103, 104, 30, 30, started=True, finished=False)]

    assert table_at(standings, 1, matches=live)["provisional"].all()


def test_a_settled_table_is_not_provisional(standings):
    assert not table_at(standings, 2)["provisional"].any()


def test_a_classic_league_produces_no_fixtures(standings):
    """Every WOD league. The payload has no `matches` key at all."""
    payload = {"league": {"scoring": "c"}, "league_entries": ENTRIES, "standings": []}
    fixtures = head_to_head_matches(payload, standings, league_code="Conf")

    assert len(fixtures) == 0
    assert list(fixtures.columns) == [
        "gameweek", "league_code", "home", "away", "home_points", "away_points",
        "started", "finished", "result", "winner",
    ]


# --- reconciliation --------------------------------------------------------
# 3 / 1 / 0 is FPL's documented rule, not something the payload states. These
# guard the check that would catch it being wrong the moment there is a settled
# table to compare against.

def api_standings(**overrides):
    rows = {
        101: {"league_entry": 101, "matches_played": 2, "matches_won": 1,
              "matches_drawn": 0, "points_for": 70, "total": 3},
        102: {"league_entry": 102, "matches_played": 2, "matches_won": 0,
              "matches_drawn": 1, "points_for": 85, "total": 1},
        103: {"league_entry": 103, "matches_played": 2, "matches_won": 1,
              "matches_drawn": 1, "points_for": 90, "total": 4},
        104: {"league_entry": 104, "matches_played": 2, "matches_won": 0,
              "matches_drawn": 2, "points_for": 75, "total": 2},
    }
    for entry, changes in overrides.items():
        rows[int(entry)].update(changes)
    return list(rows.values())


def reconcile(standings, official, matches=None):
    fixtures = head_to_head_matches(details(matches=matches), standings, league_code="DL")
    table, _ = head_to_head_table(fixtures, standings, league_code="DL", current_week=2)
    return reconcile_head_to_head(table, details(standings=official), standings)


def test_the_rebuilt_table_agrees_with_the_api(standings):
    assert reconcile(standings, api_standings()) == []


def test_a_disagreement_is_reported(standings):
    """If FPL ever awarded something other than 3/1/0, this is what would catch it."""
    notes = reconcile(standings, api_standings(**{"101": {"total": 2}}))

    assert len(notes) == 1
    assert "AA" in notes[0] and "h2h_points=3" in notes[0]


def test_nothing_to_check_against_yet_is_not_a_disagreement(standings):
    """Before the first gameweek settles, the API's own table is all zeroes."""
    blank = [{"league_entry": e["id"], "matches_played": 0, "matches_won": 0,
              "matches_drawn": 0, "points_for": 0, "total": 0} for e in ENTRIES]

    assert reconcile(standings, blank) == []


def test_a_provisional_row_is_not_compared(standings):
    """The API counts finished matches only, so being ahead of it is expected."""
    live = MATCHES[:2] + [match(2, 101, 103, 20, 60, started=True, finished=False),
                          match(2, 102, 104, 45, 45, started=True, finished=False)]

    assert reconcile(standings, api_standings(), matches=live) == []
