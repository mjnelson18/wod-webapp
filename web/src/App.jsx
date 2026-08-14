import { useEffect, useState, lazy, Suspense } from 'react'
import { useRoute, navigate, buildHash } from './lib/router.js'
import { loadSeasons, loadMeta, useAsync } from './lib/data.js'
import Header from './components/Header.jsx'

// Lazy per view so a phone opening the gameweek grid doesn't download Recharts
// (chart views) or TanStack Table (explorer) it will never render.
const Gameweek = lazy(() => import('./views/Gameweek.jsx'))
const SeasonTrends = lazy(() => import('./views/SeasonTrends.jsx'))
const Compare = lazy(() => import('./views/Compare.jsx'))
const HeadToHead = lazy(() => import('./views/HeadToHead.jsx'))
const Explorer = lazy(() => import('./views/Explorer.jsx'))
const SeasonReview = lazy(() => import('./views/SeasonReview.jsx'))
const Draft = lazy(() => import('./views/Draft.jsx'))

const VIEW_COMPONENTS = {
  gw: Gameweek, season: SeasonTrends, compare: Compare,
  h2h: HeadToHead, draft: Draft, explorer: Explorer, review: SeasonReview,
}

export default function App() {
  const route = useRoute()
  const seasons = useAsync(loadSeasons, [])

  // Send bare/unknown URLs to the newest season's latest gameweek.
  useEffect(() => {
    if (!seasons.data) return
    const known = seasons.data.seasons.map(s => s.season)
    if (!route.season || !known.includes(route.season)) {
      const fallback = seasons.data.default ?? known[0]
      const gw = seasons.data.seasons.find(s => s.season === fallback)?.current_gameweek
      navigate({ season: fallback, view: 'gw', param: gw ?? null })
    }
  }, [seasons.data, route.season])

  const season = route.season
  const meta = useAsync(() => (season ? loadMeta(season) : Promise.resolve(null)), [season])

  // League selection lives above the views so it persists across tab changes.
  const [league, setLeague] = useState(null)
  useEffect(() => {
    if (meta.data?.leagues?.length) setLeague(prev =>
      meta.data.leagues.some(l => l.code === prev) ? prev : meta.data.leagues[0].code)
  }, [meta.data])

  if (seasons.error) return <Fatal error={seasons.error} />
  if (!seasons.data || !season) return <div className="spinner">Loading…</div>

  const View = VIEW_COMPONENTS[route.view] ?? Gameweek
  // A season can be listed before it has any gameweeks — see NotStarted.
  const notStarted = Boolean(meta.data?.stage) && meta.data.stage !== 'live'

  return (
    <>
      <Header
        route={route}
        seasons={seasons.data.seasons}
        meta={meta.data}
      />
      <main>
        {meta.error && <Fatal error={meta.error} />}
        {meta.loading && <div className="spinner">Loading {season}…</div>}
        {meta.data && league && (
          notStarted && !(meta.data.stage === 'drafted' && route.view === 'draft')
            ? <NotStarted meta={meta.data} />
            : (
              <Suspense fallback={<div className="spinner">Loading view…</div>}>
                <View
                  season={season}
                  meta={meta.data}
                  league={league}
                  setLeague={setLeague}
                  route={route}
                />
              </Suspense>
            )
        )}
      </main>
    </>
  )
}

/**
 * A season that exists but has not kicked off.
 *
 * The leagues are created weeks before GW1, so the season appears in the selector
 * with nothing behind it yet. Say so plainly and show what does exist — the
 * leagues and who is in them — rather than rendering a wall of empty charts.
 */
function NotStarted({ meta }) {
  const drafted = meta.stage === 'drafted'
  const inLeague = code => meta.drafters
    .filter(d => d.league === code)
    .map(d => d.name || d.short_name)

  return (
    <div className="section" style={{ margin: 12 }}>
      <h2>{meta.label} hasn&apos;t started yet</h2>
      <div className="notice">
        Points, tables and trends appear once <strong>gameweek 1</strong> kicks off.{' '}
        {drafted
          ? 'Draft night is done — the picks are on the Draft Night tab.'
          : 'The draft hasn’t happened yet, so there are no picks to show either.'}
      </div>
      {meta.leagues.map(l => {
        const names = inLeague(l.code)
        return (
          <div key={l.code} style={{ marginTop: 12 }}>
            <strong>{l.name}</strong>
            <div className="small">
              {names.length ? names.join(' · ') : 'no entries yet'}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Fatal({ error }) {
  return (
    <div className="notice" style={{ margin: 12 }}>
      <strong>Couldn't load data.</strong>{' '}
      {String(error?.message ?? error)}
      <div className="small" style={{ marginTop: 6 }}>
        Run <code>npm run fixtures</code> to build dev data, or check that the pipeline wrote
        {' '}<code>web/public/data/</code>.
      </div>
    </div>
  )
}

export { buildHash }
