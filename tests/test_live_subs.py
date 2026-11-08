"""Provisional auto-subs: the rules on small squads, then against FPL's own record.

The 2025/26 snapshot holds every entry's picks for every gameweek *with* the
`subs` FPL processed, and the live payloads hold everyone's minutes. Replaying
the rules over those 494 squads and getting the same players on and off is the
proof that the live week's provisional subs are what FPL will do at the final
whistle. Who-replaced-whom is not compared: FPL re-sorts the XI by position
after subbing, so the original slot order (which decides the pairing) is gone
from the payload — and the pairing changes no points.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.transforms.live_subs import apply_provisional_subs, provisional_auto_subs

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "reference" / "raw_2526"


def squad(places, minutes=None, finished=None):
    """places: list of (element, place, position). minutes/finished keyed by element."""
    minutes = minutes or {}
    finished = finished or {}
    return [{"element": e, "place": p, "position": pos,
             "minutes": minutes.get(e, 90), "fixture_finished": finished.get(e, True)}
            for e, p, pos in places]


# A 3-4-3 with the usual bench: GK, then three outfielders.
XI = [(1, 1, "GKP"), (2, 2, "DEF"), (3, 3, "DEF"), (4, 4, "DEF"),
      (5, 5, "MID"), (6, 6, "MID"), (7, 7, "MID"), (8, 8, "MID"),
      (9, 9, "FWD"), (10, 10, "FWD"), (11, 11, "FWD")]
BENCH = [(12, 12, "GKP"), (13, 13, "DEF"), (14, 14, "MID"), (15, 15, "FWD")]


def test_everyone_played_means_no_subs():
    assert provisional_auto_subs(squad(XI + BENCH)) == []


def test_a_finished_starter_on_zero_is_replaced_in_bench_order():
    # MID 5 blanked; bench 13 (DEF) comes on first because it keeps 4-3-3 legal.
    assert provisional_auto_subs(squad(XI + BENCH, minutes={5: 0})) == [(5, 13)]


def test_a_starter_still_to_play_is_left_alone():
    out = provisional_auto_subs(squad(XI + BENCH, minutes={5: 0}, finished={5: False}))
    assert out == []


def test_unknown_minutes_are_neither_out_nor_eligible():
    assert provisional_auto_subs(squad(XI + BENCH, minutes={5: None})) == []
    assert provisional_auto_subs(squad(XI + BENCH, minutes={5: 0, 13: None})) == [(5, 14)]


def test_a_substitute_must_have_played():
    assert provisional_auto_subs(squad(XI + BENCH, minutes={5: 0, 13: 0})) == [(5, 14)]


def test_the_formation_must_stay_legal():
    # With only three defenders a DEF out can't take the MID or the FWD, so when
    # the bench DEF didn't play nobody comes on.
    assert provisional_auto_subs(squad(XI + BENCH, minutes={2: 0, 13: 0})) == []
    # Two FWD out of a 3-4-3: the DEF takes the first (4-4-2), the MID the second
    # (4-5-1), both legal — bench order, and the bench FWD isn't reached.
    assert provisional_auto_subs(squad(XI + BENCH, minutes={9: 0, 10: 0})) == [(9, 13), (10, 14)]


def test_starters_are_dealt_with_in_xi_order():
    # DEF 2 and FWD 9 both out, bench 13 DEF then 14 MID. The defender is handled
    # first and takes the bench DEF (the MID would leave two defenders); the
    # forward then takes the MID — 3-5-2. In slot order alone the same, but the
    # position comes first because FPL re-sorts the XI by position.
    xi = [(9, 2, "FWD"), (2, 9, "DEF")] + [p for p in XI if p[0] not in (2, 9)]
    assert provisional_auto_subs(squad(xi + BENCH, minutes={2: 0, 9: 0})) == [(2, 13), (9, 14)]


def test_only_the_bench_keeper_replaces_the_keeper():
    assert provisional_auto_subs(squad(XI + BENCH, minutes={1: 0})) == [(1, 12)]
    assert provisional_auto_subs(squad(XI + BENCH, minutes={1: 0, 12: 0})) == []
    # ...and the bench keeper replaces nobody else.
    assert provisional_auto_subs(squad(XI + BENCH, minutes={5: 0, 13: 0, 14: 0, 15: 0})) == []


def test_apply_swaps_places_for_the_live_week_only():
    rows = []
    for gw in (4, 5):
        for e, p, pos in XI + BENCH:
            rows.append({"gameweek": gw, "league_code": "L1", "short_name": "AA", "element": e,
                         "place": p, "position": pos, "minutes": 0 if e == 5 else 90,
                         "fixture_finished": True, "originally_starting": 1 if p <= 11 else 0})
    out = apply_provisional_subs(pd.DataFrame(rows), 5)
    gw5 = out[out["gameweek"] == 5].set_index("element")["place"]
    gw4 = out[out["gameweek"] == 4].set_index("element")["place"]
    assert (gw5[5], gw5[13]) == (13, 5)
    assert (gw4[5], gw4[13]) == (5, 13)
    # the picked lineup is untouched: that is how the frontend spots the sub
    assert out.loc[(out["gameweek"] == 5) & (out["element"] == 13), "originally_starting"].item() == 0


# --- the oracle: every auto-sub FPL made in 2025/26 ---------------------------

@pytest.mark.skipif(not (SNAPSHOT / "entry").exists(), reason="2526 snapshot not present")
def test_replaying_the_rules_reproduces_every_fpl_auto_sub_of_2526():
    bootstrap = json.loads((SNAPSHOT / "bootstrap_static_draft.json").read_text(encoding="utf-8"))
    short = {t["id"]: t["singular_name_short"] for t in bootstrap["element_types"]}
    position = {e["id"]: short[e["element_type"]] for e in bootstrap["elements"]}

    mismatches, squads, real_subs = [], 0, 0
    for gameweek in range(1, 39):
        live = json.loads((SNAPSHOT / "event" / f"live_gw{gameweek:02d}.json").read_text(encoding="utf-8"))
        minutes = {int(e): d["stats"].get("minutes", 0) for e, d in live["elements"].items()}
        for picks_file in sorted(SNAPSHOT.glob(f"entry/*/gw{gameweek:02d}.json")):
            payload = json.loads(picks_file.read_text(encoding="utf-8"))
            if not payload.get("picks"):
                continue
            squads += 1
            expected = sorted((s["element_out"], s["element_in"]) for s in payload.get("subs") or [])
            real_subs += len(expected)
            # The payload's slot order is *after* FPL's subs (the sub already sits
            # in the XI), so undo each recorded swap to recover the picked lineup.
            place = {p["element"]: p["position"] for p in payload["picks"]}
            for element_out, element_in in expected:
                place[element_out], place[element_in] = place[element_in], place[element_out]
            # Every fixture is over in a finished season, so "done" is minutes alone.
            rows = [{"element": e, "place": pl, "position": position.get(e, "MID"),
                     "minutes": minutes.get(e, 0), "fixture_finished": True}
                    for e, pl in place.items()]
            got = sorted(provisional_auto_subs(rows))
            on_off = lambda pairs: (sorted(o for o, _ in pairs), sorted(i for _, i in pairs))  # noqa: E731
            if on_off(got) != on_off(expected):
                mismatches.append((picks_file.parent.name, gameweek, expected, got))

    assert squads > 400 and real_subs > 250, (squads, real_subs)
    assert not mismatches, f"{len(mismatches)} of {squads} squads differ, e.g. {mismatches[:5]}"
