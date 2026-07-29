"""Pure transforms: raw JSON in, tables out. No network, no file writes.

This is what makes them testable against the historical CSVs.
"""

from .draft_picks import attach_pick_totals, draft_picks_table
from .fixtures import fixtures_from_fantasy, fixtures_from_live
from .league import (
    entry_ids,
    form_table,
    league_gaps,
    league_table,
    live_league_table,
)
from .moves import (
    finalise_trades,
    finalise_transfers,
    trades_table,
    transfers_table,
)
from .optimal import add_optimal_points, calc_optimal_points
from .players import bootstrap_team_ids_agree, players_table, teams_table
from .weekly import attach_fixtures, weekly_tables

__all__ = [
    "add_optimal_points",
    "attach_fixtures",
    "attach_pick_totals",
    "bootstrap_team_ids_agree",
    "calc_optimal_points",
    "draft_picks_table",
    "entry_ids",
    "finalise_trades",
    "finalise_transfers",
    "fixtures_from_fantasy",
    "fixtures_from_live",
    "form_table",
    "league_gaps",
    "league_table",
    "live_league_table",
    "players_table",
    "teams_table",
    "trades_table",
    "transfers_table",
    "weekly_tables",
]
