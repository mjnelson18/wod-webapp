"""Per-season configuration. Data, never logic.

Everything that varies by season lives here: league codes, league sizes,
promotion/relegation counts, and the entry excluded from each league. Transforms
read these rather than hardcoding, which is what lets 2425's one-off 5/7 split
build correctly alongside the settled 6/6.

Onboarding a new season = adding one entry here, then listing it on the site that
publishes it in sites.py (see README).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class League:
    """One league within a season."""

    code: str                 # short label used throughout the output ("Prem")
    name: str                 # display name ("Premiership")
    league_code: int | None   # FPL Draft league id; None for CSV-only archives
    size: int                 # real drafters, after exclusions
    promoted: int = 0
    relegated: int = 0
    # league_entry ids to drop. These entries did take part in the draft, so
    # their picks must be removed *and* the survivors renumbered — but they are
    # deliberately kept in the trades table.
    exclude_entries: tuple[int, ...] = ()
    # Repo-relative committed copy of this league's draft choices, used only when
    # the API serves none. `draft/<league>/choices` returns the league's current
    # or *next* draft, never a history, so a league that schedules a second draft
    # loses its first one from the API the moment it does. See build._draft_choices.
    draft_choices_fallback: str | None = None


@dataclass(frozen=True)
class Season:
    season: str
    label: str
    leagues: tuple[League, ...]
    total_gameweeks: int = 38
    squad_size: int = 15
    starting_xi: int = 11
    # 'live'  — fetch from the FPL API (the current season)
    # 'snapshot' — read a committed raw snapshot (2526)
    # 'csv'   — derive from reference/historical CSVs (2425; no raw exists)
    default_source: str = "live"
    snapshot_dir: str | None = None
    # Columns the FPL API can no longer supply for this season, backfilled from
    # the historical CSVs instead. See docs/notebook-recon.md 6.1 and 6.1b.
    csv_backfill: tuple[str, ...] = ()
    notes: str = ""

    def league(self, code: str) -> League:
        for lg in self.leagues:
            if lg.code == code:
                return lg
        raise KeyError(f"{self.season}: no league {code!r}")

    @property
    def league_codes(self) -> dict[str, int | None]:
        return {lg.code: lg.league_code for lg in self.leagues}

    @property
    def excluded_entries(self) -> set[int]:
        return {e for lg in self.leagues for e in lg.exclude_entries}


# --- 2425 -------------------------------------------------------------------
# The one exception: 5 Premiership / 7 Conference, 3 up / 1 down, because new
# joiners had to start in the Conference. Raw data is gone forever, so this
# season is built from the CSVs and cannot be logic-validated.
SEASON_2425 = Season(
    season="2425",
    label="2024/25",
    default_source="csv",
    leagues=(
        League(code="Prem", name="Premiership", league_code=None, size=5, relegated=1),
        League(code="Conf", name="Conference", league_code=None, size=7, promoted=3),
    ),
    notes="CSV-derived archive. No raw data exists; schema/plausibility checks only.",
)

# --- 2526 -------------------------------------------------------------------
# Complete season. Raw snapshot committed under reference/raw_2526 before the
# 2627 rollover; this is the regression oracle.
SEASON_2526 = Season(
    season="2526",
    label="2025/26",
    default_source="snapshot",
    snapshot_dir="reference/raw_2526",
    leagues=(
        League(
            code="Prem", name="Premiership", league_code=21123, size=6, relegated=2,
            # Peter Vickers' Premiership entry. He organised both leagues but only
            # played the Conference, filling this squad with deliberate dud picks.
            exclude_entries=(92234,),
        ),
        League(code="Conf", name="Conference", league_code=21136, size=6, promoted=2),
    ),
    # fantasy.premierleague.com had already rolled to 2627 when the snapshot was
    # taken, and the draft bootstrap carries 2627 element->team ids, so club and
    # cost columns come from the CSVs for this season.
    csv_backfill=("team", "team_name", "web_name", "now_cost", "selected_by_percent",
                  "team_difficulty", "opposition_difficulty"),
    notes="Snapshot-derived archive, cross-checked against the 2526 CSVs.",
)

# --- 2627 (current) ---------------------------------------------------------
# New leagues are created each season, so these ids change every year and cannot
# be guessed. Discover them from the league details endpoint once the draft is
# set up, then fill in below.
SEASON_2627 = Season(
    season="2627",
    label="2026/27",
    default_source="live",
    leagues=(
        League(
            code="Prem", name="Premiership",
            league_code=19736,  # "What's on Draft? Premiership"
            size=6, relegated=2,
            # Peter Vickers plays the Conference this season, so unlike 2526 there
            # is no dud Premiership entry to drop. Revisit if that changes.
            exclude_entries=(),
        ),
        League(
            code="Conf", name="Conference",
            league_code=19116,  # "What's on Draft? Conference"
            size=6, promoted=2,
            exclude_entries=(),
        ),
    ),
    notes="Live season. Both leagues draft 2026-08-14 19:30 UTC.",
)


def is_configured(season: Season) -> bool:
    """False while a live season still has <FILL IN> league codes."""
    return all(lg.league_code is not None for lg in season.leagues) or season.default_source != "live"
