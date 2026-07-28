import { useMemo } from 'react'
import { useTables, can } from '../lib/data.js'
import { navigate } from '../lib/router.js'
import { LeagueToggle, Section, Loading, Unavailable, Stat } from '../components/ui.jsx'

const STARTERS = 11
const SQUAD_SIZE = 15

/** Points -> heat step. Thresholds match the old report's visual weighting. */
function heat(points) {
  const p = Number(points) || 0
  if (p <= 0) return 'var(--heat-0)'
  if (p <= 2) return 'var(--heat-1)'
  if (p <= 4) return 'var(--heat-2)'
  if (p <= 6) return 'var(--heat-3)'
  if (p <= 9) return 'var(--heat-4)'
  if (p <= 13) return 'var(--heat-5)'
  return 'var(--heat-6)'
}

export default function Gameweek({ season, meta, league, setLeague, route }) {
  const gw = Number(route.param) || meta.current_gameweek
  const { data, loading, error } = useTables(season, ['weekly_summary', 'league_table', 'transfers', 'trades'])

  const view = useMemo(() => {
    if (!data) return null
    const { weekly_summary, league_table, transfers, trades } = data

    const table = league_table.filter(r => r.league === league).sort((a, b) => a.rank - b.rank)
    const order = table.map(r => r.short_name)
    const rows = weekly_summary.filter(r => r.league === league && r.gameweek === gw)

    // Latest successful transfer-in gameweek per (drafter, element), for the Tn# label.
    const transferWeek = new Map()
    const thisWeekIn = new Map()
    const attemptedOut = new Set()
    for (const t of transfers) {
      if (t.league && t.league !== league) continue
      const key = `${t.short_name}|${t.element_in}`
      const successful = t.result === 'successful' || t.result === 'a'
      if (successful && t.element_in != null) {
        transferWeek.set(key, Math.max(transferWeek.get(key) ?? 0, t.gameweek))
        if (t.gameweek === gw) thisWeekIn.set(key, t.kind)
      }
      if (!successful && t.gameweek === gw && t.element_out != null) {
        attemptedOut.add(`${t.short_name}|${t.element_out}`)
      }
    }

    const tradeWeek = new Map()
    for (const t of trades ?? []) {
      if (t.league && t.league !== league) continue
      if (t.element_in != null) tradeWeek.set(`${t.offered_by}|${t.element_in}`, t.gameweek)
      if (t.element_out != null) tradeWeek.set(`${t.received_by}|${t.element_out}`, t.gameweek)
    }

    const columns = order.map(short => {
      const squad = rows.filter(r => r.short_name === short)
        .sort((a, b) => (a.place ?? 99) - (b.place ?? 99))
      const gwTotal = squad.reduce((s, r) => s + (Number(r.points_scored) || 0), 0)
      const optimal = squad.reduce((s, r) => s + (Number(r.optimal_points) || 0), 0)
      const cells = squad.map(r => {
        const key = `${short}|${r.element}`
        const benched = (r.place ?? 99) > STARTERS
        let flag = ''
        if (thisWeekIn.has(key)) flag = thisWeekIn.get(key) === 'waiver' ? 'W' : 'F'
        else if (attemptedOut.has(key)) flag = 'AW'
        let sub = ''
        if (r.originally_starting === 1 && benched) sub = 'SF'
        else if (r.originally_starting === 0 && !benched) sub = 'SN'
        const acquired = r.in_original_draft === 1 && r.round != null
          ? `D${r.round}`
          : tradeWeek.has(key) ? `Td${tradeWeek.get(key)}`
          : transferWeek.has(key) ? `Tn${transferWeek.get(key)}` : '—'
        return { ...r, benched, flag, sub, acquired }
      })
      return { short, table: table.find(t => t.short_name === short), gwTotal, optimal, cells }
    })

    const best = columns.reduce((a, b) => (b.gwTotal > (a?.gwTotal ?? -1) ? b : a), null)
    const worst = columns.reduce((a, b) => (b.gwTotal < (a?.gwTotal ?? 1e9) ? b : a), null)
    const lost = columns.reduce((s, c) => s + Math.max(0, c.optimal - c.gwTotal), 0)
    return { columns, best, worst, lost }
  }, [data, league, gw])

  if (error) return <div className="notice">Couldn&apos;t load gameweek data: {String(error.message)}</div>
  if (loading || !view) return <Loading what={`gameweek ${gw}`} />

  return (
    <>
      <Section
        title={`Gameweek ${gw}`}
        aside={<LeagueToggle meta={meta} league={league} setLeague={setLeague} />}
      >
        <div className="chips" style={{ marginBottom: 10 }}>
          {meta.gameweeks.map(g => (
            <button
              key={g}
              className="chip"
              aria-pressed={g === gw}
              onClick={() => navigate({ season, view: 'gw', param: g })}
            >
              {g}
            </button>
          ))}
        </div>

        <div className="stat-grid">
          <Stat label="Gameweek high" value={view.best ? `${view.best.short} · ${view.best.gwTotal}` : '—'} />
          <Stat label="Gameweek low" value={view.worst ? `${view.worst.short} · ${view.worst.gwTotal}` : '—'} />
          {can(meta, 'optimal_points') && (
            <Stat
              label="Points left on the bench"
              value={Math.round(view.lost)}
              sub="league total vs optimal XI"
            />
          )}
        </div>
      </Section>

      <Section title="Squads" note="Swipe across · shading is points scored this week">
        <SquadGrid columns={view.columns} meta={meta} />
      </Section>
    </>
  )
}

