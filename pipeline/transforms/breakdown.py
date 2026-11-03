"""What each player's gameweek score was made of. Pure.

The event/{gw}/live payload carries an `explain` array per element — the stat
lines (minutes, goals, bonus...) behind the number — which the pipeline fetches
anyway and previously ignored. One entry per fixture, so a double gameweek
yields two, each with its own subtotal.

Restricted to elements appearing in that gameweek's weekly_summary: the squads
view is the only consumer, and the full player pool would be ~700 rows per week
of mostly unowned names.
"""

import pandas as pd


def points_breakdown(live_by_gameweek: dict,
                     weekly_summary: pd.DataFrame) -> dict[int, list[dict]]:
    """{gameweek: [{element, fixtures: [{fixture, total, items: [...]}]}]}.

    Values are plain Python ints throughout, so the output is JSON-safe by
    construction (`_dump` runs with allow_nan=False). Empty inputs — an archive
    with no raw, preseason — come back as {} and the capability stays off.
    """
    out = {}
    if not live_by_gameweek or weekly_summary is None or not len(weekly_summary):
        return out

    for gw, payload in sorted(live_by_gameweek.items()):
        owned = weekly_summary.loc[weekly_summary["gameweek"] == gw, "element"]
        wanted = set(pd.to_numeric(owned, errors="coerce").dropna().astype(int))
        elements = (payload or {}).get("elements") or {}
        if not wanted or not elements:
            continue

        records = []
        for key, details in elements.items():
            try:
                element = int(key)
            except (TypeError, ValueError):
                continue
            if element not in wanted:
                continue
            fixtures = []
            for entry in (details or {}).get("explain") or []:
                # Each entry is [items, fixture_id].
                if not isinstance(entry, (list, tuple)) or not entry:
                    continue
                items = [{
                    "stat": item.get("stat"),
                    "name": item.get("name"),
                    "points": int(item.get("points") or 0),
                    "value": int(item.get("value") or 0),
                } for item in (entry[0] or [])]
                fixtures.append({
                    "fixture": int(entry[1]) if len(entry) > 1 and entry[1] is not None else None,
                    "total": sum(item["points"] for item in items),
                    "items": items,
                })
            if fixtures:
                records.append({"element": element, "fixtures": fixtures})
        if records:
            out[int(gw)] = sorted(records, key=lambda r: r["element"])
    return out
