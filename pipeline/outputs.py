"""Write canonical JSON. The shape is documented in docs/data-contract.md.

Emits raw tables for the explorer plus pre-computed per-view arrays, so the mobile
client never aggregates a large table to draw a chart.
"""

import json
import math
from pathlib import Path

import pandas as pd

from . import paths
from .config import DEFAULT_SITE, get_site

# weekly_points is one row per element per gameweek per league — ~59k rows for a
# full season, 88% of it undrafted players. Views need owned rows plus the best
# undrafted names, so unowned rows are kept only when they ranked this well.
UNDRAFTED_RANK_CUTOFF = 20

NOT_DRAFTED_PREFIX = "Not Drafted"


def _clean(value):
    """JSON-safe scalar: NaN/inf/NaT -> None, numpy -> python, timestamps -> ISO."""
    if value is None:
        return None
    if isinstance(value, float):
        # isfinite, not isnan: an inf reaches the file as the bare token
        # `Infinity`, which Python emits happily and JSON.parse rejects — one
        # such value makes the whole table unreadable to the browser.
        return None if not math.isfinite(value) else value
    if isinstance(value, (pd.Timestamp,)):
        return None if pd.isna(value) else value.isoformat()
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _dump(payload, **kwargs) -> str:
    """Serialise strictly.

    `allow_nan=False` turns a stray non-finite float into a failed build rather
    than a file no browser can read. The deploy is gated on this step, so raising
    here leaves the last good site live instead of publishing a broken one. Only
    payloads built by hand (meta, review facts) can reach it; everything routed
    through `_records` is already cleaned.
    """
    return json.dumps(payload, allow_nan=False, **kwargs)


def _records(frame: pd.DataFrame, columns: dict[str, str]) -> list[dict]:
    """Project and rename to canonical names, keeping missing columns as None."""
    out = []
    available = {new: old for new, old in columns.items() if old in frame.columns}
    for row in frame.to_dict("records"):
        record = {new: _clean(row.get(old)) for new, old in available.items()}
        for new in columns:
            record.setdefault(new, None)
        out.append({key: record[key] for key in columns})
    return out


WEEKLY_SUMMARY = {
    "gameweek": "gameweek", "league": "league_code", "short_name": "short_name",
    "element": "element", "place": "place", "web_name": "web_name", "position": "position",
    "team_id": "team_id", "team_name": "team_name",
    "total_points": "total_points", "points_scored": "points_scored",
    "points_before_auto_subs": "points_before_auto_subs",
    "originally_starting": "originally_starting",
    "optimal_points": "optimal_points", "optimal_weight": "optimal_weight",
    "player_total_points": "player_total_points",
    "points_scored_cumulative": "points_scored_cumulative",
    "points_scored_pct": "points_scored_pct",
    "drafter_name": "drafter_name", "draft_index": "draft_index", "round": "round",
    "in_original_draft": "in_original_draft",
    "gameweek_matches": "gameweek_matches", "opposition": "opposition",
    "home_away": "home_away", "team_score": "team_score",
    "opposition_score": "opposition_score",
    "team_difficulty": "team_difficulty", "opposition_difficulty": "opposition_difficulty",
    "kickoff_time_first": "kickoff_time_first",
}

WEEKLY_POINTS = {
    "gameweek": "gameweek", "league": "league_code", "element": "id",
    "web_name": "web_name", "position": "position", "team_name": "team_name",
    "total_points": "total_points", "rank_in_week": "rank_in_week",
    "owner": "short_name", "place": "place", "is_benched": "isBenched",
    "drafter_name": "drafter_name", "draft_index": "draft_index",
    "opposition": "opposition", "home_away": "home_away",
    "team_difficulty": "team_difficulty",
}

DRAFT_PICKS = {
    "league": "league_code", "short_name": "short_name", "index": "index", "pick": "pick",
    "round": "round", "element": "element", "web_name": "web_name", "position": "position",
    "team_name": "team_name", "draft_rank": "draft_rank", "now_cost": "now_cost",
    "selected_by_percent": "selected_by_percent",
    # Two different quantities, named honestly. `total_points` is the player's
    # full season total in every season; `points_realised_by_drafter` is the part
    # the person who picked him actually banked. See attach_pick_totals().
    "total_points": "total_points",
    "points_realised_by_drafter": "points_realised_by_drafter",
    # Last season's record for the footballer, for the draft-night view. Null on
    # the oldest archived season, which has nothing behind it. See
    # transforms.draft_picks.attach_prior_season.
    "prior_points": "prior_points",
    "prior_team_name": "prior_team_name",
    "new_to_pl": "new_to_pl",
    "moved_club": "moved_club",
}

