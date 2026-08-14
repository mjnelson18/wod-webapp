"""Behaviour across the season rollover.

The FPL API serves only the current season, and the two hosts flip independently
and not instantaneously. Four things must hold through that window:

  1. Archived seasons never depend on the API again.
  2. A season whose league codes aren't known yet doesn't block deploys.
  3. Data from the wrong season is refused, not silently relabelled.
  4. An API serving a holding page skips the run instead of failing it.

Nothing here may touch the network: these tests have to pass while the very outage
they describe is happening.
"""

import urllib.request

import pytest

from pipeline import schedule
from pipeline.build import build_tables
from pipeline.config import League, Season, get_season
from pipeline.fetchers.http import Maintenance, RateLimited
from pipeline.schedule import decide
from pipeline.transforms.players import bootstrap_start_year, season_start_year


def stub_game(monkeypatch, **overrides):
    """Answer the gate's two endpoints without a network call."""
    game = {"current_event": 38, "current_event_finished": True, "next_event": None}
    game.update(overrides)
    monkeypatch.setattr(schedule, "get_json",
                        lambda url, **kwargs: [] if "fixtures" in url else game)


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

# A season with no league codes yet. Deliberately synthetic rather than the real
# current season: the live one gets configured on draft night, which used to turn
# these two tests red (and send them to the network) as a side effect.
UNCONFIGURED = Season(
    season="9999", label="future", default_source="live",
    leagues=(League(code="Prem", name="Premiership", league_code=None, size=6),),
)


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(schedule, "get_season", lambda season: UNCONFIGURED)


def test_unconfigured_season_still_allows_a_deploy(unconfigured):
    """
    Between the rollover and draft night the league codes don't exist yet. The
    current season can't be built, but the site is fine from the archives, so a
    forced run (push or manual) must still go ahead.
    """
    result = decide("9999", force=True)
    assert result["should_build"] is True      # archives build, site deploys
    assert result["season_ready"] is False     # current season is skipped
    assert result["state"] == "not_configured"


def test_unconfigured_season_is_throttled_but_not_fatal(unconfigured):
    result = decide("9999")
    assert result["season_ready"] is False
    assert result["state"] == "not_configured"
    # daily re-check, so the first configured run happens without a manual nudge
    from pipeline.schedule import MINIMUM_INTERVAL
    assert MINIMUM_INTERVAL["not_configured"] == 24 * 60 * 60


def test_configured_archive_season_reports_ready(monkeypatch):
    stub_game(monkeypatch)
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


# --- 4. the API answers, but with a holding page ---------------------------

def _raises(error):
    def get_json(url, **kwargs):
        raise error(f"{url}: holding page")
    return get_json


def test_holding_page_skips_the_run_instead_of_failing(monkeypatch):
    """
    Once the league codes are filled in, the gate calls the draft API on every
    single run. Between seasons that returns an HTML holding page under HTTP 200,
    which used to raise FetchError out of the gate and redden the whole workflow —
    a failure email every ten minutes for something entirely expected.
    """
    monkeypatch.setattr(schedule, "get_json", _raises(Maintenance))
    result = decide("2526")
    assert result["state"] == "maintenance"
    assert result["should_build"] is False


@pytest.mark.parametrize("error,state", [(Maintenance, "maintenance"),
                                         (RateLimited, "rate_limited")])
def test_an_unusable_api_is_not_overridden_by_force(monkeypatch, error, state):
    """
    Unlike not_configured, a forced run must not proceed either. The season index
    is assembled from the season folders on disk and the current season's JSON is
    never cached, so building without it would deploy a site with the current
    season missing — worse than leaving the last good deploy alone.
    """
    monkeypatch.setattr(schedule, "get_json", _raises(error))
    result = decide("2526", force=True)
    assert result["state"] == state
    assert result["should_build"] is False


def test_skip_states_need_no_interval(monkeypatch):
    """
    They return before the interval lookup. Asserted because adding a state to
    SKIP_STATES and forgetting the dict entry would be a KeyError in the gate —
    exactly the kind of hard failure this whole path exists to avoid.
    """
    for state in schedule.SKIP_STATES:
        assert state not in schedule.MINIMUM_INTERVAL
    monkeypatch.setattr(schedule, "get_json", _raises(Maintenance))
    decide("2526")          # must not raise
