import { navigate, buildHash } from '../lib/router.js'

const TABS = [
  { view: 'gw', label: 'This Gameweek' },
  { view: 'season', label: 'Season Trends' },
  { view: 'compare', label: 'Leagues' },
  { view: 'explorer', label: 'Explorer' },
]

export default function Header({ route, seasons, meta }) {
  const current = seasons.find(s => s.season === route.season)

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
      <nav className="tabs">
        {TABS.map(t => {
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
