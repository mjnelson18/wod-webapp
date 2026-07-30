"""Orchestrator: decide what to fetch -> fetch -> transform -> write JSON.

    python -m pipeline.build --season 2526 --source snapshot
    python -m pipeline.build --season 2627                 # incremental live build
    python -m pipeline.build --season 2627 --full          # ignore cache

All season-variable values come from pipeline/config. All transformation logic
lives in pipeline/transforms and is pure; this module does the I/O.
"""

import argparse
import json
import sys

import pandas as pd

from . import paths
from .adapters import backfill_difficulty, backfill_players
from .config import get_season, is_configured
from .fetchers import build_source
from .fetchers.http import RateLimited
from .transforms import (
    attach_fixtures,
    attach_pick_totals,
    available_form_players,
    bootstrap_start_year,
    bootstrap_team_ids_agree,
    draft_pick_performance,
    draft_picks_table,
    draft_share,
    draft_share_by_gameweek,
    entry_ids,
    finalise_trades,
    finalise_transfers,
    fixtures_from_fantasy,
    fixtures_from_live,
    form_table,
    formations,
    league_table,
    live_league_table,
    lorenz_curve,
    player_usage,
    players_table,
    points_distribution,
    season_review_facts,
    season_start_year,
    season_summary,
    season_summary_by_gameweek,
    teams_table,
    trades_table,
    transfers_table,
    weekly_tables,
)


def _current_week(source, season) -> int:
    game = source.game() or {}
    week = game.get("current_event")
    return int(week) if week else season.total_gameweeks


