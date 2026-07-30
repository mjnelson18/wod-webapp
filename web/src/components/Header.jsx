import { useEffect, useRef } from 'react'
import { navigate, buildHash } from '../lib/router.js'
import { hasReview } from '../lib/review.jsx'

const TABS = [
  { view: 'gw', label: 'This Gameweek' },
  { view: 'season', label: 'Season Trends' },
  { view: 'compare', label: 'Cross-league' },
  // Written once a season is over, so it only appears for seasons that have one.
  { view: 'review', label: 'Season Review', when: season => hasReview(season) },
  { view: 'explorer', label: 'Explorer' },
]

export default function Header({ route, seasons, meta }) {
  const current = seasons.find(s => s.season === route.season)
  const tabs = TABS.filter(t => !t.when || t.when(route.season))

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
          What&apos;s On Draft <span>· data pack</span>
        </div>
        <select value={route.season ?? ''} onChange={onSeasonChange} aria-label="Season">
          {seasons.map(s => (
            <option key={s.season} value={s.season}>{s.label}</option>
          ))}
        </select>
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
