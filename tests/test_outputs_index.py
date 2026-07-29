"""The season index must be rebuildable without running a build.

Regression test for a live outage: the workflow's archive cache stores the season
directories only, so on a cache hit with no build running, data/seasons.json was
absent and the deployed site failed to load with `seasons.json: 404`. The index is
now regenerated unconditionally, so it must work from season folders alone.
"""

import json

import pytest

from pipeline import outputs


def _season_dir(root, season, gameweek=38, complete=True):
    directory = root / season
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(json.dumps({
        "season": season, "label": f"20{season[:2]}/{season[2:]}",
        "current_gameweek": gameweek, "complete": complete,
    }), encoding="utf-8")
    return directory


def test_index_is_built_from_directories_on_disk(tmp_path):
    _season_dir(tmp_path, "2425")
    _season_dir(tmp_path, "2526")

    path = outputs.write_seasons_index(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "seasons.json"
    assert [s["season"] for s in payload["seasons"]] == ["2526", "2425"]  # newest first
    assert payload["default"] == "2526"


def test_index_rebuilds_when_only_the_cache_was_restored(tmp_path):
    """The outage scenario: season folders present, index missing, no build run."""
    _season_dir(tmp_path, "2526")
    index = tmp_path / "seasons.json"
    assert not index.exists()

    outputs.write_seasons_index(tmp_path)
    assert index.exists()
    assert json.loads(index.read_text(encoding="utf-8"))["default"] == "2526"


def test_index_ignores_directories_without_meta(tmp_path):
    _season_dir(tmp_path, "2526")
    (tmp_path / "2627").mkdir()          # half-written, no meta.json
    payload = json.loads(outputs.write_seasons_index(tmp_path).read_text(encoding="utf-8"))
    assert [s["season"] for s in payload["seasons"]] == ["2526"]


def test_empty_index_is_reported_as_an_error(tmp_path, monkeypatch, capsys):
    """An empty index means a blank site — the run must fail, not deploy it."""
    monkeypatch.setattr(outputs.paths, "data_dir", lambda: tmp_path)
    assert outputs.main(["--index"]) == 1
    assert "No seasons" in capsys.readouterr().out


def test_index_succeeds_when_seasons_exist(tmp_path, monkeypatch):
    _season_dir(tmp_path, "2526")
    monkeypatch.setattr(outputs.paths, "data_dir", lambda: tmp_path)
    assert outputs.main(["--index"]) == 0


def test_requires_a_flag(tmp_path):
    with pytest.raises(SystemExit):
        outputs.main([])
