"""Fixture-aware cron windows for the scheduled build.

GitHub cron schedules are static, so `.github/workflows/update.yml` cannot ask
the fixture list when to fire. This module closes that gap: it reads the game
state and the season's fixtures (published for all 38 gameweeks up front),
computes when the current and next gameweek's matches are actually on, and
rewrites the cron block between the BEGIN/END markers in the workflow file:

    python -m pipeline.windows            # print the windows
    python -m pipeline.windows --write    # rewrite the block in update.yml

`reschedule.yml` runs it daily and commits the result only when it changed —
roughly once a week, as the gameweek advances or kick-offs move for TV.

Why it exists: the repo is private, so every fired run bills a minimum of one
minute even when pipeline.schedule says there is nothing to do. Firing only
when football is on is what keeps the job inside the included Actions quota;
the README's schedule section has the arithmetic.

Each window runs from 10 minutes before kick-off to 3.5 hours after (the match
plus time for bonus to settle), and windows under an hour apart are merged.
Entries are pinned to day-of-month + month, which cron repeats *annually* —
past days are pruned on every rewrite, and if the file ever goes stale the
schedule degrades to the baseline cron, with any anniversary misfire absorbed
by the gate as one quiet run.

Stdlib-only, like pipeline.schedule: it runs before dependencies are installed.
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths
from .fetchers.http import FetchError, get_json
from .fetchers.source import DRAFT, FANTASY
from .schedule import _write_github_output

PAD_BEFORE = timedelta(minutes=10)
PAD_AFTER = timedelta(hours=3, minutes=30)
MERGE_GAP = timedelta(hours=1)
CADENCE = "*/10"  # GitHub delays short schedules; 10 min means 10-20 in practice

WORKFLOW = ".github/workflows/update.yml"
BEGIN = "# BEGIN match windows"
END = "# END match windows"
# Two gameweeks is ~14 lines even with every match on its own day; more than
# this means the input was not what we thought it was, so refuse to write it.
MAX_LINES = 30

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _kickoff(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def match_windows(fixtures, events, *, now: datetime):
    """Merged (start, end, kickoffs) windows for `events`, future ones only.

    Fixtures without a kickoff time (postponed, date TBC) are skipped — they
    get a window once rescheduled, via the daily rewrite.
    """
    kickoffs = sorted(
        _kickoff(f["kickoff_time"])
        for f in fixtures
        if f.get("event") in events and f.get("kickoff_time")
    )
    merged: list[tuple[datetime, datetime, list[datetime]]] = []
    for kickoff in kickoffs:
        start, end = kickoff - PAD_BEFORE, kickoff + PAD_AFTER
        if merged and start - merged[-1][1] <= MERGE_GAP:
            prev_start, prev_end, prev_kickoffs = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), prev_kickoffs + [kickoff])
        else:
            merged.append((start, end, [kickoff]))
    return [window for window in merged if window[1] > now]


def cron_lines(windows) -> list[str]:
    """One `- cron:` line per window per UTC day, with a human-readable note."""
    lines = []
    for start, end, kickoffs in windows:
        times = [k.strftime("%H:%M") for k in kickoffs]
        if len(times) == 1:
            label = f"1 kickoff, {times[0]} UTC"
        else:
            label = f"{len(times)} kickoffs, {times[0]}–{times[-1]} UTC"
        segment = start
        while True:
            day_end = datetime(segment.year, segment.month, segment.day,
                               tzinfo=timezone.utc) + timedelta(days=1)
            segment_end = min(end, day_end)
            first, last = segment.hour, (segment_end - timedelta(minutes=1)).hour
            hours = str(first) if first == last else f"{first}-{last}"
            cron = f"{CADENCE} {hours} {segment.day} {segment.month} *"
            lines.append(
                f"- cron: '{cron}'   "
                f"# {DAY_NAMES[segment.weekday()]} {segment.day} "
                f"{MONTH_NAMES[segment.month - 1]} — {label}"
            )
            if end <= day_end:
                break
            segment = day_end
    return lines


def replace_block(text: str, lines) -> str:
    """Replace the cron block between the markers, preserving their indent."""
    out, begun, skipping = [], False, False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(BEGIN):
            begun, skipping = True, True
            out.append(line)
            indent = line[: len(line) - len(line.lstrip())]
            if lines:
                out.extend(indent + entry for entry in lines)
            else:
                out.append(indent + "# (no upcoming fixtures — baseline cron only)")
        elif stripped.startswith(END):
            skipping = False
            out.append(line)
        elif not skipping:
            out.append(line)
    if not begun or skipping:
        raise ValueError(f"markers {BEGIN!r} / {END!r} missing or unterminated")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.windows")
    parser.add_argument("--write", action="store_true",
                        help="rewrite the cron block in the workflow file")
    parser.add_argument("--workflow", default=WORKFLOW)
    args = parser.parse_args(argv)

    try:
        game = get_json(f"{DRAFT}/game", throttle=0) or {}
        events = {e for e in (game.get("current_event"), game.get("next_event")) if e}
        fixtures = (get_json(f"{FANTASY}/fixtures/", throttle=0) or []) if events else []
    except FetchError as error:
        # Maintenance, back-off, or mid-rollover: keep the committed windows as
        # they are. The baseline cron still fires and tomorrow's run retries.
        print(f"leaving the schedule unchanged: {error}")
        _write_github_output(changed="false")
        return 0

    windows = match_windows(fixtures, events, now=datetime.now(timezone.utc))
    lines = cron_lines(windows)
    if len(lines) > MAX_LINES:
        print(f"refusing to write {len(lines)} cron lines (cap {MAX_LINES}) — "
              f"events {sorted(events)} don't look like one or two gameweeks")
        _write_github_output(changed="false")
        return 1

    for entry in lines:
        print(entry)
    if not lines:
        print(f"no upcoming fixtures for events {sorted(events) or 'none'}")

    changed = False
    if args.write:
        path = Path(args.workflow)
        if not path.is_absolute():
            path = paths.repo_root() / path
        text = path.read_text(encoding="utf-8")
        updated = replace_block(text, lines)
        changed = updated != text
        if changed:
            path.write_text(updated, encoding="utf-8", newline="\n")
        print("workflow updated" if changed else "workflow already up to date")

    _write_github_output(changed=str(changed).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
