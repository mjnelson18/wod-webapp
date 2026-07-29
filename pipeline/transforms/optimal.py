"""Best-possible XI in hindsight — `optimal_points`.

Ported from notebook cell 12. Pure: squad frame in, squad frame out.

Formation rules: exactly 1 GKP, at least 3 DEF, at least 1 FWD, at least 2 MID,
11 players total.

Method: force the mandatory core (top 1 GKP, top 3 DEF, top 1 FWD by points),
then enumerate every size-6 completion from the remaining outfielders and keep
those satisfying the MID minimum. Forcing the top-k is sound — surplus DEF/FWD
can still be picked in the extra 6 — so this finds the true optimum.

Ties are AVERAGED, not broken. Both the mandatory selection and the final
6-player set spread weight uniformly across tied-optimal solutions, so
`optimal_weight` is fractional and so is `optimal_points`. 1555 of 6840 rows in
the 2526 CSV carry non-integer values, so a naive "best XI, arbitrary tie-break"
implementation will not reproduce the numbers.
"""

from itertools import combinations, product
from math import comb

import pandas as pd

REQUIRED_GKP = 1
REQUIRED_DEF = 3
REQUIRED_FWD = 1
MIN_MID = 2
STARTING_XI = 11


def _selection_outcomes_best(frame: pd.DataFrame, k: int):
    """
    Choose the k highest-scoring rows, splitting uniformly across ties at the cutoff.

    Returns [(index_tuple, probability), ...] summing to 1.
    """
    if k <= 0 or frame.empty:
        return [((), 1.0)]
    if k >= len(frame):
        return [(tuple(frame.index.tolist()), 1.0)]

    points = pd.to_numeric(frame["total_points"])
    cutoff = points.sort_values(ascending=False).iloc[k - 1]

    above = frame[points > cutoff]
    tied = frame[points == cutoff]
    above_index = tuple(above.index.tolist())
    needed = k - len(above)

    if needed <= 0:
        return [(above_index, 1.0)]

    tied_index = tied.index.tolist()
    if needed >= len(tied_index):
        return [(tuple(list(above_index) + tied_index), 1.0)]

    denominator = comb(len(tied_index), needed)
    return [
        (tuple(list(above_index) + list(chosen)), 1.0 / denominator)
        for chosen in combinations(tied_index, needed)
    ]


def calc_optimal_points(squad: pd.DataFrame) -> pd.DataFrame:
    """Add `optimal_weight` and `optimal_points` to one drafter's squad for one gameweek."""
    squad = squad.copy()
    points = pd.to_numeric(squad["total_points"])

    outcomes = (
        _selection_outcomes_best(squad[squad["position"] == "GKP"], REQUIRED_GKP),
        _selection_outcomes_best(squad[squad["position"] == "DEF"], REQUIRED_DEF),
        _selection_outcomes_best(squad[squad["position"] == "FWD"], REQUIRED_FWD),
    )

    weight = pd.Series(0.0, index=squad.index)
    extra = STARTING_XI - (REQUIRED_GKP + REQUIRED_DEF + REQUIRED_FWD)

    for (gk_sel, p_gk), (def_sel, p_def), (fwd_sel, p_fwd) in product(*outcomes):
        p_mandatory = p_gk * p_def * p_fwd
        mandatory = set(gk_sel) | set(def_sel) | set(fwd_sel)
        for index in mandatory:
            weight.loc[index] += p_mandatory

        # only one keeper may start, so the backup can never fill the extra slots
        remaining = squad.drop(list(mandatory))
        remaining = remaining[remaining["position"] != "GKP"]

        mids_in_mandatory = int((squad.loc[list(mandatory), "position"] == "MID").sum())
        mids_needed = max(0, MIN_MID - mids_in_mandatory)

        candidates = remaining.index.tolist()
        if len(candidates) < extra:
            continue  # not a valid 15-man squad; guard as the notebook did

        best_total = None
        best_sets: list[tuple] = []
        for chosen in combinations(candidates, extra):
            if mids_needed > 0:
                mids = int((remaining.loc[list(chosen), "position"] == "MID").sum())
                if mids < mids_needed:
                    continue
            total = float(points.loc[list(chosen)].sum())
            if best_total is None or total > best_total:
                best_total, best_sets = total, [chosen]
            elif total == best_total:
                best_sets.append(chosen)

        if not best_sets:
            best_sets = [tuple(remaining.nlargest(extra, "total_points").index.tolist())]

        share = p_mandatory / len(best_sets)
        for chosen in best_sets:
            for index in chosen:
                weight.loc[index] += share

    squad["optimal_weight"] = weight
    squad["optimal_points"] = points * squad["optimal_weight"]
    return squad


def add_optimal_points(frame: pd.DataFrame, *, group_keys=("short_name", "gameweek")) -> pd.DataFrame:
    """Apply `calc_optimal_points` per squad-week and return element-level results."""
    pieces = []
    for _, squad in frame.groupby(list(group_keys), sort=False):
        pieces.append(calc_optimal_points(squad))
    if not pieces:
        return frame.assign(optimal_weight=0.0, optimal_points=0.0)
    return pd.concat(pieces)
