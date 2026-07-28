"""One-off scraper: save every raw FPL Draft endpoint for a season to disk.

Purpose: the FPL API only ever serves the *current* season. Season 2526 is complete
but still being served (as of 2026-07-28); once 2627 opens it is gone forever. This
captures the full raw payload set so the pipeline has a permanent regression oracle.

Throwaway quality by design (see BUILD_PROMPT Phase 0a) -- completeness > cleanliness.
Safe to re-run: existing files are skipped unless --force.

    python pipeline/snapshot_raw_season.py --out reference/raw_2526
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DRAFT = "https://draft.premierleague.com/api"
FANTASY = "https://fantasy.premierleague.com/api"

# 2526 leagues. Codes are per-season; a new season means new codes.
LEAGUE_CODES = {"premiership": 21123, "conference": 21136}
TOTAL_GAMEWEEKS = 38

THROTTLE_SECONDS = 0.25
MAX_RETRIES = 4


def fetch(url):
    """GET + parse JSON, with backoff. Public endpoints -- no auth, no credentials."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            last_error = error
            # 404 is a real answer for some entry/GW combos -- don't burn retries on it.
            if isinstance(error, urllib.error.HTTPError) and error.code == 404:
                return None
            time.sleep(2 ** attempt)
    print(f"    FAILED {url}: {last_error}", file=sys.stderr)
    return None


def save(payload, path, force=False):
    """Write payload to path. Returns 'skip' | 'saved' | 'empty'."""
    if path.exists() and not force:
        return "skip"
    if payload is None:
        return "empty"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    time.sleep(THROTTLE_SECONDS)
    return "saved"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reference/raw_2526")
    parser.add_argument("--force", action="store_true", help="refetch files already on disk")
    parser.add_argument("--gameweeks", type=int, default=TOTAL_GAMEWEEKS)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    tally = {"saved": 0, "skip": 0, "empty": 0}

    def grab(url, relative_path):
        result = save(fetch(url), out / relative_path, args.force)
        tally[result] += 1
        if result == "empty":
            print(f"    EMPTY {relative_path}")
        return result

    print(f"--> {out}")

    # 1. Game status + both bootstraps + fixtures (season-wide singletons).
    print("game status, bootstraps, fixtures")
    grab(f"{DRAFT}/game", "game.json")
    grab(f"{DRAFT}/bootstrap-static", "bootstrap_static_draft.json")
    grab(f"{FANTASY}/bootstrap-static", "bootstrap_static_fantasy.json")
    grab(f"{FANTASY}/fixtures/", "fixtures.json")

    # 2. Per-league: details, draft choices, transactions (waivers/frees), trades.
    entry_ids = {}
    for name, code in LEAGUE_CODES.items():
        print(f"league {name} ({code})")
        details = fetch(f"{DRAFT}/league/{code}/details")
        tally[save(details, out / f"league/{code}_details.json", args.force)] += 1
        if details:
            for entry in details["league_entries"]:
                # entry_id can be null for a never-activated entry; skip those.
                if entry.get("entry_id"):
                    entry_ids[entry["entry_id"]] = entry["short_name"]
        grab(f"{DRAFT}/draft/{code}/choices", f"league/{code}_choices.json")
        grab(f"{DRAFT}/draft/league/{code}/transactions", f"league/{code}_transactions.json")
        grab(f"{DRAFT}/draft/league/{code}/trades", f"league/{code}_trades.json")

    # 3. Live element points, one file per gameweek. 1-indexed: GW1 == event/1.
    print(f"event live x{args.gameweeks}")
    for gameweek in range(1, args.gameweeks + 1):
        grab(f"{DRAFT}/event/{gameweek}/live", f"event/live_gw{gameweek:02d}.json")

    # 4. Every entry's picks for every gameweek.
    print(f"entry picks: {len(entry_ids)} entries x {args.gameweeks} gameweeks")
    for entry_id, short_name in sorted(entry_ids.items()):
        for gameweek in range(1, args.gameweeks + 1):
            grab(
                f"{DRAFT}/entry/{entry_id}/event/{gameweek}",
                f"entry/{entry_id}/gw{gameweek:02d}.json",
            )
        print(f"    {entry_id} ({short_name}) done")

    manifest = {
        "source": "FPL public API (draft.premierleague.com, fantasy.premierleague.com)",
        "league_codes": LEAGUE_CODES,
        "entry_ids": {str(k): v for k, v in sorted(entry_ids.items())},
        "gameweeks": args.gameweeks,
        "file_count": sum(1 for p in out.rglob("*.json") if p.name != "manifest.json"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\n{tally}  files={manifest['file_count']}")


if __name__ == "__main__":
    main()
