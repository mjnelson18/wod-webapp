"""The side pot: who owes what, month by month. Pure.

Purely a group convention (config.PotRules), never derivable from any payload:
everyone buys in once, then whoever scores the fewest FPL points across each
calendar month's gameweeks adds the monthly stake. Dunelmliga keeps one; the WOD
leagues don't, so for them this emits nothing and the tab never exists.

A gameweek belongs to the month its DEADLINE falls in, even when its matches run
over a month boundary. A month only settles — and only then names its loser —
once every one of its gameweeks is finalised (finished and data-checked), so a
provisional low scorer is never billed by a build that ran mid-gameweek. A tie
for last lists everyone on the low score and flags it; the group settles ties
offline, and the pot still gains exactly one stake for the month.
"""

import calendar

import pandas as pd


def gameweek_calendar(bootstrap_draft: dict) -> pd.DataFrame:
    """
    One row per gameweek: deadline, calendar month ("2026-08"), finalised flag.

    FPL deadlines sit 11:00–18:30 UK, never near midnight, so reading the month
    straight off the UTC timestamp cannot shift a gameweek across a boundary.
    The events list unwraps the same two shapes bootstrap_start_year tolerates.
    """
    events = bootstrap_draft.get("events", {})
    rows = events.get("data", events) if isinstance(events, dict) else events
    out = []
    for event in sorted(rows or [], key=lambda e: e.get("id", 0)):
        deadline = event.get("deadline_time")
        if not deadline or not event.get("id"):
            continue
        out.append({
            "gameweek": int(event["id"]),
            "deadline_time": str(deadline),
            "month": str(deadline)[:7],
            # The DRAFT bootstrap's events have no data_checked field (that is
            # the classic bootstrap's), so absent defaults to True — the same
            # reading as fetchers.source.finalised_gameweeks, or no month would
            # ever settle. When present (classic payloads, tests) it still
            # holds settlement back until bonus is checked.
            "finalised": bool(event.get("finished")) and bool(event.get("data_checked", True)),
        })
    return pd.DataFrame(out, columns=["gameweek", "deadline_time", "month", "finalised"])


def _month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{calendar.month_name[int(number)]} {year}"


def pot_tracker(by_week: pd.DataFrame, gw_calendar: pd.DataFrame, league) -> dict | None:
    """
    The whole pot story for one league, or None for a league without the rule.

    `by_week` is live_league_table's per-drafter per-gameweek frame; its
    `points_scored` is banked FPL points, deliberately not head-to-head league
    points — the pot is decided old-school, on points scored.
    """
    if getattr(league, "pot", None) is None:
        return None
    rules = league.pot

    mine = (by_week[by_week["league_code"] == league.code]
            if len(by_week) else by_week)
    drafters = sorted(str(s) for s in mine["short_name"].unique()) if len(mine) else []

    months, settled_count = [], 0
    if len(gw_calendar):
        for month, rows in gw_calendar.groupby("month", sort=True):
            gameweeks = [int(g) for g in rows["gameweek"]]
            played = mine[mine["gameweek"].isin(gameweeks)] if len(mine) else mine
            points = {}
            if len(played):
                sums = played.groupby("short_name")["points_scored"].sum()
                points = {str(k): int(v) for k, v in sums.items()}
            # Settled needs every gameweek final AND scores to judge — a future
            # month is all-unfinalised, a skipped one would have no points.
            settled = bool(rows["finalised"].all()) and bool(points)
            losers, tied = [], False
            if settled:
                low = min(points.values())
                losers = sorted(k for k, v in points.items() if v == low)
                tied = len(losers) > 1
                settled_count += 1
            months.append({
                "month": str(month),
                "label": _month_label(str(month)),
                "gameweeks": gameweeks,
                "points": points,
                "settled": settled,
                "losers": losers,
                "tied": tied,
            })

    return {
        "league": league.code,
        "rules": {"buy_in": rules.buy_in, "monthly_stake": rules.monthly_stake,
                  "currency": rules.currency},
        "drafters": drafters,
        "months": months,
        "settled_months": settled_count,
        "pot_total": len(drafters) * rules.buy_in + settled_count * rules.monthly_stake,
    }
