"""Last season's record attached to each draft pick.

The draft-night view wants four things about a drafted footballer that draft night
itself doesn't know: what he scored last season, what he cost, whether he is new to
the Premier League, and whether he has changed club. Only the cost is already in
the pick table.

Two identifiers are involved and both are traps, which is what these tests are
really guarding:

  element   reassigned every season. Of the 19 ids in both the 2425 and 2526
            drafts, none is the same footballer.
  web_name  stable *within* a season, but FPL only disambiguates with an initial
            when names collide, so a player's web_name changes when his rivals
            do — Mateus Fernandes was `M.Fernandes` (WHU) in 2526 and plain
            `Fernandes` (TOT) in 2627.

So points and debut status come from this season's own bootstrap (which serves last
season's totals in the pre-season window) and only the old club is name-joined.

Nothing here touches the network.
"""

import pandas as pd

from pipeline.transforms import attach_prior_season

# This season's player table, as build.py holds it in memory: keyed on `id`, with
# `minutes` and `total_points` still describing last season, which is what the
# draft bootstrap serves before GW1 opens.
PLAYERS = pd.DataFrame([
    {"id": 1, "web_name": "Haaland", "minutes": 2953, "total_points": 239},
    {"id": 2, "web_name": "Fernandes", "minutes": 3017, "total_points": 135},
    {"id": 3, "web_name": "Rashford", "minutes": 0, "total_points": 0},
    {"id": 4, "web_name": "Palestra", "minutes": 0, "total_points": 0},
    {"id": 5, "web_name": "Rogers", "minutes": 2600, "total_points": 169},
])

PICKS = pd.DataFrame([
    {"element": 1, "web_name": "Haaland", "team_name": "MCI", "short_name": "MN"},
    {"element": 2, "web_name": "Fernandes", "team_name": "TOT", "short_name": "MN"},
    {"element": 3, "web_name": "Rashford", "team_name": "MUN", "short_name": "LD"},
    {"element": 4, "web_name": "Palestra", "team_name": "CHE", "short_name": "LD"},
    {"element": 5, "web_name": "Rogers", "team_name": "CHE", "short_name": "PV"},
])

# Last season. Note Mateus Fernandes is here under the name he had *then*, and
# Palestra is absent because he had not played in the league.
PRIOR = pd.DataFrame([
    {"web_name": "Haaland", "team_name": "MCI", "total_points": 239},
    {"web_name": "M.Fernandes", "team_name": "WHU", "total_points": 135},
    {"web_name": "Rashford", "team_name": "MUN", "total_points": 0},
    {"web_name": "Rogers", "team_name": "AVL", "total_points": 169},
])


def attached():
    return attach_prior_season(PICKS, PLAYERS, PRIOR).set_index("web_name")


def test_row_count_is_preserved():
    """A duplicate name in either table would fan the merge out and invent picks."""
    assert len(attach_prior_season(PICKS, PLAYERS, PRIOR)) == len(PICKS)


def test_prior_points_come_from_this_seasons_bootstrap():
    """Not from the name join, so a renamed player keeps his points."""
    frame = attached()
    assert frame.loc["Haaland", "prior_points"] == 239
    assert frame.loc["Fernandes", "prior_points"] == 135


def test_renamed_player_is_not_called_a_debutant():
    """
    The regression this whole design exists for. Mateus Fernandes doesn't match by
    name, and a join-only implementation called a 135-point player new to the league.
    """
    frame = attached()
    assert not frame.loc["Fernandes", "new_to_pl"]
    assert frame.loc["Fernandes", "prior_points"] == 135


def test_unmatched_name_leaves_moved_club_unknown():
    """Not False. We cannot see his old club, so we do not claim he stayed put."""
    assert pd.isna(attached().loc["Fernandes", "moved_club"])


def test_no_minutes_is_not_enough_to_be_new():
    """Rashford played nowhere in the league last season — he was on loan abroad."""
    frame = attached()
    assert not frame.loc["Rashford", "new_to_pl"]


def test_genuine_debutant_is_flagged():
    """No record, and absent from last season's table."""
    frame = attached()
    assert frame.loc["Palestra", "new_to_pl"]
    # No prior club to differ from, so this is a real False rather than unknown.
    assert frame.loc["Palestra", "moved_club"] is False


def test_moved_club_is_detected():
    assert attached().loc["Rogers", "moved_club"]
    assert not attached().loc["Haaland", "moved_club"]


def test_oldest_season_has_no_prior_and_says_so():
    """
    2425 has nothing behind it. Every column must be null rather than False, so the
    view can drop them instead of claiming nobody moved and nobody was new.
    """
    frame = attach_prior_season(PICKS, PLAYERS, None)
    assert frame["new_to_pl"].isna().all()
    assert frame["moved_club"].isna().all()
    assert frame["prior_team_name"].isna().all()


def test_empty_prior_table_behaves_like_none():
    frame = attach_prior_season(PICKS, PLAYERS, PRIOR.iloc[0:0])
    assert frame["moved_club"].isna().all()
