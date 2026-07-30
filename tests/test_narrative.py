"""Unit tests for the season review facts pack.

Built on a tiny hand-made season so every expected number can be worked out by
hand — the point is that the beats are *correct*, not that they run.
"""

import json

import pandas as pd
import pytest

from pipeline.config import League, Season
from pipeline.transforms.narrative import season_review_facts

SEASON = Season(
    season="9900", label="1999/00", total_gameweeks=3, default_source="csv",
    leagues=(
        League(code="Prem", name="Premiership", league_code=None, size=2, relegated=1),
        League(code="Conf", name="Conference", league_code=None, size=2, promoted=1),
    ),
)

# AA wins the Prem from behind: headed after GW1, level-ish, then clear.
#   AA  10, 30, 30  -> 70      BB  20, 15, 20 -> 55
#   CC  25, 25, 25  -> 75      DD  30, 10, 10 -> 50
POINTS = {
    ("Prem", "AA"): [10, 30, 30],
    ("Prem", "BB"): [20, 15, 20],
    ("Conf", "CC"): [25, 25, 25],
    ("Conf", "DD"): [30, 10, 10],
}
NAMES = {"AA": "Alan Partridge", "BB": "Bill Bailey",
         "CC": "Carol Clark", "DD": "Dave Dixon"}


def _by_week() -> pd.DataFrame:
    rows = []
    for (league, short), scores in POINTS.items():
        running = 0
        for gameweek, points in enumerate(scores, start=1):
            running += points
            rows.append({"league_code": league, "short_name": short,
                         "gameweek": gameweek, "points_scored": points,
                         "cumulative_points": running})
    return pd.DataFrame(rows)


def _league_table() -> pd.DataFrame:
    rows = []
    for league in ("Prem", "Conf"):
        totals = sorted(
            ((short, sum(scores)) for (lg, short), scores in POINTS.items() if lg == league),
            key=lambda pair: -pair[1],
        )
        for rank, (short, total) in enumerate(totals, start=1):
            rows.append({"league_code": league, "short_name": short, "name": NAMES[short],
                         "entry_name": f"{short} FC", "rank": rank, "total": total})
    return pd.DataFrame(rows)


def _weekly_summary() -> pd.DataFrame:
    """One squad slot per drafter per week; optimal exceeds scored by a fixed 5."""
    rows = []
    for (league, short), scores in POINTS.items():
        for gameweek, points in enumerate(scores, start=1):
            rows.append({
                "league_code": league, "short_name": short, "gameweek": gameweek,
                "element": 1, "web_name": "Player", "position": "MID", "place": 1,
                "points_scored": points, "optimal_points": points + 5,
            })
    return pd.DataFrame(rows)


def _weekly_points() -> pd.DataFrame:
    """Two players: 100 scores 10 a week all season, 200 scores nothing."""
    rows = []
    for league in ("Prem", "Conf"):
        for gameweek in (1, 2, 3):
            rows.append({"league_code": league, "gameweek": gameweek, "id": 100,
                         "web_name": "Hauler", "total_points": 10})
            rows.append({"league_code": league, "gameweek": gameweek, "id": 200,
                         "web_name": "Dud", "total_points": 0})
    return pd.DataFrame(rows)


def _draft_picks() -> pd.DataFrame:
    rows = []
    for league, drafters in (("Prem", ("AA", "BB")), ("Conf", ("CC", "DD"))):
        for i, short in enumerate(drafters, start=1):
            rows.append({"league_code": league, "short_name": short, "index": i,
                         "pick": i, "round": 1, "element": 100 if i == 1 else 200,
                         "web_name": "Hauler" if i == 1 else "Dud", "position": "MID",
                         "total_points": 30 if i == 1 else 0})
            rows.append({"league_code": league, "short_name": short, "index": i + 2,
                         "pick": i, "round": 2, "element": 300 + i,
                         "web_name": f"Late{i}", "position": "FWD", "total_points": 5})
    return pd.DataFrame(rows)


def _draft_performance() -> pd.DataFrame:
    rows = []
    for league in ("Prem", "Conf"):
        rows.append({"league_code": league, "id": 100, "total_points": 30,
                     "points_realised_by_drafter": 30})
        rows.append({"league_code": league, "id": 200, "total_points": 0,
                     "points_realised_by_drafter": 0})
        for i in (1, 2):
            rows.append({"league_code": league, "id": 300 + i, "total_points": 5,
                         "points_realised_by_drafter": 5})
    return pd.DataFrame(rows)


def _transfers() -> pd.DataFrame:
    """AA lands the hauler in GW1; BB is beaten to him in GW2."""
    return pd.DataFrame([
        {"league_code": "Prem", "gameweek": 1, "short_name": "AA", "kind": "waiver",
         "result": "successful", "element_in": 100, "element_out": 200,
         "player_in": "Hauler", "player_out": "Dud"},
        {"league_code": "Prem", "gameweek": 2, "short_name": "BB", "kind": "waiver",
         "result": "unsuccessful - player in already been picked up",
         "element_in": 100, "element_out": 200, "player_in": "Hauler", "player_out": "Dud"},
        {"league_code": "Prem", "gameweek": 2, "short_name": "BB", "kind": "waiver",
         "result": "unsuccessful - player out already gone",
         "element_in": 100, "element_out": 200, "player_in": "Hauler", "player_out": "Dud"},
    ])


