"""2425 archive: schema and plausibility only.

2425's raw data is gone forever and was never snapshotted, so there is nothing to
re-run the logic against. These tests assert the archive is structurally sound and
the numbers are plausible — they deliberately do NOT claim logic equivalence.
"""

import pandas as pd
import pytest

from pipeline.build import build_tables
from pipeline.config import get_season


@pytest.fixture(scope="module")
def tables():
    return build_tables("2425", verbose=False)


@pytest.fixture(scope="module")
def season():
    return get_season("2425")


def test_handles_the_five_seven_split(tables, season):
    """2425 was the exception: 5 Premiership, 7 Conference."""
    counts = (tables["weekly_summary"].groupby("league_code")["short_name"].nunique().to_dict())
    assert counts["Prem"] == 5
    assert counts["Conf"] == 7
    assert season.league("Prem").size == 5
    assert season.league("Conf").size == 7


def test_promotion_relegation_counts(season):
    """3 up / 1 down, not the 2 up / 2 down that applies from 2526 onward."""
    assert season.league("Conf").promoted == 3
    assert season.league("Prem").relegated == 1


def test_twelve_drafters_and_full_season(tables):
    summary = tables["weekly_summary"]
    assert summary["short_name"].nunique() == 12
    assert sorted(summary["gameweek"].unique()) == list(range(1, 39))
    assert len(summary) == 6840  # 12 x 15 x 38


def test_draft_rounds_derived_for_both_league_sizes(tables):
    """
    Rounds must come out 1..15 for a 5-drafter and a 7-drafter league alike.

    The notebook's hardcoded // 6 cannot do this; the count comes from config.
    """
    picks = tables["draft_picks"]
    for league in ("Prem", "Conf"):
        rounds = picks[picks["league_code"] == league]["round"]
        assert rounds.min() == 1
        assert rounds.max() == 15
        # every drafter picks exactly once per round
        per_round = picks[picks["league_code"] == league].groupby("round").size()
        assert per_round.nunique() == 1


def test_squad_is_fifteen_with_eleven_starters(tables):
    summary = tables["weekly_summary"]
    sizes = summary.groupby(["league_code", "short_name", "gameweek"]).size()
    assert set(sizes.unique()) == {15}
    starters = summary[summary["place"] <= 11].groupby(
        ["league_code", "short_name", "gameweek"]).size()
    assert set(starters.unique()) == {11}


def test_points_scored_only_counts_starters(tables):
    summary = tables["weekly_summary"]
    benched = summary[summary["place"] > 11]
    assert (benched["points_scored"] == 0).all()


def test_cumulative_points_track_the_running_sum(tables):
    """
    Cumulative points must equal the running sum of points_scored.

    Not a monotonicity check: a player can score negative points (a red card and
    goals conceded outweighing the appearance point), so the cumulative total
    legitimately dips.
    """
    summary = tables["weekly_summary"].sort_values(
        ["league_code", "short_name", "element", "gameweek"])
    groups = summary.groupby(["league_code", "short_name", "element"])
    expected = groups["points_scored"].cumsum()
    assert (summary["points_scored_cumulative"] == expected).all()


def test_negative_gameweek_scores_are_preserved(tables):
    """Sanity check that the season really does contain negative scores."""
    assert (tables["weekly_summary"]["total_points"] < 0).any()


def test_totals_are_plausible(tables):
    """A season total per drafter should land in a sane range, not 0 or 10x."""
    table = tables["league_table"]
    assert table["total"].between(800, 2600).all(), table[["short_name", "total"]].to_dict("records")


def test_absent_columns_are_null_not_missing(tables):
    """The canonical schema is uniform; 2425 gaps are null, never dropped columns."""
    summary = tables["weekly_summary"]
    for column in ("opposition", "home_away", "team_difficulty", "opposition_difficulty",
                   "team_score", "opposition_score", "gameweek_matches"):
        assert column in summary.columns
        assert summary[column].isna().all()


def test_no_trades_existed(tables):
    assert len(tables["trades"]) == 0


def test_capabilities_report_the_gaps(tables):
    from pipeline.outputs import _capabilities
    caps = _capabilities(tables)
    assert caps["fixtures"] is False
    assert caps["difficulty"] is False
    assert caps["cost"] is False
    assert caps["trades"] is False
    # these are genuinely derivable from what the CSVs do have
    assert caps["draft_round"] is True
    assert caps["cumulative"] is True
    assert caps["optimal_points"] is True
