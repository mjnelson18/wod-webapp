"""
`draft_picks.total_points` must mean the same thing in every season.

It didn't. The 2425 archive read the column straight from its CSV, where it is
the player's full season total; the live path built it from
`attach_pick_totals`, which summed only the weeks the drafter held the player,
because that is what the notebook did and what `Draft Picks_2526.csv` records.

Both are useful numbers. Sharing one name between them is not: any view pooling
the column across seasons compares a season total against a partial one, and
silently understates whichever season came from the live path.
"""

import pandas as pd
import pytest

from pipeline.transforms.draft_picks import attach_pick_totals


def _weekly_points():
    """
    One row per league / gameweek / player, `short_name` being that week's owner.

    Player 10 is drafted by AA, who holds him for two weeks (6 + 4) before BB
    picks him up for a third (5). Season total 15, of which AA banked 10.
    """
    return pd.DataFrame({
        "league_code": ["Prem"] * 4,
        "gameweek": [1, 2, 3, 1],
        "id": [10, 10, 10, 11],
        "short_name": ["AA", "AA", "BB", "BB"],
        "total_points": [6, 4, 5, 7],
    })


def _picks():
    return pd.DataFrame({
        "league_code": ["Prem", "Prem"],
        "short_name": ["AA", "BB"],
        "element": [10, 11],
    })


def test_total_points_is_the_players_season_total_not_the_drafters_share():
    frame = attach_pick_totals(_picks(), _weekly_points())
    aa = frame.loc[frame["short_name"] == "AA"].iloc[0]

    # 6 + 4 + 5 — everything the player scored, including the week BB owned him.
    assert aa["total_points"] == 15
    # ...while what AA actually banked is kept separately.
    assert aa["points_realised_by_drafter"] == 10


def test_a_drafter_who_never_held_their_pick_realises_zero_not_nan():
    picks = pd.DataFrame({
        "league_code": ["Prem"], "short_name": ["CC"], "element": [10],
    })
    frame = attach_pick_totals(picks, _weekly_points())
    assert frame.iloc[0]["total_points"] == 15
    assert frame.iloc[0]["points_realised_by_drafter"] == 0


def test_realised_never_exceeds_the_season_total():
    frame = attach_pick_totals(_picks(), _weekly_points())
    assert (frame["points_realised_by_drafter"] <= frame["total_points"]).all()


def _agrees_with_performance(tables, season):
    """
    The cross-season guard. `draft_performance` already carries both quantities
    under unambiguous names, so it is the reference: if `draft_picks` agrees with
    it for every season, the two producers cannot drift apart again.

    Note `draft_performance` is a *view*, not a top-level table — `outputs.py`
    writes everything under `tables["views"]` as its own JSON file.
    """
    picks = tables["draft_picks"]
    performance = tables["views"]["draft_performance"]

    for column in ("total_points", "points_realised_by_drafter"):
        assert column in picks.columns, f"{season}: draft_picks is missing {column}"

    # Take only the keys and the two columns under test. `draft_performance` also
    # carries web_name and position, and letting those collide would suffix them —
    # making `r.web_name` in the failure messages below an AttributeError.
    keys = ["league_code", "short_name", "element"]
    reference = (
        performance.rename(columns={"id": "element", "drafter_name": "short_name"})
        [keys + ["total_points", "points_realised_by_drafter"]]
    )
    merged = picks.merge(
        reference, on=keys, how="left", indicator=True, suffixes=("_picks", "_perf"),
    )

    unmatched = merged.loc[merged["_merge"] == "left_only"]
    assert unmatched.empty, (
        f"{season}: {len(unmatched)} picks have no draft_performance row, e.g. "
        + ", ".join(
            f"{r.short_name} {r.web_name}" for r in unmatched.head(5).itertuples()
        )
    )

    for column in ("total_points", "points_realised_by_drafter"):
        left = pd.to_numeric(merged[f"{column}_picks"], errors="coerce").fillna(-1)
        right = pd.to_numeric(merged[f"{column}_perf"], errors="coerce").fillna(-1)
        bad = merged.loc[left != right]
        assert bad.empty, (
            f"{season}: {column} disagrees with draft_performance on {len(bad)} picks, e.g. "
            + ", ".join(
                f"{r.short_name} {r.web_name} "
                f"{getattr(r, column + '_picks')} vs {getattr(r, column + '_perf')}"
                for r in bad.head(5).itertuples()
            )
        )


def test_archive_2425_agrees_with_draft_performance():
    from pipeline.build import build_tables
    _agrees_with_performance(build_tables("2425", verbose=False), "2425")


@pytest.mark.slow
def test_live_2526_agrees_with_draft_performance():
    """Guards the live path, which is where the two meanings diverged."""
    from pipeline.build import build_tables
    _agrees_with_performance(build_tables("2526", verbose=False), "2526")
