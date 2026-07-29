"""optimal_points: formation rules and tie-averaging.

The tie-averaging is the part a naive port gets wrong, so it is tested directly
rather than only through the regression comparison.
"""

import pandas as pd
import pytest

from pipeline.transforms.optimal import calc_optimal_points


def squad(**counts) -> pd.DataFrame:
    """Build a squad from {position: [points, ...]}."""
    rows = []
    element = 0
    for position, values in counts.items():
        for value in values:
            rows.append({"element": element, "position": position, "total_points": value})
            element += 1
    return pd.DataFrame(rows)


def typical(gkp=(6, 1), dfd=(8, 7, 6, 5, 4), mid=(9, 8, 7, 2, 1), fwd=(10, 3, 2)):
    return squad(GKP=list(gkp), DEF=list(dfd), MID=list(mid), FWD=list(fwd))


def test_selects_exactly_eleven():
    out = calc_optimal_points(typical())
    assert out["optimal_weight"].sum() == pytest.approx(11.0)


def test_respects_formation_minimums():
    out = calc_optimal_points(typical())
    picked = out[out["optimal_weight"] > 0]
    counts = picked["position"].value_counts()
    assert counts.get("GKP", 0) == 1
    assert counts.get("DEF", 0) >= 3
    assert counts.get("FWD", 0) >= 1
    assert counts.get("MID", 0) >= 2


def test_only_one_keeper_can_start():
    """Even when both keepers outscore everyone, only one may be selected."""
    out = calc_optimal_points(squad(
        GKP=[50, 49], DEF=[8, 7, 6, 5, 4], MID=[9, 8, 7, 2, 1], FWD=[10, 3, 2],
    ))
    keepers = out[(out["position"] == "GKP") & (out["optimal_weight"] > 0)]
    assert keepers["optimal_weight"].sum() == pytest.approx(1.0)


def test_optimal_is_at_least_as_good_as_actual_best_eleven():
    frame = typical()
    out = calc_optimal_points(frame)
    naive_top_11 = frame.nlargest(11, "total_points")["total_points"].sum()
    # the optimum is constrained, so it can be lower than an unconstrained top 11,
    # but never higher
    assert out["optimal_points"].sum() <= naive_top_11 + 1e-9


def test_ties_are_shared_not_broken():
    """
    Five equal defenders competing for exactly three slots take 0.6 each, rather
    than one arbitrary trio taking all of it.

    The midfielders and forwards score high enough to claim every one of the extra
    six slots, so no defender beyond the mandatory three can sneak in — which is
    what makes this a real tie rather than "everyone starts anyway".
    """
    frame = squad(
        GKP=[5, 1],
        DEF=[9, 9, 9, 9, 9],
        MID=[20, 20, 20, 20, 20],
        FWD=[20, 20, 20],
    )
    out = calc_optimal_points(frame)
    defenders = out[out["position"] == "DEF"]["optimal_weight"]
    assert all(0 < w < 1 for w in defenders), f"expected shared weight, got {defenders.tolist()}"
    assert defenders.sum() == pytest.approx(3.0)   # three slots split five ways
    assert all(w == pytest.approx(0.6) for w in defenders)
    assert out["optimal_weight"].sum() == pytest.approx(11.0)


def test_fractional_points_follow_weight():
    frame = squad(GKP=[5, 1], DEF=[9, 9, 9, 9, 1], MID=[7, 7, 7], FWD=[8, 1, 1])
    out = calc_optimal_points(frame)
    expected = out["total_points"] * out["optimal_weight"]
    assert out["optimal_points"].tolist() == pytest.approx(expected.tolist())


def test_all_equal_squad_shares_by_position_not_uniformly():
    """
    15 identical players: weight is uniform *within* a position but not across them,
    because the mandatory core favours DEF and FWD.

    A defender takes 3/5 from the mandatory trio plus a share of the extra six drawn
    from the 9 non-mandatory outfielders: 0.6 + 0.4 * 6/9. A forward takes
    1/3 + 2/3 * 6/9. A midfielder is never mandatory, so it is only 6/9.
    """
    out = calc_optimal_points(squad(
        GKP=[4, 4], DEF=[4, 4, 4, 4, 4], MID=[4, 4, 4, 4, 4], FWD=[4, 4, 4],
    ))
    assert out["optimal_weight"].sum() == pytest.approx(11.0)

    weight_of = lambda pos: out[out["position"] == pos]["optimal_weight"].tolist()
    expected = {
        "GKP": 1 / 2,
        "DEF": 0.6 + 0.4 * 6 / 9,
        "FWD": 1 / 3 + (2 / 3) * (6 / 9),
        "MID": 6 / 9,
    }
    for position, value in expected.items():
        # approx, not nunique: weights accumulate share-by-share so equal players
        # can land a float ULP apart
        assert weight_of(position) == pytest.approx([value] * len(weight_of(position))), position
