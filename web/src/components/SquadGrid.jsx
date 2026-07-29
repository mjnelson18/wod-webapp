import { useMemo } from 'react'
import { fullName } from '../lib/names.js'

/**
 * The flagship squad grid, extracted so the Gameweek view stays readable.
 *
 * One layout from 360px to desktop: a horizontally scrollable set of columns with
 * a sticky place-number gutter. On a phone you swipe across drafters; on desktop
 * all six fit.
 */

const STARTERS = 11
const SQUAD_SIZE = 15

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

export default function SquadGrid({ columns, meta, transfers, trades, league, gameweek }) {
  const flags = useMemo(() => {
    // latest successful transfer-in per (drafter, element) for the Tn# label
    const transferWeek = new Map()
    const thisWeekIn = new Map()
    const attemptedOut = new Set()
    for (const t of transfers ?? []) {
      if (t.league && t.league !== league) continue
      const key = `${t.short_name}|${t.element_in}`
      const ok = t.result === 'successful'
      if (ok && t.element_in != null) {
        transferWeek.set(key, Math.max(transferWeek.get(key) ?? 0, t.gameweek))
        if (t.gameweek === gameweek) thisWeekIn.set(key, t.kind)
      }
      if (!ok && t.gameweek === gameweek && t.element_out != null) {
        attemptedOut.add(`${t.short_name}|${t.element_out}`)
      }
    }
    const tradeWeek = new Map()
    for (const t of trades ?? []) {
      if (t.league && t.league !== league) continue
      if (t.element_in != null) tradeWeek.set(`${t.offered_by}|${t.element_in}`, t.gameweek)
      if (t.element_out != null) tradeWeek.set(`${t.received_by}|${t.element_out}`, t.gameweek)
    }
    return { transferWeek, thisWeekIn, attemptedOut, tradeWeek }
  }, [transfers, trades, league, gameweek])

  const decorate = (short, row) => {
    const key = `${short}|${row.element}`
    const benched = (row.place ?? 99) > STARTERS
    let flag = ''
    if (flags.thisWeekIn.has(key)) flag = flags.thisWeekIn.get(key) === 'waiver' ? 'W' : 'F'
    else if (flags.attemptedOut.has(key)) flag = 'AW'
    let sub = ''
    if (row.originally_starting === 1 && benched) sub = 'SF'
    else if (row.originally_starting === 0 && !benched) sub = 'SN'
    const acquired = row.in_original_draft === 1 && row.round != null ? `D${row.round}`
      : flags.tradeWeek.has(key) ? `Td${flags.tradeWeek.get(key)}`
      : flags.transferWeek.has(key) ? `Tn${flags.transferWeek.get(key)}` : '—'
    return { benched, flag, sub, acquired }
  }

  return (
    <>
      <div className="squad-scroll">
        <div className="squad-grid">
          <div className="squad-col squad-gutter">
            <div className="squad-head" style={{ background: 'transparent', border: 0 }} />
            {Array.from({ length: SQUAD_SIZE }, (_, i) => (
              <div key={i} className={`gutter-cell${i === STARTERS ? ' bench-start' : ''}`}>
                {i + 1}
              </div>
            ))}
          </div>

          {columns.map(col => (
            <div className="squad-col" key={col.short}>
              <div className="squad-head" title={fullName(meta, col.short)}>
                {col.short}
                <span className="gw-total">{col.gwTotal}</span>
                <span className="rank">
                  {col.table ? `#${col.table.rank} · ${col.table.total} pts` : ''}
                </span>
              </div>
              {[...col.cells]
                .sort((a, b) => (a.place ?? 99) - (b.place ?? 99))
                .map((c, i) => {
                  const d = decorate(col.short, c)
                  return (
                    <div
                      key={c.element}
                      className={`squad-cell${d.benched ? ' benched' : ''}${i === STARTERS ? ' bench-start' : ''}`}
                      style={{ background: heat(c.points_scored) }}
                      title={`${c.web_name} — ${c.total_points} pts`}
                    >
                      <div className="name">
                        <span>
                          {d.flag && <span className="flag">{d.flag} </span>}
                          {d.sub && <span className="flag">{d.sub} </span>}
                          {c.web_name}
                        </span>
                        <b>{c.total_points}</b>
                      </div>
                      <div className="meta">
                        {c.position}{c.team_name ? ` · ${c.team_name}` : ''}
                      </div>
                      <div className="meta">
                        {d.acquired}
                        {c.player_total_points != null && ` · ${c.player_total_points} S`}
                        {c.points_scored_cumulative != null && ` · ${c.points_scored_cumulative} R`}
                      </div>
                    </div>
                  )
                })}
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
