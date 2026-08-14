"""Draft picks. Ported from notebook cell 10. Pure."""

import pandas as pd

PICK_COLUMNS = [
    "element", "short_name", "index", "pick", "web_name", "league_code", "position",
    "draft_rank", "now_cost", "selected_by_percent", "team", "team_name",
    "first_name", "last_name", "round",
]


def draft_picks_table(choices: dict, players: pd.DataFrame, table: pd.DataFrame,
                      *, league_code, drafters: int) -> pd.DataFrame:
    """
    One row per pick, with `index` renumbered and `round` derived.

    Excluded entries drafted for real, so removing their picks leaves gaps in the
    raw `index` (1, 2, 3, 4, 6, ... in 2526's Premiership, which ran 7 entries).
    Renumbering the survivors 1..N restores a contiguous sequence that divides
    cleanly into rounds. Verified against Draft Picks_2526.csv: 0 mismatches on
    both `index` and `round`, for both leagues.

    `drafters` comes from season config, replacing the notebook's hardcoded // 6
    which cannot handle 2425's 5/7 split.

    `pick` (position within the raw round) is left untouched, as the notebook did,
    so for 2526's Premiership it runs 1..7 while `index` runs 1..90.
    """
    # Before draft night the league exists but nobody has picked. Return the empty
    # frame with its real columns so downstream concats and merges still line up.
    if not (choices.get("choices") or []):
        return pd.DataFrame(columns=PICK_COLUMNS)

    picks = pd.json_normalize(choices["choices"])
    picks = picks.merge(players, left_on="element", right_on="id", how="inner")
    picks = picks.merge(table, left_on="entry", right_on="entry_id", how="inner")

    # renumber in true pick order, after the inner merge has dropped excluded entries
    picks = picks.sort_values("index", kind="stable").reset_index(drop=True)
    picks["index"] = range(1, len(picks) + 1)
    picks["round"] = ((picks["index"] - 1) // int(drafters)) + 1
    picks["league_code"] = league_code

    for column in ("index", "round", "pick"):
        picks[column] = pd.to_numeric(picks[column]).astype(int)

    return picks[PICK_COLUMNS]


def attach_pick_totals(picks: pd.DataFrame, weekly_points: pd.DataFrame) -> pd.DataFrame:
    """
    Attach two deliberately separate columns to each pick.

    `total_points`               the player's full season total, whoever owned him
    `points_realised_by_drafter` only the weeks the drafter who picked him held him

    The notebook stored the *second* quantity under the name `total_points`, which
    is why `Draft Picks_2526.csv` disagrees with the 2425 archive: the 2425 CSV
    carries the player's season total in that column, the 2526 one carries what
    the drafter banked. Pooling the two silently compares different quantities —
    it made a "points by draft round" table understate rounds 3-15 by a third,
    because late picks get dropped more often and so realise less of their total.

    Emitting both under honest names is the fix. `total_points` now means the same
    thing in every season and matches `players.total_points`; the old value keeps
    its meaning under an explicit name. Registered in validate.py's INTENTIONAL,
    since it deliberately no longer reproduces the 2526 CSV's column.

    Grouping matches `draft_pick_performance`, so the two tables agree by
    construction: weekly_points holds one row per league/gameweek/player, so
    summing over (league, player) is the season total and summing over
    (league, owner, player) is the owner's share.
    """
    season_total = (
        weekly_points.groupby(["league_code", "id"], as_index=False)["total_points"].sum()
        .rename(columns={"id": "element"})
    )
    realised = (
        weekly_points.groupby(["league_code", "short_name", "id"], as_index=False)["total_points"]
        .sum()
        .rename(columns={"id": "element", "total_points": "points_realised_by_drafter"})
    )

    frame = picks.merge(season_total, on=["league_code", "element"], how="left")
    frame = frame.merge(realised, on=["league_code", "short_name", "element"], how="left")
    frame["points_realised_by_drafter"] = frame["points_realised_by_drafter"].fillna(0)
    return frame
