"""Orchestrator: decide what to fetch -> fetch -> transform -> write JSON.

    python -m pipeline.build --season 2526 --source snapshot
    python -m pipeline.build --season 2627                 # incremental live build
    python -m pipeline.build --season 2627 --full          # ignore cache
    python -m pipeline.build --season 2627 --site dunelmliga

All season-variable values come from pipeline/config. All transformation logic
lives in pipeline/transforms and is pure; this module does the I/O. `--site`
selects which published site's seasons and output folder to use; it changes no
logic, only which leagues are read and where the JSON lands.
"""

import argparse
import json
import sys

import pandas as pd

from . import paths
from .adapters import backfill_difficulty, backfill_players
from .config import DEFAULT_SITE, get_site, is_configured
from .fetchers import build_source
from .fetchers.http import Maintenance, RateLimited
from .transforms import (
    attach_fixtures,
    attach_pick_totals,
    attach_prior_season,
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
    if week:
        return int(week)
    # No current gameweek. Before GW1 opens that means zero weeks have happened —
    # the honest answer, and it keeps us from fetching 38 empty live payloads and
    # 404ing every entry/gameweek pair. `next_event` is what separates "not started
    # yet" from a payload that simply omits the field (the archives).
    if game.get("next_event"):
        return 0
    return season.total_gameweeks


def _prior_players(season, site, say) -> "pd.DataFrame | None":
    """
    Last season's player table, read back from its own generated archive.

    The archives are frozen and restored into `data/<site>/<season>/` before the
    current season builds, so by the time we get here the file is on disk. It is
    optional on purpose: the oldest season has nothing behind it, and a missing
    archive should cost the draft view one column rather than fail the run.

    A site in its first season has no archive of its own, so it may borrow one —
    see Site.player_history_site. This table is a list of footballers, not of
    drafters, so borrowing it says nothing about the other site's league.
    """
    prior = getattr(season, "previous_season", None) or _previous_season(season.season)
    if not prior:
        return None
    candidates = [site.slug]
    if site.player_history_site:
        candidates.append(site.player_history_site)
    for slug in candidates:
        path = paths.season_data_dir(prior, slug) / "players.json"
        try:
            return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            last = error
    say(f"  no {prior} players.json ({last}) — draft view loses last season's clubs")
    return None


def _draft_choices(source, league, say) -> dict:
    """
    Draft night for one league, falling back to a committed copy.

    `draft/<league>/choices` serves the league's current or *next* draft, not a
    history. A league that schedules a second draft therefore loses the first one
    from the API the moment it does — which is exactly Dunelmliga's position: it
    re-drafts at GW21, so its completed GW1 draft now returns an empty list. Left
    alone, every player in that league reads "Not Originally Drafted" and the
    draft-night view has nothing to show.

    Only ever a fallback. A league whose draft the API still serves reads it from
    the API, so this can't mask a live payload going stale.
    """
    choices = source.draft_choices(league.league_code) or {}
    if choices.get("choices") or not league.draft_choices_fallback:
        return choices

    path = paths.repo_root() / league.draft_choices_fallback
    try:
        restored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        say(f"  ! {league.code}: API served no draft choices and {path.name} "
            f"is unreadable ({error}) — draft night will be empty")
        return choices

    say(f"  {league.code}: API served no draft choices; restored "
        f"{len(restored.get('choices') or [])} from {path.name}")
    return restored


def _previous_season(season_id: str) -> str | None:
    """'2627' -> '2526'. None if the id isn't the two-year form."""
    text = str(season_id or "")
    if not (len(text) == 4 and text.isdigit()):
        return None
    start = int(text[:2])
    if start <= 0:
        return None
    return f"{start - 1:02d}{start:02d}"


def _preseason_tables(season, site, source, teams, players, say) -> dict:
    """
    A season that exists but has not kicked off.

    Between the leagues being created and GW1 opening there are no gameweeks, so
    the weekly tables, per-view aggregates and review facts have nothing to compute
    from. Emit only what really exists — the leagues, their drafters, and the picks
    once draft night has happened — so the site can list the season and show draft
    night as soon as it lands, instead of hiding the season for the whole build-up.
    """
    standings_frames, picks_frames = [], []
    for league in season.leagues:
        details = source.league_details(league.league_code)
        standings = league_table(details, league_code=league.code,
                                 exclude_entries=league.exclude_entries)
        picks = draft_picks_table(
            _draft_choices(source, league, say), players, standings,
            league_code=league.code, drafters=league.size,
        )
        say(f"  {league.code} ({league.league_code}): {len(standings)} drafters, "
            f"{len(picks)} picks")
        standings_frames.append(standings)
        picks_frames.append(picks)

    draft_picks = pd.concat(picks_frames, ignore_index=True)
    standings = pd.concat(standings_frames, ignore_index=True)
    if len(draft_picks):
        draft_picks = attach_prior_season(draft_picks, players,
                                          _prior_players(season, site, say))
    # 'drafted' unlocks the draft-night view; 'pre_draft' has names and nothing else.
    stage = "drafted" if len(draft_picks) else "pre_draft"
    say(f"  no gameweeks yet — stage={stage}")
    return {
        "season": season,
        "current_week": 0,
        "stage": stage,
        "teams": teams,
        "players": players,
        "standings": standings,
        "draft_picks": draft_picks,
    }


def build_tables(season_id: str, *, site: str | None = None,
                 source_kind: str | None = None, force: bool = False,
                 gameweeks: int | None = None, verbose: bool = True) -> dict:
    """Run the whole pipeline for one season of one site and return canonical tables."""
    site = get_site(site)
    season = site.season(season_id)
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

    if current_week == 0:
        return _preseason_tables(season, site, source, teams, players, say)

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
            _draft_choices(source, league, say), players, standings,
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

    # Last season's record for each drafted footballer. `bootstrap_is_prior_season`
    # is False here and True in the pre-season path, because that one flag decides
    # whether the bootstrap's totals mean last season or this one — get it wrong
    # and the draft view files this week's points as last year's.
    if len(draft_picks):
        draft_picks = attach_prior_season(
            draft_picks, players, _prior_players(season, site, say),
            bootstrap_is_prior_season=False,
        )

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
        "stage": "live",
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
    parser.add_argument("--site", default=DEFAULT_SITE,
                        help=f"site to build (default {DEFAULT_SITE}); see pipeline/config/sites.py")
    parser.add_argument("--source", choices=["live", "snapshot"], default=None)
    parser.add_argument("--full", action="store_true", help="ignore cache, refetch everything")
    parser.add_argument("--gameweeks", type=int, default=None, help="cap gameweeks (debug)")
    parser.add_argument("--out", default=None, help="output dir (default data/<site>/<season>)")
    args = parser.parse_args(argv)

    try:
        tables = build_tables(args.season, site=args.site, source_kind=args.source,
                              force=args.full, gameweeks=args.gameweeks)
    except (RateLimited, Maintenance) as error:
        # Not a failure: FPL either asked us to slow down or is serving a holding
        # page mid-run. Leave the existing data in place, say so, and let the next
        # scheduled run pick it up. Exiting 0 keeps this from raising a red build
        # for a self-correcting condition — and because no data was written, the
        # workflow declines to deploy rather than publishing a site that is
        # missing this season (see the digest step in update.yml).
        print(f"::notice title=Nothing fetched::{error}")
        print("no data written; the next scheduled run will retry")
        return 0

    from .outputs import write_season  # local import keeps transforms import-light
    out = write_season(tables, site=args.site, out_dir=args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
