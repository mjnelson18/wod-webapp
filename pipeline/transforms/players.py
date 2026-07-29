"""Player and team lookups. Ported from notebook cells 5 and 7. Pure."""

import pandas as pd

PLAYER_COLUMNS = [
    "id", "web_name", "team", "team_name", "position", "total_points",
    "goals_scored", "assists", "bonus", "clean_sheets", "minutes", "draft_rank",
]


def teams_table(bootstrap_draft: dict) -> pd.DataFrame:
    """team id -> short name, from the draft bootstrap."""
    teams = pd.json_normalize(bootstrap_draft["teams"])[["id", "short_name"]]
    teams.columns = ["team", "team_name"]
    return teams


def players_table(bootstrap_draft: dict, bootstrap_fantasy: dict | None = None) -> pd.DataFrame:
    """
    One row per footballer.

    `now_cost` and `selected_by_percent` come from the fantasy bootstrap. The
    notebook merged the two bootstraps with how="inner" on `id`, which is only
    safe while both hosts serve the same season — element ids are reassigned every
    year. The merge is left here and callers pass bootstrap_fantasy=None when the
    hosts disagree, leaving the columns null for CSV backfill instead of joining
    2526 players onto 2627 ids.
    """
    elements = pd.json_normalize(bootstrap_draft["elements"])
    players = elements[[
        "id", "web_name", "element_type", "team", "total_points", "goals_scored",
        "assists", "bonus", "clean_sheets", "minutes", "draft_rank",
    ]].copy()

    positions = pd.json_normalize(bootstrap_draft["element_types"])[["id", "singular_name_short"]]
    positions.columns = ["element_type", "position"]
    players = players.merge(positions, on="element_type", how="inner")

    players = players.merge(teams_table(bootstrap_draft), on="team", how="inner")
    players = players[PLAYER_COLUMNS]

    if bootstrap_fantasy is not None:
        fantasy = pd.json_normalize(bootstrap_fantasy["elements"])[
            ["id", "selected_by_percent", "now_cost"]
        ].copy()
        fantasy["now_cost"] = pd.to_numeric(fantasy["now_cost"]) / 10
        players = players.merge(fantasy, on="id", how="inner")
    else:
        players["selected_by_percent"] = pd.NA
        players["now_cost"] = pd.NA

    return players


def bootstrap_start_year(bootstrap_draft: dict) -> int | None:
    """
    Calendar year of the season the payload describes, from GW1's deadline.

    Used to catch a payload from the wrong season — see `season_start_year`.
    """
    events = bootstrap_draft.get("events", {})
    rows = events.get("data", events) if isinstance(events, dict) else events
    for event in sorted(rows or [], key=lambda e: e.get("id", 0)):
        deadline = event.get("deadline_time")
        if deadline:
            return int(str(deadline)[:4])
    return None


def season_start_year(season_id: str) -> int:
    """'2627' -> 2026. The season id's first half is the year it kicks off in."""
    return 2000 + int(str(season_id)[:2])


def bootstrap_team_ids_agree(bootstrap_draft: dict, bootstrap_fantasy: dict) -> bool:
    """
    Sanity check for the hybrid-payload trap (docs/notebook-recon.md 6.1b).

    The snapshot's draft bootstrap carries 2526 `teams` and 2526 stats but 2627
    `elements[].team` ids, so joining element -> team inside it silently returns
    the wrong club for 39% of players. Compare the two hosts' team lists: if they
    disagree, element->team ids cannot be trusted.
    """
    draft = {t["short_name"] for t in bootstrap_draft.get("teams", [])}
    fantasy = {t["short_name"] for t in bootstrap_fantasy.get("teams", [])}
    return bool(draft) and draft == fantasy
