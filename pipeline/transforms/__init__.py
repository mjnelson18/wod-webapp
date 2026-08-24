"""Pure transforms: raw JSON in, tables out. No network, no file writes.

This is what makes them testable against the historical CSVs.
"""

from .draft_picks import attach_pick_totals, attach_prior_season, draft_picks_table
from .fixtures import fixtures_from_fantasy, fixtures_from_live
from .league import (
    H2H_MATCH_COLUMNS,
    H2H_TABLE_COLUMNS,
    entry_ids,
    form_table,
    head_to_head_matches,
    head_to_head_table,
    is_head_to_head,
    league_gaps,
    league_table,
    live_league_table,
    reconcile_head_to_head,
)
from .moves import (
    finalise_trades,
    finalise_transfers,
    trades_table,
    transfers_table,
)
from .narrative import season_review_facts
from .optimal import add_optimal_points, calc_optimal_points
from .summaries import (
    available_form_players,
    draft_pick_performance,
    draft_share,
    draft_share_by_gameweek,
    fixture_lookahead,
    formations,
    lorenz_curve,
    player_usage,
    points_distribution,
    season_summary,
    season_summary_by_gameweek,
)
from .players import (
    bootstrap_start_year,
    bootstrap_team_ids_agree,
    players_table,
    season_start_year,
    teams_table,
)
from .weekly import attach_fixtures, weekly_tables

__all__ = [
    "add_optimal_points",
    "attach_fixtures",
    "attach_pick_totals",
    "available_form_players",
    "bootstrap_start_year",
    "bootstrap_team_ids_agree",
    "draft_pick_performance",
    "draft_share",
    "draft_share_by_gameweek",
    "fixture_lookahead",
    "formations",
    "lorenz_curve",
    "player_usage",
    "points_distribution",
    "season_review_facts",
    "season_summary",
    "season_summary_by_gameweek",
    "calc_optimal_points",
    "attach_prior_season",
    "draft_picks_table",
    "entry_ids",
    "finalise_trades",
    "finalise_transfers",
    "fixtures_from_fantasy",
    "fixtures_from_live",
    "H2H_MATCH_COLUMNS",
    "H2H_TABLE_COLUMNS",
    "form_table",
    "head_to_head_matches",
    "head_to_head_table",
    "is_head_to_head",
    "league_gaps",
    "league_table",
    "live_league_table",
    "reconcile_head_to_head",
    "players_table",
    "season_start_year",
    "teams_table",
    "trades_table",
    "transfers_table",
    "weekly_tables",
]
