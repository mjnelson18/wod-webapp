"""Which sites this repo publishes. Data, never logic.

One codebase, two audiences:

  wod         the "What's on Draft" data pack — Premiership and Conference,
              plus the 2425 and 2526 archives.
  dunelmliga  a different group of friends. One standalone league, no promotion
              or relegation, no history in this repo and no comparison drawn to
              the WOD leagues.

A site owns a slug — its folder under `data/`, and the Vite mode that brands it —
and the seasons it publishes. Everything else is shared: the same pipeline, the
same transforms, the same React app, one scheduled workflow. Branding and the
Pages sub-path live in `web/.env.<slug>`, not here.

Nothing downstream needs to know which site it is building — `build`, `outputs`
and `schedule` all take `--site` and read this module.
"""

from dataclasses import dataclass

from .seasons import League, Season, SEASON_2425, SEASON_2526, SEASON_2627

# --- dunelmliga -------------------------------------------------------------
# Six drafters, one division, first season in this app. Two things differ from
# the WOD leagues and both are deliberate:
#
#   * No promotion or relegation. `promoted`/`relegated` at zero is already
#     understood everywhere — the head-to-head view drops its promotion stat
#     rather than inventing one.
#   * FPL runs this league on head-to-head scoring (`scoring: 'h'`), where the
#     official table is won on weekly fixtures rather than points banked. This
#     app ranks on points scored, which is an honest table but not the one the
#     league plays for. Building the real W/D/L table from the `matches` payload
#     is tracked separately; until then `notes` says so on the site.
DUNELMLIGA_2627 = Season(
    season="2627",
    label="2026/27",
    default_source="live",
    leagues=(
        League(
            code="DL", name="Dunelmliga",
            league_code=32619,
            size=6, promoted=0, relegated=0,
            # This league re-drafts at GW21, which took its GW1 picks off the API.
            # The committed copy is the only surviving record of draft night.
            draft_choices_fallback="reference/draft_choices/dunelmliga_2627.json",
        ),
    ),
    notes="Head-to-head league on FPL. This table ranks on total points scored, "
          "not the weekly head-to-head result.",
)


@dataclass(frozen=True)
class Site:
    """
    One published site: which seasons it covers and where its data lands.

    Branding and the Pages sub-path are deliberately *not* here. They belong to
    the build that renders them, so they live in `web/.env.<slug>` and nothing
    has to be kept in step across two languages.
    """

    slug: str                    # data/<slug>/, and the Vite mode that styles it
    name: str                    # how the pipeline refers to it in its own output
    seasons: tuple[Season, ...]
    # Footballer-level history to borrow when this site has no season behind the
    # current one. players.json is a list of footballers — last season's points
    # and club — so this shares nothing about the other site's drafters, and it
    # is what puts "scored 239 last year" on a first-season draft board.
    player_history_site: str | None = None

    @property
    def current_season(self) -> str | None:
        """The one season built from the live API. None once a site is dormant."""
        live = [s.season for s in self.seasons if s.default_source == "live"]
        return live[0] if live else None

    @property
    def archive_seasons(self) -> tuple[str, ...]:
        """Frozen seasons: generated once from committed inputs, never refetched."""
        return tuple(s.season for s in self.seasons if s.default_source != "live")

    @property
    def season_ids(self) -> tuple[str, ...]:
        return tuple(s.season for s in self.seasons)

    def season(self, season_id: str) -> Season:
        for s in self.seasons:
            if s.season == str(season_id):
                return s
        raise KeyError(
            f"site {self.slug!r} has no season {season_id!r}; "
            f"known: {', '.join(self.season_ids) or 'none'}"
        )


SITE_WOD = Site(
    slug="wod",
    name="What's On Draft",
    seasons=(SEASON_2425, SEASON_2526, SEASON_2627),
)

# Pages serves one site per repo, so this one is published under a sub-path of the
# first (see web/.env.dunelmliga). Routing is hash-based, so deep links work there
# unchanged.
SITE_DUNELMLIGA = Site(
    slug="dunelmliga",
    name="Dunelmliga",
    seasons=(DUNELMLIGA_2627,),
    player_history_site="wod",
)

SITES: dict[str, Site] = {s.slug: s for s in (SITE_WOD, SITE_DUNELMLIGA)}

DEFAULT_SITE = "wod"


def get_site(slug: str | None = None) -> Site:
    slug = str(slug or DEFAULT_SITE)
    try:
        return SITES[slug]
    except KeyError:
        raise KeyError(
            f"unknown site {slug!r}; known: {', '.join(sorted(SITES))}"
        ) from None


def get_season(season: str, site: str | None = None) -> Season:
    """Resolve a season within a site. Defaults to the WOD site."""
    return get_site(site).season(season)
