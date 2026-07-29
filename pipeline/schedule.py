"""Self-throttling gate for the scheduled build.

Runs before anything expensive and answers one question: is it worth building
right now? Deliberately cheap — `/api/game` (162 bytes) plus one gameweek of
fixtures (~3 KB), rather than the 1.4 MB bootstrap or a 610 KB live payload.

    python -m pipeline.schedule --season 2627

Writes `should_build`, `state` and `reason` to $GITHUB_OUTPUT when present, and
prints them either way. Exit code is always 0 — "nothing to do" is a success.

States and their minimum intervals:

  live              a match is in progress            every run (~10 min)
  settling          matches done, bonus not applied    15 min
  gameweek_open     gameweek open, no live match now    1 hour
  between_gameweeks gameweek done, next one pending     6 hours
  off_season        no next gameweek                    7 days
  not_configured    league codes still <FILL IN>        skip, don't fail

The interval is enforced against the last successful build recorded in
pipeline/cache, which the workflow restores from the Actions cache. Without that
the pipeline would also refetch all 38 gameweeks every run.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from . import paths
from .config import get_season, is_configured
from .fetchers.http import RateLimited, get_json
from .fetchers.source import DRAFT, FANTASY

MINIMUM_INTERVAL = {
    "live": 0,
    "settling": 15 * 60,
    "gameweek_open": 60 * 60,
    "between_gameweeks": 6 * 60 * 60,
    "off_season": 7 * 24 * 60 * 60,
}

STATE_FILE = "last_build.json"


def _state_path(season: str):
    return paths.cache_dir() / str(season) / STATE_FILE


def read_last_build(season: str) -> float | None:
    path = _state_path(season)
    if not path.exists():
        return None
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["completed_at"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def record_build(season: str, *, digest: str | None = None) -> None:
    path = _state_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "completed_at": time.time(),
        "completed_at_iso": datetime.now(timezone.utc).isoformat(),
        "digest": digest,
    }), encoding="utf-8")


def classify(season) -> tuple[str, str]:
    """Return (state, human-readable reason) from the two cheap endpoints."""
    if season.default_source == "live" and not is_configured(season):
        return "not_configured", (
            f"{season.season} league codes are still <FILL IN> in pipeline/config/seasons.py"
        )

    try:
        game = get_json(f"{DRAFT}/game", throttle=0) or {}
    except RateLimited as error:
        # Don't build into a throttle. The next cron retries within minutes.
        return "rate_limited", str(error)
    current = game.get("current_event")
    finished = bool(game.get("current_event_finished"))
    next_event = game.get("next_event")

    if not current:
        return "off_season", "no current gameweek yet"

    if finished and not next_event:
        return "off_season", f"GW{current} finished and no next gameweek — season over"

    if finished:
        return "between_gameweeks", f"GW{current} finished, GW{next_event} pending"

    # gameweek is open: is a match actually in progress?
    try:
        fixtures = get_json(f"{FANTASY}/fixtures/?event={current}", throttle=0) or []
    except RateLimited as error:
        return "rate_limited", str(error)
    started = [f for f in fixtures if f.get("started")]
    in_play = [f for f in started if not f.get("finished_provisional")]
    if in_play:
        return "live", f"GW{current}: {len(in_play)} of {len(fixtures)} fixtures in play"

    awaiting_bonus = [f for f in started if f.get("finished_provisional") and not f.get("finished")]
    if awaiting_bonus:
        return "settling", f"GW{current}: {len(awaiting_bonus)} fixtures awaiting final bonus"

    return "gameweek_open", (
        f"GW{current} open, {len(started)} of {len(fixtures)} fixtures played, none live"
    )


def decide(season_id: str, *, force: bool = False) -> dict:
    season = get_season(season_id)
    state, reason = classify(season)

    # Neither is a failure: one means the season isn't set up yet, the other means
    # the API asked us to wait. Both should skip quietly.
    if state in ("not_configured", "rate_limited"):
        return {"should_build": False, "state": state, "reason": reason,
                "interval": None, "since": None}

    if force:
        return {"should_build": True, "state": state, "reason": f"forced — {reason}",
                "interval": 0, "since": None}

    interval = MINIMUM_INTERVAL[state]
    last = read_last_build(season.season)
    if last is None:
        return {"should_build": True, "state": state,
                "reason": f"no previous build recorded — {reason}",
                "interval": interval, "since": None}

    since = time.time() - last
    if since >= interval:
        return {"should_build": True, "state": state,
                "reason": f"{int(since // 60)} min since last build — {reason}",
                "interval": interval, "since": since}
    wait = int((interval - since) // 60)
    return {"should_build": False, "state": state,
            "reason": f"throttled: {wait} min until next {state} build — {reason}",
            "interval": interval, "since": since}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.schedule")
    parser.add_argument("--season", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--record", action="store_true",
                        help="record a completed build instead of deciding")
    parser.add_argument("--digest", default=None)
    args = parser.parse_args(argv)

    if args.record:
        record_build(args.season, digest=args.digest)
        print(f"recorded build for {args.season}")
        return 0

    result = decide(args.season, force=args.force)
    print(f"state       : {result['state']}")
    print(f"should_build: {result['should_build']}")
    print(f"reason      : {result['reason']}")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"should_build={str(result['should_build']).lower()}\n")
            handle.write(f"state={result['state']}\n")
            handle.write(f"reason={result['reason']}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Schedule gate\n\n"
                         f"- **state**: `{result['state']}`\n"
                         f"- **build**: {result['should_build']}\n"
                         f"- {result['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
