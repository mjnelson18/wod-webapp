"""The acceptance test: does the pipeline reproduce 2526 from 2526 raw?

Runs the pipeline on reference/raw_2526 and asserts every shared column matches
reference/historical/*_2526.csv, except columns that are knowingly CSV-backfilled
or deliberately cleaned up.

Slow (~2 min for the full season) because optimal_points solves 456 squad-weeks.
The module-scoped fixture means it runs once for all assertions.
"""

import pytest

from pipeline import validate

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def results():
    return validate.report("2526")


def _table(results, name):
    for entry in results:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"no comparison for {name}")


def test_no_unexplained_differences(results):
    """Every mismatching column must be explicitly accounted for."""
    problems = []
    for table in results:
        for column, info in table["columns"].items():
            if info["mismatches"] == 0:
                continue
            if column in validate.EXPECTED_BACKFILL:
                continue
            # Deliberate changes may be registered globally or per table, so ask
            # rather than testing membership — a (table, column) key is not found
            # by `column in INTENTIONAL`.
            if validate.intentional_note(table["name"], column):
                continue
            problems.append(f"{table['name']}.{column}: {info['mismatches']}/{info['compared']}")
    assert not problems, "unexplained differences vs the 2526 CSVs:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("name,rows", [
    ("weekly_summary", 6840),   # 12 drafters x 15 slots x 38 gameweeks
    ("weekly_points", 59494),
    ("draft_picks", 180),       # 12 drafters x 15 rounds
    ("players", 841),
])
def test_row_counts_match_csv(results, name, rows):
    table = _table(results, name)
    assert table["rows_produced"] == rows
    assert table["rows_expected"] == rows


def test_every_row_aligns(results):
    """No rows invented and none lost, on any table."""
    for table in results:
        assert table["only_in_produced"] == 0, f"{table['name']}: rows not in the CSV"
        assert table["only_in_csv"] == 0, f"{table['name']}: CSV rows not produced"


def test_optimal_points_matches_exactly(results):
    """The fractional tie-averaging is the subtle part — it must match to tolerance."""
    info = _table(results, "weekly_summary")["columns"]["optimal_points"]
    assert info["mismatches"] == 0


@pytest.mark.parametrize("column", [
    "points_scored", "points_before_auto_subs", "originally_starting",
    "points_scored_cumulative", "points_scored_pct", "player_total_points",
    "index", "round", "in_original_draft", "total",
])
def test_core_summary_columns_match(results, column):
    info = _table(results, "weekly_summary")["columns"][column]
    assert info["mismatches"] == 0, info.get("examples")


@pytest.mark.parametrize("column", ["rank_in_week", "short_name", "isBenched", "place"])
def test_weekly_points_columns_match(results, column):
    info = _table(results, "weekly_points")["columns"][column]
    assert info["mismatches"] == 0, info.get("examples")


@pytest.mark.parametrize("column", [
    "opposition", "home_away", "team_score", "opposition_score", "gameweek_matches",
])
def test_fixtures_rebuilt_from_draft_api_match(results, column):
    """
    Fixtures were rebuilt from draft-side event/{gw}/live because
    fantasy.premierleague.com had already rolled to 2627 (docs/notebook-recon.md 6.1).
    """
    info = _table(results, "weekly_summary")["columns"][column]
    assert info["mismatches"] == 0, info.get("examples")
