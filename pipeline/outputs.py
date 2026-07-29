"""Write canonical JSON. The shape is documented in docs/data-contract.md.

Emits raw tables for the explorer plus pre-computed per-view arrays, so the mobile
client never aggregates a large table to draw a chart.
"""

import json
import math
from pathlib import Path

import pandas as pd

from . import paths
from .config import SEASONS

# weekly_points is one row per element per gameweek per league — ~59k rows for a
# full season, 88% of it undrafted players. Views need owned rows plus the best
# undrafted names, so unowned rows are kept only when they ranked this well.
UNDRAFTED_RANK_CUTOFF = 20

NOT_DRAFTED_PREFIX = "Not Drafted"


def _clean(value):
    """JSON-safe scalar: NaN/NaT -> None, numpy -> python, timestamps -> ISO."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else value
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
    "selected_by_percent": "selected_by_percent", "total_points": "total_points",
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
    "element": "id", "web_name": "web_name", "position": "position",
    "team_id": "team", "team_name": "team_name", "total_points": "total_points",
    "goals_scored": "goals_scored", "assists": "assists", "bonus": "bonus",
    "clean_sheets": "clean_sheets", "minutes": "minutes", "draft_rank": "draft_rank",
    "now_cost": "now_cost", "selected_by_percent": "selected_by_percent",
}

TEAMS = {"team_id": "team", "team_name": "team_name"}

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


def write_season(tables: dict, *, out_dir: str | None = None, reduce_points: bool = True) -> Path:
    season = tables["season"]
    root = Path(out_dir) if out_dir else paths.season_data_dir(season.season)
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
        "current_gameweek": int(tables["current_week"]),
        "total_gameweeks": len(gameweeks),
        "complete": len(gameweeks) >= season.total_gameweeks,
        "gameweeks": gameweeks,
        "leagues": [
            {"code": lg.code, "name": lg.name, "size": lg.size,
             "promoted": lg.promoted, "relegated": lg.relegated}
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
    }
    for name, view in (tables.get("views") or {}).items():
        columns = VIEW_COLUMNS.get(name)
        if columns is None:
            continue
        files[f"{name}.json"] = _records(view, columns)

    for name, payload in files.items():
        (root / name).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    write_seasons_index(root.parent)
    return root


def write_seasons_index(data_root: Path | None = None) -> Path:
    """
    Rebuild seasons.json from whatever season directories exist on disk.

    Safe to call standalone (`python -m pipeline.outputs --index`), which the
    workflow does on every run. Season directories can be restored from the Actions
    cache without any build running, and the cache holds the season folders only —
    so without an unconditional rebuild the index goes missing and the whole site
    fails to load.
    """
    if data_root is None:
        data_root = paths.data_dir()
    entries = []
    for season_id in sorted(SEASONS, reverse=True):
        meta_path = data_root / season_id / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        entries.append({
            "season": meta["season"], "label": meta["label"],
            "current_gameweek": meta["current_gameweek"], "complete": meta["complete"],
        })
    payload = {"seasons": entries, "default": entries[0]["season"] if entries else None}
    path = data_root / "seasons.json"
    data_root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.outputs")
    parser.add_argument("--index", action="store_true",
                        help="rebuild data/seasons.json from the season directories on disk")
    args = parser.parse_args(argv)

    if not args.index:
        parser.error("nothing to do; pass --index")

    path = write_seasons_index()
    payload = json.loads(path.read_text(encoding="utf-8"))
    seasons = ", ".join(s["season"] for s in payload["seasons"]) or "none"
    print(f"wrote {path} ({seasons})")
    if not payload["seasons"]:
        # An empty index means the site will load nothing — fail loudly rather
        # than deploying a blank app.
        print("::error title=No seasons::data/ contains no season directories")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
