"""Phase 2 regression report: does the refactor reproduce the notebook's numbers?

Runs the pipeline on reference/raw_2526 and compares every shared column against
reference/historical/*_2526.csv, row-aligned on natural keys.

    python -m pipeline.validate --season 2526

A column is reported as one of:
  MATCH     identical for every aligned row
  DIFF      values disagree (count + examples)
  BACKFILL  expected: the API can no longer supply it, sourced from CSV instead
  MISSING   present in the CSV, absent from the pipeline output
"""

import argparse

import numpy as np
import pandas as pd

from . import paths
from .build import build_tables
from .config import get_season

# Columns the FPL API can no longer supply for 2526 (see docs/notebook-recon.md
# 6.1 and 6.1b): fantasy.premierleague.com rolled to 2627, and the draft
# bootstrap carries 2627 element->team ids.
EXPECTED_BACKFILL = {
    "team", "team_name", "team_id", "now_cost", "selected_by_percent",
    "team_difficulty", "opposition_difficulty", "web_name",
}

# Columns dropped on purpose: pandas merge artifacts, always identical to `element`.
DROPPED = {"element_x", "element_y"}

# Deliberate cleanups that change a value. Listed explicitly, as CLAUDE.md requires.
INTENTIONAL = {
    "player_in": "display string removed — CSV bakes in '(points)', data keeps the bare name",
    "player_out": "display string removed — CSV bakes in '(points)', data keeps the bare name",
    "optimal_weight": (
        "true selection weight from calc_optimal_points; the CSV recomputed it as "
        "optimal_points/total_points, which is NaN for the 946 zero-point rows"
    ),
}

TABLES = {
    "weekly_summary": ("Weekly Summary", ["league_code", "short_name", "gameweek", "element"]),
    "weekly_points": ("Player Points Weekly", ["league_code", "gameweek", "id"]),
    "draft_picks": ("Draft Picks", ["league_code", "short_name", "element"]),
    "transfers": ("Transfers", ["league_code", "gameweek", "element_in", "element_out"]),
    "players": ("All Players Summary", ["id"]),
}

TOLERANCE = 1e-6


def load_csv(stem: str, season: str) -> pd.DataFrame | None:
    path = paths.historical_dir() / f"{stem}_{season}.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path, encoding="utf-8")
    # the 2425 CSVs carry a leading unnamed pandas index column
    return frame.loc[:, [c for c in frame.columns if not c.startswith("Unnamed")]]


