"""Behaviour across the season rollover.

The FPL API serves only the current season, and the two hosts flip independently
and not instantaneously. Three things must hold through that window:

  1. Archived seasons never depend on the API again.
  2. A season whose league codes aren't known yet doesn't block deploys.
  3. Data from the wrong season is refused, not silently relabelled.
"""

import urllib.request

import pytest

from pipeline.build import build_tables
from pipeline.config import get_season
from pipeline.schedule import decide
from pipeline.transforms.players import bootstrap_start_year, season_start_year


# --- 1. archives are frozen ------------------------------------------------

@pytest.fixture
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("archive build attempted a network call")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.mark.parametrize("season", ["2526", "2425"])
def test_archive_builds_with_no_network(no_network, season):
    """
    2526 comes from the committed raw snapshot, 2425 from the committed CSVs.
    Neither may touch the API, or the archive would evaporate at the rollover.
    """
    tables = build_tables(season, verbose=False)
    assert len(tables["weekly_summary"]) == 6840
    assert tables["weekly_summary"]["gameweek"].max() == 38


def test_archive_seasons_declare_a_non_live_source():
    for season in ("2425", "2526"):
        assert get_season(season).default_source in ("csv", "snapshot")


# --- 2. the pre-season gap -------------------------------------------------

def test_unconfigured_season_still_allows_a_deploy():
    """
    Between the rollover and draft night the league codes don't exist yet. The
    current season can't be built, but the site is fine from the archives, so a
    forced run (push or manual) must still go ahead.
    """
    result = decide("2627", force=True)
    assert result["should_build"] is True      # archives build, site deploys
    assert result["season_ready"] is False     # current season is skipped
    assert result["state"] == "not_configured"


def test_unconfigured_season_is_throttled_but_not_fatal():
    result = decide("2627")
    assert result["season_ready"] is False
    assert result["state"] == "not_configured"
    # daily re-check, so the first configured run happens without a manual nudge
    from pipeline.schedule import MINIMUM_INTERVAL
    assert MINIMUM_INTERVAL["not_configured"] == 24 * 60 * 60


def test_configured_archive_season_reports_ready():
    assert decide("2526", force=True)["season_ready"] is True


# --- 3. wrong-season data is refused --------------------------------------

def test_season_start_year_mapping():
    assert season_start_year("2425") == 2024
    assert season_start_year("2526") == 2025
    assert season_start_year("2627") == 2026


def test_snapshot_reports_its_real_season():
    from pipeline.fetchers import SnapshotSource
    bootstrap = SnapshotSource("reference/raw_2526").bootstrap_draft()
    assert bootstrap_start_year(bootstrap) == 2025


def test_building_a_season_against_the_wrong_payload_is_refused(monkeypatch):
    """
    Simulates a build kicked off before the API rolled over: we ask for 2627 but
    the draft host still serves 2526. That must abort, not write 2526 numbers out
    under the 2627 label.
    """
    from pipeline import build as build_module
    from pipeline.fetchers import SnapshotSource

    snapshot = SnapshotSource("reference/raw_2526")   # a 2025/26 payload
    monkeypatch.setattr(build_module, "build_source", lambda *a, **k: snapshot)

    season = get_season("2526")
    monkeypatch.setattr(build_module, "get_season", lambda _: type(season)(
        season="2627", label="2026/27", leagues=season.leagues,
        default_source="snapshot", snapshot_dir=season.snapshot_dir,
    ))

    with pytest.raises(SystemExit, match="season mismatch"):
        build_tables("2627", verbose=False)


def test_bootstrap_start_year_handles_missing_events():
    assert bootstrap_start_year({}) is None
    assert bootstrap_start_year({"events": {"data": []}}) is None