function SquadGrid({ columns, meta }) {
  return (
    <>
      <div className="squad-scroll">
        <div className="squad-grid">
          {/* sticky place-number gutter so rows stay readable while scrolling */}
          <div className="squad-col squad-gutter">
            <div className="squad-head" style={{ background: 'transparent', border: 0 }} />
            {Array.from({ length: SQUAD_SIZE }, (_, i) => (
              <div
                key={i}
                className={`gutter-cell${i === STARTERS ? ' bench-start' : ''}`}
              >
                {i + 1}
              </div>
            ))}
          </div>

          {columns.map(col => (
            <div className="squad-col" key={col.short}>
              <div className="squad-head">
                {col.short}
                <span className="gw-total">{col.gwTotal}</span>
                <span className="rank">
                  {col.table ? `#${col.table.rank} · ${col.table.total} pts` : ''}
                </span>
              </div>
              {col.cells.map((c, i) => (
                <div
                  key={c.element}
                  className={`squad-cell${c.benched ? ' benched' : ''}${i === STARTERS ? ' bench-start' : ''}`}
                  style={{ background: heat(c.points_scored) }}
                  title={`${c.web_name} — ${c.total_points} pts`}
                >
                  <div className="name">
                    <span>
                      {c.flag && <span className="flag">{c.flag} </span>}
                      {c.sub && <span className="flag">{c.sub} </span>}
                      {c.web_name}
                    </span>
                    <b>{c.total_points}</b>
                  </div>
                  <div className="meta">
                    {c.position}{c.team_name ? ` · ${c.team_name}` : ''}
                  </div>
                  <div className="meta">
                    {c.acquired}
                    {c.player_total_points != null && ` · ${c.player_total_points} S`}
                    {c.points_scored_cumulative != null && ` · ${c.points_scored_cumulative} R`}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <p className="legend">
        <code>W</code> waiver this week · <code>F</code> free agent · <code>AW</code> attempted waiver ·{' '}
        <code>SN</code> subbed on · <code>SF</code> subbed off · <code>D#</code> draft round ·{' '}
        <code>Tn#</code> transferred in GW# · <code>Td#</code> traded GW#
        {meta.capabilities.cumulative && <> · <code>S</code> season total · <code>R</code> realised by drafter</>}
        <br />
        Dashed border = benched. The heavy line separates the starting XI from the bench.
      </p>
    </>
  )
}