TRANSFERS = {
    "league": "league_code", "gameweek": "gameweek", "short_name": "short_name",
    "kind": "kind", "result": "result", "priority": "priority", "index": "index",
    "element_in": "element_in", "element_out": "element_out",
    "player_in": "player_in", "player_out": "player_out",
    "player_in_points": "player_in_points_scored_in_week",
    "player_out_points": "player_out_points_scored_in_week",
    "net_points": "net_points_of_transfer_in_week",
}

TRADES = {
    "league": "league_code", "gameweek": "gameweek", "state": "state",
    "offer_time": "offer_time", "response_time": "response_time",
    "offered_by": "offered_by", "received_by": "received_by",
    "element_in": "element_in", "element_out": "element_out",
    "player_in": "player_in", "player_out": "player_out",
    "player_in_points": "player_in_total_points",
    "player_out_points": "player_out_total_points",
    "net_points": "net_points_from_trade",
}

PLAYERS = {
    # `element` is this season's id and is reassigned each year; `code` is the
    # footballer's permanent one, and is what lets next season recognise him here.
    # Null on the CSV-derived 2425 archive, which never had it.
    "element": "id", "code": "code", "web_name": "web_name", "position": "position",
    "team_id": "team", "team_name": "team_name", "total_points": "total_points",
    "goals_scored": "goals_scored", "assists": "assists", "bonus": "bonus",
    "clean_sheets": "clean_sheets", "minutes": "minutes", "draft_rank": "draft_rank",
    "now_cost": "now_cost", "selected_by_percent": "selected_by_percent",
}

TEAMS = {"team_id": "team", "team_name": "team_name"}

# A head-to-head league's own table, and the fixtures behind it. Empty for a
# classic league, which is every WOD league — the views key off meta.leagues[].scoring
# rather than off these being non-empty, so an empty file is never ambiguous.
H2H_TABLE = {
    "league": "league_code", "short_name": "short_name",
    "played": "played", "won": "won", "drawn": "drawn", "lost": "lost",
    "points_for": "points_for", "points_against": "points_against",
    "h2h_points": "h2h_points", "rank": "rank", "last_rank": "last_rank",
    # True while a counted gameweek is still being played, so the view can say
    # the table is ahead of the official one rather than silently contradicting it.
    "provisional": "provisional",
}

H2H_MATCHES = {
    "gameweek": "gameweek", "league": "league_code",
    "home": "home", "away": "away",
    "home_points": "home_points", "away_points": "away_points",
    "started": "started", "finished": "finished",
    "result": "result", "winner": "winner",
}

# One row per team per gameweek for the WHOLE season, past and future. Separate
# from the fixture columns embedded in weekly_summary, which only cover gameweeks
# that have been played — the next-6 look-ahead needs fixtures that haven't.
FIXTURES = {
    "gameweek": "gameweek", "team_name": "team", "gameweek_matches": "gameweek_matches",
    "opposition": "opposition", "home_away": "home_away",
    "team_score": "team_score", "opposition_score": "opposition_score",
    "team_difficulty": "team_difficulty", "opposition_difficulty": "opposition_difficulty",
    "kickoff_time": "kickoff_time_first",
}

