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
    """Add each pick's season points, as the notebook did after building weekly points."""
    totals = (
        weekly_points.groupby(["league_code", "short_name", "id"], as_index=False)["total_points"]
        .sum()
    )
    return picks.merge(
        totals, left_on=["league_code", "short_name", "element"],
        right_on=["league_code", "short_name", "id"], how="left",
    )