def _normalise(series: pd.Series) -> pd.Series:
    """Make a column comparable: datetimes to UTC, numerics to float, else trimmed str."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, utc=True, errors="coerce")

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() >= max(1, int(series.notna().sum() * 0.9)):
        return numeric.astype(float)

    text = series.astype(str).str.strip()
    # a string column that is really timestamps (the CSV side of date_added etc.)
    if len(text) and text.str.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:").mean() > 0.9:
        return pd.to_datetime(text, utc=True, errors="coerce")
    return text.str.upper()


def compare_table(name: str, produced: pd.DataFrame, expected: pd.DataFrame,
                  keys: list[str]) -> dict:
    """Align on keys and compare shared columns."""
    result = {"name": name, "rows_produced": len(produced), "rows_expected": len(expected),
              "columns": {}, "key_note": ""}

    usable_keys = [k for k in keys if k in produced.columns and k in expected.columns]
    if not usable_keys:
        result["key_note"] = f"no shared key columns from {keys}"
        return result

    left = produced.copy()
    right = expected.copy()
    for frame in (left, right):
        for key in usable_keys:
            frame[key] = _normalise(frame[key])

    left = left.drop_duplicates(subset=usable_keys)
    right = right.drop_duplicates(subset=usable_keys)
    if len(left) != len(produced) or len(right) != len(expected):
        result["key_note"] = (
            f"keys not unique (produced {len(produced)}->{len(left)}, "
            f"csv {len(expected)}->{len(right)}); compared on deduped rows"
        )

    merged = left.merge(right, on=usable_keys, how="inner", suffixes=("__new", "__old"))
    result["rows_aligned"] = len(merged)
    result["only_in_produced"] = len(left) - len(merged)
    result["only_in_csv"] = len(right) - len(merged)

    shared = sorted((set(produced.columns) & set(expected.columns)) - set(usable_keys))
    for column in shared:
        new = _normalise(merged[f"{column}__new"])
        old = _normalise(merged[f"{column}__old"])
        if new.dtype.kind == "f" and old.dtype.kind == "f":
            equal = np.isclose(new.fillna(-10**9), old.fillna(-10**9), atol=TOLERANCE)
        elif pd.api.types.is_datetime64_any_dtype(new) and pd.api.types.is_datetime64_any_dtype(old):
            equal = (new == old) | (new.isna() & old.isna())
        else:
            equal = new.astype(str).fillna("") == old.astype(str).fillna("")
        bad = int((~equal).sum())
        entry = {"mismatches": bad, "compared": len(merged)}
        if bad:
            sample = merged.loc[~equal, usable_keys + [f"{column}__new", f"{column}__old"]].head(3)
            entry["examples"] = sample.to_dict("records")
        result["columns"][column] = entry

    result["missing"] = sorted(
        set(expected.columns) - set(produced.columns) - set(usable_keys) - DROPPED
    )
    return result


def report(season_id: str = "2526", *, gameweeks: int | None = None) -> list[dict]:
    season = get_season(season_id)
    tables = build_tables(season_id, source_kind="snapshot", gameweeks=gameweeks)

    results = []
    for key, (stem, natural_keys) in TABLES.items():
        expected = load_csv(stem, season.season)
        if expected is None:
            continue
        results.append(compare_table(key, tables[key], expected, natural_keys))
    return results


def print_report(results: list[dict]) -> bool:
    """Print the diff report. Returns True when everything unexplained matches."""
    clean = True
    for table in results:
        print(f"\n=== {table['name']} ===")
        print(f"  rows: pipeline {table['rows_produced']}, csv {table['rows_expected']}, "
              f"aligned {table.get('rows_aligned', 0)}"
              f" (only-pipeline {table.get('only_in_produced', 0)},"
              f" only-csv {table.get('only_in_csv', 0)})")
        if table["key_note"]:
            print(f"  ! {table['key_note']}")

        matched, diffs, backfill, intended = [], [], [], []
        for column, info in sorted(table["columns"].items()):
            if info["mismatches"] == 0:
                matched.append(column)
            elif column in EXPECTED_BACKFILL:
                backfill.append((column, info))
            elif column in INTENTIONAL:
                intended.append((column, info))
            else:
                diffs.append((column, info))

        print(f"  MATCH ({len(matched)}): {', '.join(matched) if matched else '-'}")
        if backfill:
            print(f"  BACKFILL ({len(backfill)}), expected — API can no longer supply:")
            for column, info in backfill:
                print(f"    {column}: {info['mismatches']}/{info['compared']} differ")
        if intended:
            print(f"  INTENTIONAL ({len(intended)}), deliberate cleanups:")
            for column, info in intended:
                print(f"    {column}: {info['mismatches']}/{info['compared']} differ — {INTENTIONAL[column]}")
        if diffs:
            clean = False
            print(f"  DIFF ({len(diffs)}):")
            for column, info in diffs:
                print(f"    {column}: {info['mismatches']}/{info['compared']} differ")
                for example in info.get("examples", []):
                    keys = {k: v for k, v in example.items() if not k.endswith(("__new", "__old"))}
                    new = next(v for k, v in example.items() if k.endswith("__new"))
                    old = next(v for k, v in example.items() if k.endswith("__old"))
                    print(f"      {keys} new={new!r} csv={old!r}")
        if table["missing"]:
            print(f"  MISSING from pipeline: {', '.join(table['missing'])}")
    return clean


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.validate")
    parser.add_argument("--season", default="2526")
    parser.add_argument("--gameweeks", type=int, default=None)
    args = parser.parse_args(argv)

    results = report(args.season, gameweeks=args.gameweeks)
    clean = print_report(results)
    print("\n" + ("ALL COMPARED COLUMNS MATCH (backfill aside)" if clean
                  else "UNEXPLAINED DIFFERENCES PRESENT"))
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