# Pre-computed per-view tables. Keys are file stems under the season directory.
VIEW_COLUMNS = {
    "season_summary": {
        "league": "league_code", "short_name": "short_name", "is_average": "is_average",
        "draft_points": "draft_points",
        "points_gained_through_waivers": "points_gained_through_waivers",
        "squad_points": "squad_points", "bench_strength": "bench_strength",
        "optimal_points": "optimal_points",
        "points_lost_choosing_starting_XI": "points_lost_choosing_starting_XI",
        "points_before_auto_subs": "points_before_auto_subs",
        "points_gained_with_auto_subs": "points_gained_with_auto_subs",
        "net_points_lost_through_subs": "net_points_lost_through_subs",
        "points_scored": "points_scored",
    },
    "season_summary_by_gameweek": {
        "league": "league_code", "short_name": "short_name", "gameweek": "gameweek",
        "draft_points": "draft_points",
        "points_gained_through_waivers": "points_gained_through_waivers",
        "squad_points": "squad_points", "bench_strength": "bench_strength",
        "optimal_points": "optimal_points",
        "points_lost_choosing_starting_XI": "points_lost_choosing_starting_XI",
        "points_before_auto_subs": "points_before_auto_subs",
        "points_gained_with_auto_subs": "points_gained_with_auto_subs",
        "net_points_lost_through_subs": "net_points_lost_through_subs",
        "points_scored": "points_scored",
    },
    "formations": {
        "league": "league_code", "short_name": "short_name",
        "formation": "formation", "count": "count", "optimal_formation": "optimal_formation",
    },
    "draft_performance": {
        "league": "league_code", "short_name": "drafter_name", "draft_index": "draft_index",
        "element": "id", "web_name": "web_name", "position": "position",
        "total_points": "total_points",
        "points_realised_by_drafter": "points_realised_by_drafter",
        "points_realised_by_other": "points_realised_by_other",
        "points_unrealised": "points_unrealised",
        "still_owned": "still_owned", "current_owner": "current_owner",
    },
    "player_usage": {
        "league": "league_code", "short_name": "short_name",
        "unique_players_used": "unique_players_used",
        "unique_players_started": "unique_players_started",
        "scoring_players": "scoring_players", "gini": "gini",
        "top_player": "top_player", "top_player_points": "top_player_points",
        "top_player_pct": "top_player_pct",
    },
    "lorenz": {
        "league": "league_code", "short_name": "short_name",
        "player_index": "player_index", "players_pct": "players_pct",
        "points_pct": "points_pct", "points_cumulative": "points_cumulative",
        "players_total": "players_total", "web_name": "web_name",
    },
    "draft_share": {
        "league": "league_code", "short_name": "short_name",
        "points_scored": "points_scored", "draft_points": "draft_points",
        "pct_from_draft": "pct_from_draft",
    },
    "draft_share_by_gameweek": {
        "league": "league_code", "short_name": "short_name", "gameweek": "gameweek",
        "points_scored": "points_scored", "draft_points": "draft_points",
        "pct_from_draft": "pct_from_draft",
    },
    "distribution_position": {
        "league": "league_code", "short_name": "short_name", "cut": "cut",
        "bucket": "bucket", "points_scored": "points_scored",
        "pct_points": "pct_points", "avg_points": "avg_points",
    },
    "available_players": {
        "league": "league_code", "gameweek": "gameweek", "element": "id",
        "web_name": "web_name", "position": "position", "team_name": "team_name",
        "form_points": "form_points", "rank": "rank",
    },
}
VIEW_COLUMNS["distribution_team"] = VIEW_COLUMNS["distribution_position"]


def _capabilities(tables: dict) -> dict:
    summary = tables["weekly_summary"]
    points = tables["weekly_points"]

    def filled(frame, column):
        # bool() matters: numpy.bool_ is not JSON serializable
        return bool(column in frame.columns and frame[column].notna().any())

    return {
        "fixtures": filled(summary, "opposition"),
        "difficulty": filled(summary, "team_difficulty"),
        "cost": filled(tables["players"], "now_cost"),
        "ownership_by_league": filled(points, "drafter_name"),
        "draft_round": filled(summary, "round"),
        "cumulative": filled(summary, "points_scored_cumulative"),
        "team_names": filled(summary, "team_name"),
        "trades": len(tables["trades"]) > 0,
        "optimal_points": filled(summary, "optimal_points"),
        # a full-season fixture table, needed for the next-6 look-ahead
        "fixture_lookahead": filled(tables.get("fixtures_by_team", pd.DataFrame()), "opposition"),
    }


def _league_table_view(tables: dict) -> list[dict]:
    """Per-drafter table with per-gameweek arrays precomputed for the trends chart."""
    table = tables["league_table"]
    by_week = tables["league_table_by_week"]
    gameweeks = sorted(by_week["gameweek"].unique())

    rows = []
    for record in table.to_dict("records"):
        league, short = record["league_code"], record["short_name"]
        mine = by_week[(by_week["league_code"] == league) & (by_week["short_name"] == short)]
        series = mine.set_index("gameweek")["points_scored"].to_dict()
        weekly = [int(series.get(gw, 0)) for gw in gameweeks]
        running, cumulative = 0, []
        for value in weekly:
            running += value
            cumulative.append(running)
        rows.append({
            "league": league,
            "short_name": short,
            "name": _clean(record.get("name")),
            "entry_name": _clean(record.get("entry_name")),
            "rank": _clean(record.get("rank")),
            "last_rank": _clean(record.get("last_rank")),
            "total": _clean(record.get("total")),
            "gameweek_points": _clean(record.get("gameweek_points")),
            "form_points": _clean(record.get("form_points")),
            "form_rank": _clean(record.get("form_rank")),
            "points_by_gameweek": weekly,
            "cumulative_by_gameweek": cumulative,
        })
    rows.sort(key=lambda r: (r["league"], r["rank"] if r["rank"] is not None else 99))
    return rows


