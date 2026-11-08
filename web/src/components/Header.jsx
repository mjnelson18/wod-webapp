import { useEffect, useRef } from 'react'
import { navigate, buildHash } from '../lib/router.js'
import { hasReview } from '../lib/review.jsx'

// `when` decides whether a tab exists at all for this season. Both uses are about
// a tab having nothing to say rather than being switched off: a review that hasn't
// been written, and a cross-league comparison on a site with one league.
const TABS = [
  { view: 'gw', label: 'This Gameweek' },
  { view: 'season', label: 'Season Trends' },
  // Only a league whose config keeps the side pot emits the data (Dunelmliga).
  { view: 'pot', label: 'Pot Tracker', when: (season, meta) => Boolean(meta?.capabilities?.pot_tracker) },
  { view: 'compare', label: 'Cross-league', when: (season, meta) => (meta?.leagues?.length ?? 0) > 1 },
  { view: 'h2h', label: 'Multiverse' },
  { view: 'draft', label: 'Draft Night' },
  // Written once a season is over, so it only appears for seasons that have one.
  { view: 'review', label: 'Season Review', when: season => hasReview(season) },
  { view: 'explorer', label: 'Explorer' },
]

const BRAND = import.meta.env.VITE_SITE_BRAND ?? "What's On Draft"
const TAGLINE = import.meta.env.VITE_SITE_TAGLINE ?? '· data pack'

// "as of 16:42" today, "as of Sat 16:42" within the week, else "as of 8 Nov 16:42"
// — in the viewer's own time zone, which is what "when did this last update"
// means to someone checking their phone at half-time.
function asOf(date) {
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  const withinWeek = now - date < 6 * 24 * 60 * 60 * 1000
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  if (sameDay) return time
  if (withinWeek) return `${date.toLocaleDateString(undefined, { weekday: 'short' })} ${time}`
  return `${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${time}`
}

// Before GW1 there are no gameweeks, so every chart and table would be empty.
// Draft Night is the exception: it needs only the picks, so it opens the moment
// draft night has happened. An unlisted stage (or meta still loading) shows all.
const STAGE_TABS = { pre_draft: [], drafted: ['draft'] }

export default function Header({ route, seasons, meta, builtAt }) {
  const current = seasons.find(s => s.season === route.season)
  const allowed = STAGE_TABS[meta?.stage]
  const tabs = TABS
    .filter(t => !allowed || allowed.includes(t.view))
    .filter(t => !t.when || t.when(route.season, meta))

  // The strip scrolls horizontally and five tabs no longer fit on a phone, so
  // the selected one has to be pulled into view — otherwise landing on a deep
  // link leaves the active tab off the right-hand edge.
  //
  // Done by hand rather than with scrollIntoView: inside a nested scroll
  // container that scrolled the *page* vertically and left the strip untouched.
  const strip = useRef(null)
  useEffect(() => {
    const nav = strip.current
    const active = nav?.querySelector('[aria-current="true"]')
    if (!active) return
    const bounds = nav.getBoundingClientRect()
    const tab = active.getBoundingClientRect()
    const margin = 12
    if (tab.right > bounds.right) nav.scrollLeft += tab.right - bounds.right + margin
    else if (tab.left < bounds.left) nav.scrollLeft -= bounds.left - tab.left + margin
  }, [route.view, route.season])

  function onSeasonChange(e) {
    const next = e.target.value
    const gw = seasons.find(s => s.season === next)?.current_gameweek
    // Keep the current view, but reset the gameweek — GW38 may not exist next season.
    navigate({ season: next, view: route.view, param: route.view === 'gw' ? (gw ?? null) : null })
  }

  return (
    <header className="header">
      <div className="header-top">
        <div className="brand">
          {BRAND} <span>{TAGLINE}</span>
          {builtAt && (
            <span className="as-of" title={builtAt.toLocaleString()}>
              {' '}· as of {asOf(builtAt)}
            </span>
          )}
        </div>
        {/* A site in its first season has nothing to select between. */}
        {seasons.length > 1 ? (
          <select value={route.season ?? ''} onChange={onSeasonChange} aria-label="Season">
            {seasons.map(s => (
              <option key={s.season} value={s.season}>{s.label}</option>
            ))}
          </select>
        ) : (
          <span className="small">{seasons[0]?.label}</span>
        )}
      </div>
      <nav className="tabs" ref={strip}>
        {tabs.map(t => {
          const param = t.view === 'gw' ? (route.view === 'gw' ? route.param : current?.current_gameweek) : null
          return (
            <a
              key={t.view}
              className="tab"
              aria-current={route.view === t.view}
              href={buildHash({ season: route.season, view: t.view, param: param ?? null })}
            >
              {t.label}
            </a>
          )
        })}
      </nav>
    </header>
  )
}
