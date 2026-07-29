"""Raw-payload sources.

Every transform takes raw payloads, never a Source, so the same transform code
runs against the live API, a committed snapshot, or the cache. That is what makes
the 2526 regression test possible: run the pipeline on reference/raw_2526 and
compare to the CSVs.

Gameweeks are 1-indexed throughout — GW1 is `event/1`. The notebook's
`event/{gameweek+1}` was a zero-based-loop artifact and is not carried forward.
"""

import json
from pathlib import Path

from .. import paths
from .http import get_json

DRAFT = "https://draft.premierleague.com/api"
FANTASY = "https://fantasy.premierleague.com/api"


class SnapshotSource:
    """Reads a committed raw snapshot. Never touches the network."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        if not self.root.is_absolute():
            self.root = paths.repo_root() / self.root
        if not self.root.exists():
            raise FileNotFoundError(f"snapshot not found: {self.root}")

    def _read(self, relative: str):
        path = self.root / relative
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def game(self):
        return self._read("game.json")

    def bootstrap_draft(self):
        return self._read("bootstrap_static_draft.json")

    def bootstrap_fantasy(self):
        return self._read("bootstrap_static_fantasy.json")

    def fixtures(self):
        return self._read("fixtures.json")

    def league_details(self, league_code):
        return self._read(f"league/{league_code}_details.json")

    def draft_choices(self, league_code):
        return self._read(f"league/{league_code}_choices.json")

    def transactions(self, league_code):
        return self._read(f"league/{league_code}_transactions.json")

    def trades(self, league_code):
        return self._read(f"league/{league_code}_trades.json")

    def event_live(self, gameweek):
        return self._read(f"event/live_gw{int(gameweek):02d}.json")

    def entry_event(self, entry_id, gameweek):
        return self._read(f"entry/{entry_id}/gw{int(gameweek):02d}.json")


class LiveSource:
    """
    Fetches from the FPL API, caching payloads that can never change again.

    Incremental rule — the single biggest win over the notebook, which refetched
    every gameweek for every entry on every run:

      * game status                     always refetched
      * bootstraps, fixtures, league    always refetched (they move)
      * transactions, trades            always refetched (append-only, cheap)
      * event live / entry picks        cached once the gameweek is finalised

    A gameweek is only finalised when the API says so — points and bonus are
    provisional while matches are live, so an in-progress gameweek is never
    written to the cache.
    """

    def __init__(self, season: str, *, cache_dir: Path | None = None, force: bool = False):
        self.season = str(season)
        self.cache = (cache_dir or paths.cache_dir()) / self.season
        self.force = force
        self._finalised: set[int] | None = None
        self.stats = {"fetched": 0, "cached": 0}

    # -- cache plumbing ----------------------------------------------------

    def _cached(self, relative: str):
        path = self.cache / relative
        if self.force or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        self.stats["cached"] += 1
        return payload

    def _store(self, relative: str, payload) -> None:
        path = self.cache / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _fetch(self, url: str):
        payload = get_json(url)
        self.stats["fetched"] += 1
        return payload

    # -- always-fresh endpoints -------------------------------------------

    def game(self):
        return self._fetch(f"{DRAFT}/game")

    def bootstrap_draft(self):
        return self._fetch(f"{DRAFT}/bootstrap-static")

    def bootstrap_fantasy(self):
        return self._fetch(f"{FANTASY}/bootstrap-static")

    def fixtures(self):
        return self._fetch(f"{FANTASY}/fixtures/")

    def league_details(self, league_code):
        return self._fetch(f"{DRAFT}/league/{league_code}/details")

    def draft_choices(self, league_code):
        return self._fetch(f"{DRAFT}/draft/{league_code}/choices")

    def transactions(self, league_code):
        return self._fetch(f"{DRAFT}/draft/league/{league_code}/transactions")

    def trades(self, league_code):
        return self._fetch(f"{DRAFT}/draft/league/{league_code}/trades")

    # -- cacheable-once-final endpoints -----------------------------------

    def finalised_gameweeks(self) -> set[int]:
        """Gameweeks whose points can no longer change (bonus applied, all done)."""
        if self._finalised is None:
            bootstrap = self.bootstrap_draft() or {}
            events = bootstrap.get("events", {})
            rows = events.get("data", events) if isinstance(events, dict) else events
            self._finalised = {
                int(e["id"]) for e in (rows or [])
                if e.get("finished") and e.get("data_checked", True)
            }
        return self._finalised

    def _cacheable_gw(self, gameweek: int) -> bool:
        return int(gameweek) in self.finalised_gameweeks()

    def event_live(self, gameweek):
        relative = f"event/live_gw{int(gameweek):02d}.json"
        hit = self._cached(relative)
        if hit is not None:
            return hit
        payload = self._fetch(f"{DRAFT}/event/{int(gameweek)}/live")
        if payload is not None and self._cacheable_gw(gameweek):
            self._store(relative, payload)
        return payload

    def entry_event(self, entry_id, gameweek):
        relative = f"entry/{entry_id}/gw{int(gameweek):02d}.json"
        hit = self._cached(relative)
        if hit is not None:
            return hit
        payload = self._fetch(f"{DRAFT}/entry/{entry_id}/event/{int(gameweek)}")
        if payload is not None and self._cacheable_gw(gameweek):
            self._store(relative, payload)
        return payload


def build_source(season_config, *, source: str | None = None, force: bool = False):
    """Pick a source for a season: 'live', 'snapshot', or the season default."""
    kind = source or season_config.default_source
    if kind == "snapshot":
        if not season_config.snapshot_dir:
            raise ValueError(f"{season_config.season} has no snapshot_dir configured")
        return SnapshotSource(season_config.snapshot_dir)
    if kind == "live":
        return LiveSource(season_config.season, force=force)
    raise ValueError(f"no raw source for kind {kind!r} (csv seasons use the adapter)")
