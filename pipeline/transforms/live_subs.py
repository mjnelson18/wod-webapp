"""Provisional auto-subs for a gameweek still being played. Pure.

FPL applies auto-subs once the whole gameweek is over, so until then a starter
whose match has finished without him getting on the pitch sits in the XI on
zero. Nothing more can come from him, and the substitute FPL will bring on is
already determined by its published rules, so the swap is made here ahead of
time — only for the live week (the settled weeks take FPL's own `subs`), and
only where the outcome is settled: the starter's fixture is over and the
replacement has actually played.

The rules, as FPL states them: a player only comes on if he played; subs come
on in bench order; the XI must stay a legal formation (exactly one keeper, at
least 3 DEF, 2 MID and 1 FWD, at most 5 DEF, 5 MID and 3 FWD). The keeper rule
means a keeper can only ever be replaced by the bench keeper, and the bench
keeper can replace nobody else. Non-playing starters are dealt with in XI order
(keeper, defenders, midfielders, forwards, then slot), each taking the first
bench player who keeps the formation legal. `test_live_subs.py` replays this
over every auto-sub FPL made in the 2025/26 snapshot — 287 of them across 494
squads — and gets the same players on and off every time.
"""

import pandas as pd

STARTING_XI = 11
POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
FORMATION_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
FORMATION_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}


def _minutes(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _legal(counts: dict) -> bool:
    return all(FORMATION_MIN[p] <= counts.get(p, 0) <= FORMATION_MAX[p] for p in FORMATION_MIN)


def provisional_auto_subs(squad: list[dict]) -> list[tuple[int, int]]:
    """
    The swaps FPL will make for one drafter's squad, as (element_out, element_in).

    `squad` is one gameweek of one drafter: dicts with `element`, `place` (1-15),
    `position`, `minutes` and `fixture_finished`. A starter is out of the game
    when his fixture has finished and he has no minutes; a substitute is eligible
    when he has minutes. Unknown minutes (null) count as neither.
    """
    rows = sorted(squad, key=lambda r: int(r["place"]))
    starters = [r for r in rows if int(r["place"]) <= STARTING_XI]
    bench = [r for r in rows if int(r["place"]) > STARTING_XI]
    counts: dict[str, int] = {}
    for r in starters:
        counts[r["position"]] = counts.get(r["position"], 0) + 1

    def done(r) -> bool:
        return bool(r.get("fixture_finished")) is True and _minutes(r.get("minutes")) == 0

    def played(r) -> bool:
        return (_minutes(r.get("minutes")) or 0) > 0

    swaps: list[tuple[int, int]] = []
    used: set[int] = set()
    out = sorted((r for r in starters if done(r)),
                 key=lambda r: (POSITION_ORDER.get(r["position"], 9), int(r["place"])))
    for starter in out:
        for sub in bench:
            if int(sub["element"]) in used or not played(sub):
                continue
            after = dict(counts)
            after[starter["position"]] -= 1
            after[sub["position"]] = after.get(sub["position"], 0) + 1
            if not _legal(after):
                continue
            counts = after
            used.add(int(sub["element"]))
            swaps.append((int(starter["element"]), int(sub["element"])))
            break
    return swaps


def apply_provisional_subs(summary: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    """
    Swap `place` for the live gameweek's predictable auto-subs, per drafter.

    `originally_starting` is left alone, so a provisional sub looks exactly like
    a real one downstream: place says who is in the XI now, originally_starting
    says who was picked, and the difference is the substitution. Anything
    FPL's own processing later disagrees with is overwritten when the settled
    week's picks (with their `subs`) replace this build's.
    """
    needed = {"gameweek", "league_code", "short_name", "element", "place", "position",
              "minutes", "fixture_finished"}
    if summary.empty or not needed.issubset(summary.columns):
        return summary
    out = summary.copy()
    week = out["gameweek"] == int(gameweek)
    if not week.any():
        return out
    for (_, _), group in out[week].groupby(["league_code", "short_name"]):
        swaps = provisional_auto_subs(group.to_dict("records"))
        if not swaps:
            continue
        place_of = dict(zip(group["element"].astype(int), group["place"]))
        for element_out, element_in in swaps:
            idx_out = group.index[group["element"].astype(int) == element_out]
            idx_in = group.index[group["element"].astype(int) == element_in]
            out.loc[idx_out, "place"] = place_of[element_in]
            out.loc[idx_in, "place"] = place_of[element_out]
    return out
