"""Dunelmliga: a second published site, sharing the code and nothing else.

The point of these is separation. One pipeline, one React app and one scheduled
run now serve two groups of friends who have no interest in each other's league,
so the things that must not leak — data, seasons, league structure — are asserted
here rather than left to the workflow to get right.
"""

import json

import pandas as pd
import pytest

from pipeline import outputs, paths
from pipeline.build import _prior_players
from pipeline.config import SITES, get_season, get_site


def test_both_sites_are_registered():
    assert sorted(SITES) == ["dunelmliga", "wod"]


def test_dunelmliga_is_one_standalone_league():
    season = get_season("2627", "dunelmliga")
    assert len(season.leagues) == 1

    league = season.leagues[0]
    assert league.league_code == 32619
    assert league.size == 6
    # No division above or below it, so nothing to be promoted to or relegated from.
    assert (league.promoted, league.relegated) == (0, 0)
    assert league.exclude_entries == ()


def test_the_two_sites_do_not_share_a_season():
    """Same season id, different leagues — which is exactly why data is namespaced."""
    wod = get_season("2627", "wod")
    dunelmliga = get_season("2627", "dunelmliga")

    assert wod.season == dunelmliga.season == "2627"
    assert {lg.code for lg in wod.leagues} == {"Prem", "Conf"}
    assert {lg.code for lg in dunelmliga.leagues} == {"DL"}
    assert paths.data_dir("wod") != paths.data_dir("dunelmliga")
    assert paths.season_data_dir("2627", "wod").parent.name == "wod"


def test_a_site_only_knows_its_own_seasons():
    assert get_site("wod").season_ids == ("2425", "2526", "2627")
    assert get_site("dunelmliga").season_ids == ("2627",)
    with pytest.raises(KeyError, match="no season '2526'"):
        get_season("2526", "dunelmliga")


def test_current_and_archive_seasons_are_derived_not_declared():
    """One place to change at the rollover: the season's own `default_source`."""
    wod = get_site("wod")
    assert wod.current_season == "2627"
    assert wod.archive_seasons == ("2425", "2526")

    dunelmliga = get_site("dunelmliga")
    assert dunelmliga.current_season == "2627"
    assert dunelmliga.archive_seasons == ()


def test_the_index_ignores_another_sites_folders(tmp_path):
    """
    Both sites write under the same `data/`, so an index built for one must not
    pick up a season the other publishes even if the folder is right there.
    """
    for season in ("2526", "2627"):
        directory = tmp_path / season
        directory.mkdir(parents=True)
        (directory / "meta.json").write_text(json.dumps({
            "season": season, "label": "label",
            "current_gameweek": 38, "complete": True,
        }), encoding="utf-8")

    path = outputs.write_seasons_index(tmp_path, site="dunelmliga")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert [s["season"] for s in payload["seasons"]] == ["2627"]


def test_a_first_season_borrows_the_shared_player_history(tmp_path, monkeypatch, capsys):
    """
    Dunelmliga has no season behind its first, so the draft board would lose last
    season's points and clubs. players.json is a list of footballers, so it can be
    read from the site that does have an archive without exposing anything about
    that site's league.
    """
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    archive = tmp_path / "data" / "wod" / "2526"
    archive.mkdir(parents=True)
    (archive / "players.json").write_text(
        json.dumps([{"id": 1, "web_name": "Haaland", "total_points": 239}]),
        encoding="utf-8",
    )

    prior = _prior_players(get_season("2627", "dunelmliga"), get_site("dunelmliga"), print)
    assert isinstance(prior, pd.DataFrame)
    assert prior.loc[0, "web_name"] == "Haaland"


def test_a_missing_archive_costs_a_column_not_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)

    prior = _prior_players(get_season("2627", "dunelmliga"), get_site("dunelmliga"), print)

    assert prior is None
    assert "draft view loses last season's clubs" in capsys.readouterr().out


# --- head-to-head standings ------------------------------------------------
# FPL runs draft leagues on two scoring modes and serves a different standings
# shape for each. The WOD leagues are classic; Dunelmliga is head-to-head, which
# has no `event_total` at all — reading it blind raised
# `KeyError: ['event_total'] not in index` and took the whole build down.

def _details(standings):
    return {
        "league_entries": [{
            "entry_id": 169022, "entry_name": "Makélélé Reloaded", "id": 169828,
            "short_name": "mn", "player_first_name": "mike", "player_last_name": "nelson",
        }],
        "standings": standings,
    }


def test_head_to_head_standings_are_read_without_event_total():
    from pipeline.transforms.league import league_table

    table = league_table(_details([{
        "league_entry": 169828, "matches_played": 1, "matches_won": 1,
        "matches_drawn": 0, "matches_lost": 0, "points_for": 39,
        "points_against": 11, "total": 3, "rank": 1, "rank_sort": 1, "last_rank": None,
    }]), league_code="DL")

    row = table.iloc[0]
    assert row["short_name"] == "MN"
    assert row["rank"] == 1
    assert row["last_rank"] == 0          # null until the second gameweek
    assert row["gameweek_points"] == 0    # absent on this shape; recomputed later


def test_classic_standings_still_read_their_gameweek_points():
    from pipeline.transforms.league import league_table

    table = league_table(_details([{
        "league_entry": 169828, "event_total": 39, "total": 39,
        "rank": 1, "last_rank": 2,
    }]), league_code="Prem")

    row = table.iloc[0]
    assert (row["gameweek_points"], row["total"]) == (39, 39)
    assert (row["rank"], row["last_rank"]) == (1, 2)


# --- draft night that the API no longer serves ------------------------------

def test_dunelmliga_points_at_its_committed_draft_choices():
    league = get_season("2627", "dunelmliga").leagues[0]
    assert league.draft_choices_fallback == "reference/draft_choices/dunelmliga_2627.json"

    payload = json.loads(
        (paths.repo_root() / league.draft_choices_fallback).read_text(encoding="utf-8"))
    choices = payload["choices"]

    assert len(choices) == 90                                   # 6 drafters x 15
    assert sorted(c["index"] for c in choices) == list(range(1, 91))
    assert {c["pick"] for c in choices} == set(range(1, 7))
    assert len({c["element"] for c in choices}) == 90           # nobody drafted twice
    # A snake: the drafter who closes a round opens the next one.
    by_index = {c["index"]: c["entry"] for c in choices}
    assert by_index[6] == by_index[7]
    assert by_index[12] == by_index[13]


class _Source:
    """A source that serves whatever choices it was handed."""

    def __init__(self, choices):
        self.payload = {"choices": choices}

    def draft_choices(self, league_code):
        return self.payload


def test_an_empty_choices_payload_falls_back_to_the_committed_copy():
    from pipeline.build import _draft_choices

    league = get_season("2627", "dunelmliga").leagues[0]
    restored = _draft_choices(_Source([]), league, lambda *_: None)

    assert len(restored["choices"]) == 90


def test_the_api_wins_whenever_it_actually_serves_a_draft():
    """The fallback must never mask a live payload — only an absent one."""
    from pipeline.build import _draft_choices

    league = get_season("2627", "dunelmliga").leagues[0]
    live = [{"element": 1, "entry": 2, "index": 1, "pick": 1}]

    assert _draft_choices(_Source(live), league, lambda *_: None)["choices"] == live


def test_a_league_with_no_fallback_is_left_alone():
    from pipeline.build import _draft_choices

    league = get_season("2627", "wod").leagues[0]
    assert league.draft_choices_fallback is None
    assert _draft_choices(_Source([]), league, lambda *_: None) == {"choices": []}