def _trades() -> pd.DataFrame:
    """One real drafter-to-drafter swap, one with the excluded entry."""
    return pd.DataFrame([
        {"league_code": "Prem", "gameweek": 2, "state": "p", "offered_by": "AA",
         "received_by": "BB", "element_in": 100, "element_out": 200,
         "player_in": "Hauler", "player_out": "Dud", "net_points_from_trade": 20},
        {"league_code": "Prem", "gameweek": 3, "state": "p", "offered_by": "AA",
         "received_by": "99999", "element_in": 100, "element_out": 200,
         "player_in": "Hauler", "player_out": "Dud", "net_points_from_trade": 99},
    ])


@pytest.fixture(scope="module")
def facts() -> dict:
    return season_review_facts(
        season=SEASON, current_week=3,
        league_table=_league_table(), league_table_by_week=_by_week(),
        weekly_summary=_weekly_summary(), weekly_points=_weekly_points(),
        draft_picks=_draft_picks(), draft_performance=_draft_performance(),
        transfers=_transfers(), trades=_trades(),
    )


def _league(facts: dict, code: str) -> dict:
    return next(lg for lg in facts["leagues"] if lg["code"] == code)


# --- honours ----------------------------------------------------------------

def test_champion_margin_and_last_place(facts):
    prem = _league(facts, "Prem")
    assert prem["champion"]["short_name"] == "AA"
    assert prem["champion"]["name"] == "Alan Partridge"
    assert prem["title_margin"] == 70 - 55
    assert prem["wooden_spoon"]["short_name"] == "BB"


def test_promotion_and_relegation_come_from_config(facts):
    """Counts are per-league config, never hardcoded ranks — 2425 ran 3 up / 1 down."""
    assert [r["short_name"] for r in _league(facts, "Prem")["relegated"]] == ["BB"]
    assert _league(facts, "Prem")["promoted"] == []
    assert [r["short_name"] for r in _league(facts, "Conf")["promoted"]] == ["CC"]
    assert _league(facts, "Conf")["relegated"] == []


# --- the race ---------------------------------------------------------------

def test_champion_who_was_headed_early_is_not_wire_to_wire(facts):
    race = _league(facts, "Prem")["race"]
    assert [e["short_name"] for e in race["leader_by_gameweek"]] == ["BB", "AA", "AA"]
    assert race["lead_changes"] == 1
    assert race["champion_led_unbroken_from"] == 2
    assert race["wire_to_wire"] is False
    assert race["biggest_deficit_overturned"]["points"] == 10   # 20 v 10 after GW1


def test_longest_spell_top_tracks_the_holder_not_the_champion(facts):
    """DD leads GW1 on 30, CC takes it from GW2 and holds it to the end."""
    race = _league(facts, "Conf")["race"]
    assert race["distinct_leaders"] == ["CC", "DD"]
    assert race["wire_to_wire"] is False
    assert race["longest_spell_top"]["short_name"] == "CC"
    assert race["longest_spell_top"]["gameweeks"] == 2


# --- extremes ---------------------------------------------------------------

def test_highest_and_lowest_weeks(facts):
    extremes = _league(facts, "Prem")["extremes"]
    assert (extremes["highest_gameweek"]["short_name"],
            extremes["highest_gameweek"]["points"]) == ("AA", 30)
    assert (extremes["lowest_gameweek"]["short_name"],
            extremes["lowest_gameweek"]["points"]) == ("AA", 10)
    assert extremes["biggest_rise"]["change"] == 20      # AA 10 -> 30
    assert extremes["biggest_fall"]["change"] == -5      # BB 20 -> 15


def test_widest_gap_in_a_week(facts):
    gap = _league(facts, "Prem")["extremes"]["widest_gap_in_a_week"]
    assert gap["gameweek"] == 2 and gap["gap"] == 15     # AA 30 v BB 15


# --- draft ------------------------------------------------------------------

def test_best_pick_and_round_one_bust(facts):
    draft = _league(facts, "Prem")["draft"]
    assert draft["best_pick"]["player"] == "Hauler"
    assert draft["best_pick"]["points_realised_by_drafter"] == 30
    assert draft["round_one_bust"]["player"] == "Dud"
    assert draft["round_one_bust"]["player_total_points"] == 0
    assert draft["best_late_pick"]["round"] == 2


# --- moves ------------------------------------------------------------------

