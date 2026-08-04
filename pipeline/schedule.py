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
  rate_limited      API asked us to back off            skip, don't fail
  maintenance       API serving a holding page          skip, don't fail
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
from .fetchers.http import Maintenance, RateLimited, get_json
from .fetchers.source import DRAFT, FANTASY

# "Not now, and not because of us": the endpoint has either asked us to wait or
# has nothing to serve. These return before any interval lookup, so they carry no
# MINIMUM_INTERVAL entry — see decide() for why force does not override them.
SKIP_STATES = ("rate_limited", "maintenance")

MINIMUM_INTERVAL = {
    "live": 0,
    "settling": 15 * 60,
    "gameweek_open": 60 * 60,
    "between_gameweeks": 6 * 60 * 60,
    "off_season": 7 * 24 * 60 * 60,
    # Waiting on league codes: nothing to fetch, but keep checking daily so the
    # first configured run happens on its own rather than needing a manual nudge.
    "not_configured": 24 * 60 * 60,
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
    except Maintenance as error:
        # Between seasons this endpoint serves an HTML "Game Updating" page under
        # HTTP 200. Expected, so skip the run rather than reddening the workflow.
        return "maintenance", str(error)
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
    except Maintenance as error:
        # The two hosts roll over independently, so this one can be mid-update
        # while the draft host is already answering.
        return "maintenance", str(error)
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
    """
    Two independent answers, because they are different questions:

      should_build    is this run worth doing at all?
      season_ready    can the *current* season be fetched yet?

    They come apart between the API rolling over to a new season and that season's
    league codes being known — typically a few weeks, since the codes only exist
    after draft night. Through that window the current season cannot be built, but
    the site is still perfectly serviceable from the archives, so a push must still
    be able to deploy. Treating "not configured" as "do nothing" would freeze
    deployments for the whole pre-season.
    """
    season = get_season(season_id)
    state, reason = classify(season)
    season_ready = state != "not_configured"

    def result(should_build, why, interval=None, since=None):
        return {"should_build": should_build, "season_ready": season_ready,
                "state": state, "reason": why, "interval": interval, "since": since}

    # Never build into a back-off or a holding page, not even when forced. Unlike
    # not_configured, there is nothing to gain: the deployed site already holds a
    # full copy of this season, and the season index is assembled from whatever
    # season folders are on disk — so a run that can't fetch the current season
    # would deploy a site with it missing. Leaving the last good deploy alone is
    # strictly better, and the next run self-corrects.
    if state in SKIP_STATES:
        return result(False, reason)

    if force:
        return result(True, f"forced — {reason}", interval=0)

    interval = MINIMUM_INTERVAL[state]
    last = read_last_build(season.season)
    if last is None:
        return result(True, f"no previous build recorded — {reason}", interval)

    since = time.time() - last
    if since >= interval:
        return result(True, f"{int(since // 60)} min since last build — {reason}",
                      interval, since)
    wait = int((interval - since) // 60)
    return result(False, f"throttled: {wait} min until next {state} build — {reason}",
                  interval, since)


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
    print(f"season_ready: {result['season_ready']}")
    print(f"reason      : {result['reason']}")
    if not result["season_ready"]:
        print("note        : archives will still build and deploy; "
              "only the current season is skipped")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"should_build={str(result['should_build']).lower()}\n")
            handle.write(f"season_ready={str(result['season_ready']).lower()}\n")
            handle.write(f"state={result['state']}\n")
            handle.write(f"reason={result['reason']}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Schedule gate\n\n"
                         f"- **state**: `{result['state']}`\n"
                         f"- **build**: {result['should_build']}\n"
                         f"- **current season ready**: {result['season_ready']}\n"
                         f"- {result['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
