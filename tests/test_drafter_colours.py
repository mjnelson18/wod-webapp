"""Drafter colours follow a person from season to season."""

import json

from pipeline import outputs
from pipeline.config.seasons import previous_season
from pipeline.transforms.drafters import assign_drafter_colours


def test_first_season_is_dealt_alphabetically_across_both_leagues():
    colours, registry = assign_drafter_colours(["TS", "AC", "MN", "JP"], None)
    assert colours == {"AC": 0, "JP": 1, "MN": 2, "TS": 3}
    assert registry == colours


def test_returning_drafters_keep_their_slot_and_newcomers_take_the_lowest_free_one():
    _, registry = assign_drafter_colours(["AC", "JP", "MN", "TS"], None)   # AC0 JP1 MN2 TS3
    colours, updated = assign_drafter_colours(["TS", "MN", "BB", "ZZ"], registry)   # JP, AC gone
    assert colours == {"MN": 2, "TS": 3, "BB": 0, "ZZ": 1}
    # the memory keeps the departed too, so they get their colour back if they return
    assert updated == {"AC": 0, "JP": 1, "MN": 2, "TS": 3, "BB": 0, "ZZ": 1}


def test_a_drafter_back_after_a_season_out_is_remembered():
    _, r1 = assign_drafter_colours(["AC", "JP"], None)          # AC0 JP1
    _, r2 = assign_drafter_colours(["JP", "MN"], r1)            # MN takes the free 0
    colours, _ = assign_drafter_colours(["AC", "JP", "MN"], r2)
    # AC and MN both remember slot 0; the alphabetically earlier keeps it, the other re-deals
    assert colours == {"AC": 0, "JP": 1, "MN": 2}


def test_initials_match_case_insensitively_and_keep_their_spelling():
    _, registry = assign_drafter_colours(["mn"], None)
    colours, updated = assign_drafter_colours(["MN", "AC"], registry)
    assert colours == {"MN": 0, "AC": 1}
    assert updated == {"MN": 0, "AC": 1}


def test_twelve_slots_cover_a_full_season_and_wrap_beyond():
    names = [f"D{i:02d}" for i in range(13)]
    colours, _ = assign_drafter_colours(names, None)
    assert sorted(colours.values()) == [0] + list(range(12))   # twelve distinct, then one repeat
    assert colours["D12"] == 0        # thirteenth drafter wraps rather than failing


def test_previous_season_ids():
    assert previous_season("2627") == "2526"
    assert previous_season("2526") == "2425"
    assert previous_season("0001") is None
    assert previous_season("live") is None


def test_prior_registry_is_read_from_last_seasons_meta(tmp_path, monkeypatch):
    """The live season's build reads the restored 2526 archive's meta.json."""
    monkeypatch.setattr(outputs.paths, "season_data_dir",
                        lambda season, site=None: tmp_path / str(site) / str(season))
    (tmp_path / "wod" / "2526").mkdir(parents=True)
    (tmp_path / "wod" / "2526" / "meta.json").write_text(json.dumps({
        "drafters": [{"short_name": "TS", "league": "Prem", "colour": 11}],
        "colour_registry": {"ac": 0, "TS": 11, "XX": 4},
    }), encoding="utf-8")

    class S:
        season = "2627"

    assert outputs._prior_colour_registry(S, "wod") == {"AC": 0, "TS": 11, "XX": 4}
    assert outputs._prior_colour_registry(S, "dunelmliga") == {}     # another site: nothing borrowed

    class First:
        season = "2425"

    assert outputs._prior_colour_registry(First, "wod") == {}       # nothing before it


def test_drafters_meta_is_sorted_and_coloured(monkeypatch):
    monkeypatch.setattr(outputs, "_prior_colour_registry", lambda season, site: {"TS": 7})

    class S:
        season = "2627"

    rows = [
        {"short_name": "TS", "name": "Tom", "league_code": "Prem"},
        {"short_name": "AC", "name": "Alex", "league_code": "Conf"},
        {"short_name": "MN", "name": "Mike", "league_code": "Prem"},
    ]
    drafters, registry = outputs._drafters_meta(rows, S, "wod")
    assert [d["short_name"] for d in drafters] == ["AC", "MN", "TS"]
    assert {d["short_name"]: d["colour"] for d in drafters} == {"TS": 7, "AC": 0, "MN": 1}
    assert drafters[0] == {"short_name": "AC", "name": "Alex", "league": "Conf", "colour": 0}
    assert registry == {"TS": 7, "AC": 0, "MN": 1}