def test_points_since_measures_the_rest_of_the_season(facts):
    """The GW1 pickup banks 3 weeks x 10, the dud nothing, so the move is worth 30."""
    best = _league(facts, "Prem")["moves"]["best_transfer"]
    assert best["short_name"] == "AA"
    assert best["player_in_points_since"] == 30
    assert best["net_points_since"] == 30


def test_worst_miss_only_counts_being_beaten_to_a_player(facts):
    """`player out already gone` is an admin misfire, not one that got away."""
    moves = _league(facts, "Prem")["moves"]
    assert moves["worst_miss"]["short_name"] == "BB"
    assert moves["worst_miss"]["points_since"] == 20     # GW2 onward, not GW1
    assert moves["counts"]["failed"] == 2
    assert moves["counts"]["beaten_to_a_player"] == 1


def test_moves_are_scored_from_names_when_ids_are_missing():
    """
    2425's CSV transfers carry names and no element ids at all. Without a name
    fallback every move scored zero and the beats read as real findings.
    """
    nameless = _transfers().assign(element_in=None, element_out=None)
    facts = season_review_facts(
        season=SEASON, current_week=3,
        league_table=_league_table(), league_table_by_week=_by_week(),
        weekly_summary=_weekly_summary(), weekly_points=_weekly_points(),
        draft_picks=_draft_picks(), draft_performance=_draft_performance(),
        transfers=nameless, trades=_trades(),
    )
    moves = _league(facts, "Prem")["moves"]
    assert moves["best_transfer"]["player_in_points_since"] == 30
    assert moves["counts"]["valued"] == 3


def test_unidentifiable_moves_are_excluded_not_scored_zero():
    """A move naming nobody must not win 'worst transfer' on a phantom zero."""
    unknown = _transfers().assign(element_in=None, element_out=None,
                                  player_in="Nobody", player_out="Nobody")
    facts = season_review_facts(
        season=SEASON, current_week=3,
        league_table=_league_table(), league_table_by_week=_by_week(),
        weekly_summary=_weekly_summary(), weekly_points=_weekly_points(),
        draft_picks=_draft_picks(), draft_performance=_draft_performance(),
        transfers=unknown, trades=_trades(),
    )
    moves = _league(facts, "Prem")["moves"]
    assert moves["counts"]["valued"] == 0
    assert "best_transfer" not in moves
    assert "worst_transfer" not in moves
    assert "worst_miss" not in moves
    # The counts are still real even when nothing can be valued.
    assert moves["counts"]["successful"] == 1


def test_swaps_with_an_excluded_entry_are_counted_not_ranked(facts):
    """
    An excluded squad is a deliberate non-participant whose owner auto-accepts, so
    its players were free agents in all but name. The 99-point swap must not be
    reported as the league's best trade just because it scores highest.
    """
    moves = _league(facts, "Prem")["moves"]
    assert moves["best_trade"]["net_points"] == 20
    assert moves["best_trade"]["received_by"]["short_name"] == "BB"
    assert moves["trade_count"] == 1
    assert moves["trade_items_with_excluded_entry"] == 1


def test_excluded_entry_is_flagged_not_named():
    """trades_table labels an excluded entry with its bare id; prose must not print it."""
    from pipeline.transforms.narrative import _person
    assert _person({}, "Prem", "99999") == {
        "short_name": "99999", "name": None, "excluded_entry": True,
    }


def test_leagues_without_trades_omit_the_beat(facts):
    """2425 has no trades at all — the beat is absent, never a zero."""
    assert "best_trade" not in _league(facts, "Conf")["moves"]


# --- bench ------------------------------------------------------------------

def test_bench_losses(facts):
    bench = _league(facts, "Prem")["bench"]
    assert bench["worst_week"]["points_lost"] == 5       # fixed 5 a week
    assert {r["short_name"]: r["points_lost"] for r in bench["season_lost"]} == {
        "AA": 15, "BB": 15,
    }


# --- cross-league -----------------------------------------------------------

def test_cross_league_uses_means_not_totals(facts):
    """Totals would hand every week to the bigger league — 2425 ran 5 v 7."""
    cross = facts["cross_league"]
    assert cross["weekly"][0]["mean_points"] == {"Prem": 15.0, "Conf": 27.5}
    assert cross["weekly"][0]["winner"] == "Conf"
    # Conf takes GW1 on 27.5; Prem takes GW2 (22.5 v 17.5) and GW3 (25 v 17.5).
    assert cross["record"] == {"Prem": 2, "Conf": 1}


def test_champion_crossover_ranks_against_the_other_league(facts):
    """CC's 75 would top the Prem; AA's 70 would sit second in the Conf."""
    crossover = {c["champion_of"]: c for c in facts["cross_league"]["champion_crossover"]}
    assert crossover["Conf"]["would_rank"] == 1
    assert crossover["Prem"]["would_rank"] == 2


# --- output contract --------------------------------------------------------

def test_facts_are_json_serialisable(facts):
    """Written straight to JSON, so numpy scalars would break the build."""
    assert json.loads(json.dumps(facts))["season"] == "9900"
