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


# Columns attach_prior_season adds. Named for what they are: last season's facts
# about the footballer, not about the pick.
PRIOR_COLUMNS = ["prior_points", "prior_team_name", "new_to_pl", "moved_club"]


def attach_prior_season(picks: pd.DataFrame, players: pd.DataFrame,
                        prior_players: pd.DataFrame | None) -> pd.DataFrame:
    """
    Attach last season's record for each drafted footballer.

    `prior_points`      his total in the previous season, NaN if he wasn't in it
    `prior_team_name`   the club he finished the previous season at
    `new_to_pl`         True if he has no previous-season record at all
    `moved_club`        True if he has one and it names a different club

    Two independent sources, because neither is sufficient alone.

    `prior_points` and `new_to_pl` come from the picks' own `last_minutes` /
    `last_points`, which the caller takes from the current draft bootstrap. Before
    GW1 those fields still describe *last* season — that is simply what FPL serves
    in the pre-season window — so they are an exact, join-free record of what each
    footballer did last year. Nothing can go wrong with a name here.

    `prior_team_name`, and therefore `moved_club`, genuinely need the previous
    season's table, and are joined on `web_name`. Not on `element`: FPL reassigns
    element ids every season, and of the 19 ids present in both the 2425 and 2526
    drafts not one refers to the same footballer (id 16 is Rice in 2425 and Saka in
    2526). Joining on it yields a table that looks plausible and is entirely wrong.

    But `web_name` is not fully stable either, which is why it is not trusted for
    the other two columns. FPL adds an initial only when names collide *within* a
    season, so a player's web_name changes when his rivals do: Mateus Fernandes was
    `M.Fernandes` (WHU) in 2526 and is plain `Fernandes` (TOT) in 2627. A pure name
    join therefore loses him — and would have called a 135-point player a Premier
    League debutant. Where the name doesn't match, `moved_club` is left null, which
    says "we can't tell" rather than asserting he stayed put.

    `prior_players` is None for the oldest season in the archive, which has nothing
    behind it. Then `moved_club` is null throughout — "we don't know" is not the
    same claim as "nobody moved".
    """
    frame = picks.copy()

    # `players` is this season's table, so joining on the element id is safe here —
    # ids are only unstable *between* seasons. PICK_COLUMNS deliberately doesn't
    # carry minutes or points, so they're taken from the source frame rather than
    # widening every pick row with columns only this function needs.
    record = (
        players[["id", "minutes", "total_points"]]
        .rename(columns={"id": "element", "total_points": "prior_points",
                         "minutes": "prior_minutes"})
    )
    frame = frame.merge(record, on="element", how="left")

    minutes = pd.to_numeric(frame["prior_minutes"], errors="coerce").fillna(0)
    points = pd.to_numeric(frame["prior_points"], errors="coerce").fillna(0)
    frame["prior_points"] = points
    frame = frame.drop(columns=["prior_minutes"])

    # No minutes and no points is necessary but not sufficient: Marcus Rashford
    # scored nothing last season because he spent it on loan abroad, and calling
    # him new to the Premier League would be nonsense. So a debutant must also be
    # absent from last season's player list entirely. Both are checked for points
    # and minutes because a substitute can score without starting, and a defender
    # can play 3000 minutes for very few points.
    no_record = (minutes <= 0) & (points <= 0)

    if prior_players is None or not len(prior_players):
        # Nothing behind this season, so we can neither confirm a debutant nor
        # place anyone's old club.
        frame["new_to_pl"] = pd.NA
        frame["prior_team_name"] = pd.NA
        frame["moved_club"] = pd.NA
        return frame

    # One row per name: a footballer appears once per league in players.json, so
    # the same name arrives up to twice carrying identical values.
    prior = (
        prior_players[["web_name", "team_name"]]
        .drop_duplicates(subset="web_name", keep="first")
        .rename(columns={"team_name": "prior_team_name"})
    )

    frame = frame.merge(prior, on="web_name", how="left")
    matched = frame["prior_team_name"].notna()
    frame["new_to_pl"] = no_record.values & ~matched

    frame["moved_club"] = pd.NA
    frame.loc[matched, "moved_club"] = (
        frame.loc[matched, "prior_team_name"] != frame.loc[matched, "team_name"]
    )
    # A debutant has no prior club to differ from, so that is a real False.
    frame.loc[frame["new_to_pl"], "moved_club"] = False
    return frame