def build_tables(season_id: str, *, source_kind: str | None = None, force: bool = False,
                 gameweeks: int | None = None, verbose: bool = True) -> dict:
    """Run the whole pipeline for one season and return canonical tables."""
    season = get_season(season_id)
    if season.default_source == "csv" and source_kind is None:
        # No raw input exists (2425) — build the archive from the historical CSVs.
        from .adapters import build_csv_tables
        return build_csv_tables(season, verbose=verbose)
    if season.default_source == "live" and not is_configured(season):
        raise SystemExit(
            f"{season.season} has <FILL IN> league codes in pipeline/config/seasons.py"
        )

    source = build_source(season, source=source_kind, force=force)
    current_week = gameweeks or _current_week(source, season)
    weeks = list(range(1, current_week + 1))
    say = print if verbose else (lambda *a, **k: None)
    say(f"{season.season}: gameweeks 1..{current_week}")

    bootstrap_draft = source.bootstrap_draft()
    bootstrap_fantasy = source.bootstrap_fantasy()

    # Refuse to label one season's data as another's. The FPL API serves only the
    # current season, and the changeover is not instantaneous — so a build started
    # around the rollover could otherwise fetch last season and write it out under
    # this season's id, silently and irreversibly.
    expected = season_start_year(season.season)
    actual = bootstrap_start_year(bootstrap_draft)
    if actual is not None and actual != expected:
        raise SystemExit(
            f"season mismatch: building {season.season} (expects GW1 in {expected}) "
            f"but the draft API returned a season starting {actual}. "
            f"The API has probably not rolled over yet — do not overwrite "
            f"{season.season} with {actual}/{actual + 1} data."
        )

    teams = teams_table(bootstrap_draft)

    # The snapshot's draft bootstrap carries 2526 teams/stats but 2627
    # element->team ids (docs/notebook-recon.md 6.1b). When the two hosts'
    # team lists disagree the payloads are from different seasons, so the
    # fantasy merge would join across seasons and element->team is untrustworthy.
    hosts_agree = bootstrap_team_ids_agree(bootstrap_draft, bootstrap_fantasy)
    if not hosts_agree:
        say("  ! bootstrap hosts disagree on teams -> fantasy columns deferred to CSV backfill")

    players = players_table(bootstrap_draft, bootstrap_fantasy if hosts_agree else None)

    # Correct club/cost columns before anything downstream uses them. team_name
    # feeds the fixture join, so an uncorrected club silently attaches the wrong
    # fixture to every row for that player.
    if season.csv_backfill:
        players = backfill_players(players, season)
        say(f"  backfilled from CSV: {', '.join(season.csv_backfill)}")

    # event/{gw}/live, shared across both leagues — fetch once
    live = {gw: source.event_live(gw) for gw in weeks}

    if hosts_agree:
        _, fixtures_by_team = fixtures_from_fantasy(source.fixtures(), teams)
    else:
        say("  rebuilding fixtures from draft-side event live payloads")
        _, fixtures_by_team = fixtures_from_live(live, teams)
    if season.csv_backfill:
        fixtures_by_team = backfill_difficulty(fixtures_by_team, season)

    summaries, points_frames, picks_frames = [], [], []
    standings_frames, transfers_frames, trades_frames = [], [], []

    for league in season.leagues:
        say(f"  {league.code} ({league.league_code})")
        details = source.league_details(league.league_code)
        standings = league_table(details, league_code=league.code,
                                exclude_entries=league.exclude_entries)
        names = entry_ids(details, exclude_entries=league.exclude_entries)

        picks = draft_picks_table(
            source.draft_choices(league.league_code), players, standings,
            league_code=league.code, drafters=league.size,
        )

        entry_picks = {
            (entry_id, gw): source.entry_event(entry_id, gw)
            for entry_id in names for gw in weeks
        }

        summary, weekly_points = weekly_tables(
            picks_by_entry_gameweek=entry_picks, live_by_gameweek=live,
            players=players, draft_picks=picks, standings=standings,
            entry_names=names, league_code=league.code,
        )

        transfers = finalise_transfers(
            transfers_table(source.transactions(league.league_code), players, standings,
                            league_code=league.code),
            weekly_points,
        )
        trades = finalise_trades(
            trades_table(source.trades(league.league_code), standings,
                         league_code=league.code),
            weekly_points, players,
        )

        summaries.append(summary)
        points_frames.append(weekly_points)
        picks_frames.append(attach_pick_totals(picks, weekly_points))
        standings_frames.append(standings)
        transfers_frames.append(transfers)
        trades_frames.append(trades)

    weekly_summary = pd.concat(summaries, ignore_index=True)
    weekly_points = pd.concat(points_frames, ignore_index=True)
    draft_picks = pd.concat(picks_frames, ignore_index=True)
    standings = pd.concat(standings_frames, ignore_index=True)
    transfers = pd.concat(transfers_frames, ignore_index=True)
    trades = pd.concat(trades_frames, ignore_index=True)

    weekly_summary = attach_fixtures(weekly_summary, fixtures_by_team)
    weekly_points = attach_fixtures(weekly_points, fixtures_by_team)

    table, by_week = live_league_table(weekly_summary, standings, current_week)
    table = table.merge(form_table(weekly_summary, current_week),
                        on=["league_code", "short_name"], how="left")

    # Pre-computed per-view tables, so the client never aggregates a 6,840-row
    # table to draw a chart.
    views = {
        "season_summary": season_summary(weekly_summary, weekly_points),
        "season_summary_by_gameweek": season_summary_by_gameweek(weekly_summary, weekly_points),
        "formations": formations(weekly_summary),
        "draft_performance": draft_pick_performance(weekly_summary, weekly_points, current_week),
        "player_usage": player_usage(weekly_summary),
        "lorenz": lorenz_curve(weekly_summary),
        "draft_share": draft_share(weekly_summary),
        "draft_share_by_gameweek": draft_share_by_gameweek(weekly_summary),
        "distribution_position": points_distribution(weekly_summary, "position"),
        "distribution_team": points_distribution(weekly_summary, "team_name"),
        "available_players": available_form_players(weekly_points, current_week),
    }

    # Story beats for the season review. Takes the full weekly_points, not the
    # reduced table written to JSON — a failed waiver on an undrafted player needs
    # that player's rows to be scored.
    review_facts = season_review_facts(
        season=season, current_week=current_week,
        league_table=table, league_table_by_week=by_week,
        weekly_summary=weekly_summary, weekly_points=weekly_points,
        draft_picks=draft_picks, draft_performance=views["draft_performance"],
        transfers=transfers, trades=trades,
    )

    if isinstance(source, object) and hasattr(source, "stats"):
        say(f"  fetches={source.stats['fetched']} cache_hits={source.stats['cached']}")

    return {
        "season": season,
        "current_week": current_week,
        "hosts_agree": hosts_agree,
        "teams": teams,
        "players": players,
        "draft_picks": draft_picks,
        "weekly_summary": weekly_summary,
        "weekly_points": weekly_points,
        "transfers": transfers,
        "trades": trades,
        "standings": standings,
        "league_table": table,
        "league_table_by_week": by_week,
        "fixtures_by_team": fixtures_by_team,
        "views": views,
        "review_facts": review_facts,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.build")
    parser.add_argument("--season", required=True)
    parser.add_argument("--source", choices=["live", "snapshot"], default=None)
    parser.add_argument("--full", action="store_true", help="ignore cache, refetch everything")
    parser.add_argument("--gameweeks", type=int, default=None, help="cap gameweeks (debug)")
    parser.add_argument("--out", default=None, help="output dir (default data/<season>)")
    args = parser.parse_args(argv)

    try:
        tables = build_tables(args.season, source_kind=args.source, force=args.full,
                              gameweeks=args.gameweeks)
    except RateLimited as error:
        # Not a failure: FPL asked us to slow down. Leave the existing data in
        # place, say so, and let the next scheduled run pick it up. Exiting 0
        # keeps this from raising a red build for a self-correcting condition.
        print(f"::notice title=Rate limited::{error}")
        print("no data written; the next scheduled run will retry")
        return 0

    from .outputs import write_season  # local import keeps transforms import-light
    out = write_season(tables, out_dir=args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
