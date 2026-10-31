"""Unit tests for the fixture-aware cron window generator.

Pure functions only — fetching is exercised in CI by reschedule.yml itself.
"""

from datetime import datetime, timezone

import pytest

from pipeline.windows import cron_lines, match_windows, replace_block


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def fixture(event, kickoff):
    return {"event": event, "kickoff_time": kickoff}


LONG_AGO = utc(2020, 1, 1)


def test_saturday_cluster_merges_into_one_window():
    """12:30 + 15:00x3 + 17:30 is one window, not five."""
    fixtures = [
        fixture(9, "2026-10-31T12:30:00Z"),
        fixture(9, "2026-10-31T15:00:00Z"),
        fixture(9, "2026-10-31T15:00:00Z"),
        fixture(9, "2026-10-31T15:00:00Z"),
        fixture(9, "2026-10-31T17:30:00Z"),
    ]
    windows = match_windows(fixtures, {9}, now=LONG_AGO)
    assert len(windows) == 1
    start, end, kickoffs = windows[0]
    assert start == utc(2026, 10, 31, 12, 20)   # 10 min before first kickoff
    assert end == utc(2026, 10, 31, 21, 0)      # 3.5 h after the last
    assert len(kickoffs) == 5

    (line,) = cron_lines(windows)
    assert line == (
        "- cron: '*/10 12-20 31 10 *'   # Sat 31 Oct — 5 kickoffs, "
        "12:30–17:30 UTC"
    )


def test_distinct_days_stay_separate_and_past_days_are_pruned():
    fixtures = [
        fixture(9, "2026-10-30T20:00:00Z"),   # Friday — in the past below
        fixture(10, "2026-11-01T16:30:00Z"),  # Sunday
    ]
    now = utc(2026, 10, 31, 12, 0)
    windows = match_windows(fixtures, {9, 10}, now=now)
    (line,) = cron_lines(windows)
    assert line == "- cron: '*/10 16-19 1 11 *'   # Sun 1 Nov — 1 kickoff, 16:30 UTC"


def test_window_in_progress_is_kept():
    """A match being played right now still gets its window."""
    fixtures = [fixture(9, "2026-10-31T15:00:00Z")]
    now = utc(2026, 10, 31, 16, 0)
    assert len(match_windows(fixtures, {9}, now=now)) == 1


def test_window_crossing_midnight_splits_into_two_lines():
    fixtures = [fixture(9, "2026-10-31T21:00:00Z")]  # ends 00:30 the next day
    lines = cron_lines(match_windows(fixtures, {9}, now=LONG_AGO))
    assert lines == [
        "- cron: '*/10 20-23 31 10 *'   # Sat 31 Oct — 1 kickoff, 21:00 UTC",
        "- cron: '*/10 0 1 11 *'   # Sun 1 Nov — 1 kickoff, 21:00 UTC",
    ]


def test_other_events_and_postponed_fixtures_are_ignored():
    fixtures = [
        fixture(8, "2026-10-24T14:00:00Z"),       # wrong gameweek
        {"event": 9, "kickoff_time": None},        # postponed, date TBC
    ]
    assert match_windows(fixtures, {9}, now=LONG_AGO) == []


def test_replace_block_swaps_only_the_marked_lines():
    workflow = (
        "on:\n"
        "  schedule:\n"
        "    # BEGIN match windows (generated)\n"
        "    - cron: '*/10 1 1 1 *'   # stale\n"
        "    # END match windows\n"
        "    - cron: '17 */3 * * *'   # baseline\n"
    )
    updated = replace_block(workflow, ["- cron: '*/10 12-20 31 10 *'   # new"])
    assert updated == (
        "on:\n"
        "  schedule:\n"
        "    # BEGIN match windows (generated)\n"
        "    - cron: '*/10 12-20 31 10 *'   # new\n"
        "    # END match windows\n"
        "    - cron: '17 */3 * * *'   # baseline\n"
    )
    # idempotent: writing the same lines again changes nothing
    assert replace_block(updated, ["- cron: '*/10 12-20 31 10 *'   # new"]) == updated


def test_replace_block_with_no_windows_leaves_a_note():
    workflow = (
        "    # BEGIN match windows\n"
        "    - cron: '*/10 1 1 1 *'\n"
        "    # END match windows\n"
    )
    updated = replace_block(workflow, [])
    assert "no upcoming fixtures" in updated
    assert "*/10 1 1 1" not in updated


def test_replace_block_refuses_a_file_without_markers():
    with pytest.raises(ValueError):
        replace_block("on:\n  schedule:\n    - cron: '17 * * * *'\n", [])


def test_real_workflow_has_the_markers():
    """The committed update.yml must keep the block the rewriter targets."""
    from pipeline import paths

    text = (paths.repo_root() / ".github/workflows/update.yml").read_text(encoding="utf-8")
    assert replace_block(text, ["- cron: '*/10 12-20 31 10 *'   # probe"]) != text