def _reduce_weekly_points(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep owned rows plus undrafted players who ranked in the top N that gameweek."""
    if "short_name" not in frame.columns:
        return frame
    undrafted = frame["short_name"].astype(str).str.startswith(NOT_DRAFTED_PREFIX)
    keep_undrafted = undrafted & (pd.to_numeric(frame["rank_in_week"], errors="coerce")
                                 <= UNDRAFTED_RANK_CUTOFF)
    return frame[~undrafted | keep_undrafted]


def _write_preseason(tables: dict, *, site: str | None = None,
                     out_dir: str | None = None) -> Path:
    """
    Write the little that exists for a season that has not kicked off.

    Enough for the site to list the season, name its leagues and drafters, and —
    once draft night has happened — show the picks. Everything derived from
    gameweeks is written empty rather than omitted, so a view that loads a table
    renders nothing instead of failing on a 404.
    """
    season = tables["season"]
    root = Path(out_dir) if out_dir else paths.season_data_dir(season.season, site)
    root.mkdir(parents=True, exist_ok=True)
    standings = tables["standings"]

    def full_name(row):
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        return _clean(name) or None

    # Reuse the real capability probe against empty frames rather than hardcoding a
    # list of falses, so this cannot drift as capabilities are added. `cost` comes
    # out true on its own merit: the bootstrap carries prices before GW1.
    empty = pd.DataFrame()
    capabilities = _capabilities({
        "weekly_summary": empty, "weekly_points": empty, "trades": empty,
        "players": tables["players"], "fixtures_by_team": empty,
    })

    meta = {
        "season": season.season,
        "label": season.label,
        "source": season.default_source,
        "stage": tables["stage"],
        "current_gameweek": 0,
        "total_gameweeks": 0,
        "complete": False,
        "gameweeks": [],
        "leagues": [
            {"code": lg.code, "name": lg.name, "size": lg.size,
             "promoted": lg.promoted, "relegated": lg.relegated,
             "scoring": (tables.get("scoring") or {}).get(lg.code, "classic")}
            for lg in season.leagues
        ],
        "drafters": [
            {"short_name": r["short_name"], "name": full_name(r), "league": r["league_code"]}
            for r in standings.to_dict("records")
        ],
        "capabilities": capabilities,
        "notes": season.notes,
    }

    files = {
        "meta.json": meta,
        "draft_picks.json": _records(tables["draft_picks"], DRAFT_PICKS),
        "players.json": _records(tables["players"], PLAYERS),
        "teams.json": _records(tables["teams"], TEAMS),
    }
    for name in ("league_table", "weekly_summary", "weekly_points",
                 "transfers", "trades", "fixtures", "h2h_table", "h2h_matches"):
        files[f"{name}.json"] = []

    for name, payload in files.items():
        (root / name).write_text(_dump(payload, separators=(",", ":")), encoding="utf-8")

    write_seasons_index(root.parent, site=site)
    return root


def write_season(tables: dict, *, site: str | None = None, out_dir: str | None = None,
                 reduce_points: bool = True) -> Path:
    if tables.get("stage", "live") != "live":
        return _write_preseason(tables, site=site, out_dir=out_dir)

    season = tables["season"]
    root = Path(out_dir) if out_dir else paths.season_data_dir(season.season, site)
    root.mkdir(parents=True, exist_ok=True)

    summary = tables["weekly_summary"]
    points = tables["weekly_points"]
    if reduce_points:
        points = _reduce_weekly_points(points)

    gameweeks = sorted(int(g) for g in summary["gameweek"].unique())
    meta = {
        "season": season.season,
        "label": season.label,
        "source": season.default_source,
        "stage": tables.get("stage", "live"),
        "current_gameweek": int(tables["current_week"]),
        "total_gameweeks": len(gameweeks),
        "complete": len(gameweeks) >= season.total_gameweeks,
        "gameweeks": gameweeks,
        "leagues": [
            {"code": lg.code, "name": lg.name, "size": lg.size,
             "promoted": lg.promoted, "relegated": lg.relegated,
             "scoring": (tables.get("scoring") or {}).get(lg.code, "classic")}
            for lg in season.leagues
        ],
        "drafters": [
            {"short_name": r["short_name"], "name": _clean(r.get("name")), "league": r["league_code"]}
            for r in tables["league_table"].to_dict("records")
        ],
        "capabilities": _capabilities(tables),
        "notes": season.notes,
    }

    files = {
        "meta.json": meta,
        "league_table.json": _league_table_view(tables),
        "weekly_summary.json": _records(summary, WEEKLY_SUMMARY),
        "weekly_points.json": _records(points, WEEKLY_POINTS),
        "draft_picks.json": _records(tables["draft_picks"], DRAFT_PICKS),
        "transfers.json": _records(tables["transfers"], TRANSFERS),
        "trades.json": _records(tables["trades"], TRADES),
        "players.json": _records(tables["players"], PLAYERS),
        "teams.json": _records(tables["teams"], TEAMS),
        "fixtures.json": _records(tables.get("fixtures_by_team", pd.DataFrame()), FIXTURES),
        "h2h_table.json": _records(tables.get("h2h_table", pd.DataFrame()), H2H_TABLE),
        "h2h_matches.json": _records(tables.get("h2h_matches", pd.DataFrame()), H2H_MATCHES),
    }
    # Not a table: a nested dict of story beats the season review is written from.
    if tables.get("review_facts"):
        files["season_review_facts.json"] = tables["review_facts"]
    for name, view in (tables.get("views") or {}).items():
        columns = VIEW_COLUMNS.get(name)
        if columns is None:
            continue
        files[f"{name}.json"] = _records(view, columns)

    for name, payload in files.items():
        (root / name).write_text(_dump(payload, separators=(",", ":")), encoding="utf-8")

    write_seasons_index(root.parent, site=site)
    return root


def write_seasons_index(data_root: Path | None = None, *, site: str | None = None) -> Path:
    """
    Rebuild seasons.json from whatever season directories exist on disk.

    Safe to call standalone (`python -m pipeline.outputs --index`), which the
    workflow does on every run. Season directories can be restored from the Actions
    cache without any build running, and the cache holds the season folders only —
    so without an unconditional rebuild the index goes missing and the whole site
    fails to load.

    Only the seasons the site publishes are listed, so one site can never index
    another's folders even though they sit under the same `data/`.
    """
    if data_root is None:
        data_root = paths.data_dir(site)
    entries = []
    for season_id in sorted(get_site(site).season_ids, reverse=True):
        meta_path = data_root / season_id / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        entries.append({
            "season": meta["season"], "label": meta["label"],
            "current_gameweek": meta["current_gameweek"], "complete": meta["complete"],
            "stage": meta.get("stage", "live"),
        })
    # Land on the newest season that has something to show. The new season appears
    # in the selector as soon as its leagues exist, but opening the site on its
    # holding screen would bury last season's completed data for weeks.
    playable = [e for e in entries if e["stage"] == "live"]
    default = (playable or entries or [{"season": None}])[0]["season"]
    payload = {"seasons": entries, "default": default}
    path = data_root / "seasons.json"
    data_root.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(payload, indent=2), encoding="utf-8")
    return path


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.outputs")
    parser.add_argument("--index", action="store_true",
                        help="rebuild data/<site>/seasons.json from the season "
                             "directories on disk")
    parser.add_argument("--site", default=DEFAULT_SITE,
                        help=f"site to index (default {DEFAULT_SITE})")
    args = parser.parse_args(argv)

    if not args.index:
        parser.error("nothing to do; pass --index")

    path = write_seasons_index(site=args.site)
    payload = json.loads(path.read_text(encoding="utf-8"))
    seasons = ", ".join(s["season"] for s in payload["seasons"]) or "none"
    print(f"wrote {path} ({seasons})")
    if not payload["seasons"]:
        # An empty index means the site will load nothing — fail loudly rather
        # than deploying a blank app.
        print(f"::error title=No seasons::{path.parent} contains no season directories")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
