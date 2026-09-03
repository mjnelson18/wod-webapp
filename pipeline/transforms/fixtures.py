"""Fixtures, aggregated to one row per team per gameweek. Ported from notebook cell 8. Pure.

Two builders:

* `fixtures_from_fantasy` — the notebook's path, using fantasy/fixtures/. Carries
  `team_difficulty`, which only that endpoint provides.
* `fixtures_from_live` — the same shape rebuilt from the draft-side
  event/{gw}/live payloads, which carry team_h/team_a/scores/kickoff_time. Needed
  because fantasy.premierleague.com had already rolled to 2627 when the 2526
  snapshot was taken, so 2526 fixtures are not refetchable from it. Difficulty is
  unavailable this way and is left null for CSV backfill.
"""

import pandas as pd

TEAM_GW_COLUMNS = [
    "gameweek", "team", "gameweek_matches", "opposition", "home_away",
    "team_score", "opposition_score", "team_difficulty", "opposition_difficulty",
    "kickoff_time_first",
]


def _ordered_join(values, separator="-", dedupe=True):
    """Join preserving order; optionally drop repeats (ARS-LIV vs HA)."""
    items = [str(v) for v in values.tolist()]
    if not dedupe:
        return separator.join(items)
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return separator.join(out)


def _aggregate_team_gameweeks(per_team: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per (gameweek, team) so double gameweeks combine."""
    aggregated = (
        per_team.sort_values(["gameweek", "team", "kickoff_time"])
        .groupby(["gameweek", "team"], as_index=False)
        .agg(
            gameweek_matches=("opposition", "size"),
            opposition=("opposition", lambda s: _ordered_join(s, "-", dedupe=True)),
            home_away=("home_away", lambda s: _ordered_join(s, "", dedupe=False)),
            team_score=("team_score", "mean"),
            opposition_score=("opposition_score", "mean"),
            team_difficulty=("team_difficulty", "mean"),
            opposition_difficulty=("opposition_difficulty", "mean"),
            kickoff_time_first=("kickoff_time", "min"),
        )
        .sort_values(["gameweek", "team"])
        .reset_index(drop=True)
    )
    return aggregated[TEAM_GW_COLUMNS]


def _explode_home_away(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per team per fixture, from one row per fixture."""
    shared = ["gameweek", "kickoff_time"]
    home = frame.assign(
        team=frame["team_h"], opposition=frame["team_a"], home_away="H",
        team_score=frame["team_h_score"], opposition_score=frame["team_a_score"],
        team_difficulty=frame["team_h_difficulty"],
        opposition_difficulty=frame["team_a_difficulty"],
    )
    away = frame.assign(
        team=frame["team_a"], opposition=frame["team_h"], home_away="A",
        team_score=frame["team_a_score"], opposition_score=frame["team_h_score"],
        team_difficulty=frame["team_a_difficulty"],
        opposition_difficulty=frame["team_h_difficulty"],
    )
    columns = shared + ["team", "opposition", "home_away", "team_score",
                        "opposition_score", "team_difficulty", "opposition_difficulty"]
    return pd.concat([home[columns], away[columns]], ignore_index=True)


def fixtures_from_fantasy(raw_fixtures: list, teams: pd.DataFrame):
    """Returns (per-fixture frame, per-team-gameweek frame)."""
    frame = pd.json_normalize(raw_fixtures)[[
        "event", "team_a", "team_h", "team_a_score", "team_h_score",
        "team_a_difficulty", "team_h_difficulty", "kickoff_time",
    ]].copy()
    # A fixture that has not been played has no score, and that is NOT nil-nil. Filling with
    # zero made every future fixture look like a completed goalless draw — 753 of 760 rows in
    # the 2026/27 output at GW3 — so the app could not tell a fixture still to come from one
    # that ended 0-0, and future fixtures stopped rendering. Nullable Int64 keeps the integer
    # dtype and carries the gap through to JSON null.
    frame["team_h_score"] = pd.to_numeric(frame["team_h_score"], errors="coerce").astype("Int64")
    frame["team_a_score"] = pd.to_numeric(frame["team_a_score"], errors="coerce").astype("Int64")

    names = teams.set_index("team")["team_name"]
    frame["team_a"] = frame["team_a"].map(names)
    frame["team_h"] = frame["team_h"].map(names)
    frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True, errors="coerce")
    frame = frame.rename(columns={"event": "gameweek"})

    return frame, _aggregate_team_gameweeks(_explode_home_away(frame))


def fixtures_from_live(live_by_gameweek: dict[int, dict], teams: pd.DataFrame):
    """
    Rebuild fixtures from draft-side event/{gw}/live payloads.

    `team_difficulty` and `opposition_difficulty` are null — the draft API does not
    expose FPL's difficulty ratings.
    """
    rows = []
    for gameweek, payload in sorted(live_by_gameweek.items()):
        for fixture in (payload or {}).get("fixtures", []) or []:
            rows.append({
                "gameweek": fixture.get("event", gameweek),
                "team_h": fixture.get("team_h"),
                "team_a": fixture.get("team_a"),
                "team_h_score": fixture.get("team_h_score"),
                "team_a_score": fixture.get("team_a_score"),
                "team_h_difficulty": pd.NA,
                "team_a_difficulty": pd.NA,
                "kickoff_time": fixture.get("kickoff_time"),
            })
    if not rows:
        empty = pd.DataFrame(columns=TEAM_GW_COLUMNS)
        return pd.DataFrame(), empty

    frame = pd.DataFrame(rows)
    # Same rule as `fixtures_from_fantasy` — an unplayed fixture keeps a null score.
    frame["team_h_score"] = pd.to_numeric(frame["team_h_score"], errors="coerce").astype("Int64")
    frame["team_a_score"] = pd.to_numeric(frame["team_a_score"], errors="coerce").astype("Int64")

    names = teams.set_index("team")["team_name"]
    frame["team_h"] = frame["team_h"].map(names)
    frame["team_a"] = frame["team_a"].map(names)
    frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True, errors="coerce")

    return frame, _aggregate_team_gameweeks(_explode_home_away(frame))
