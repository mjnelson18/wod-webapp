import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { useTables, can } from '../lib/data.js'
import { Section, Loading, Unavailable, Stat, ChartTip } from '../components/ui.jsx'

/**
 * Leagues view — the one place that deliberately shows both leagues at once
 * rather than using the Prem/Conf toggle.
 */
export default function Compare({ season, meta }) {
  const { data, loading, error } = useTables(season, ['weekly_summary', 'weekly_points', 'league_table'])

  const view = useMemo(() => {
    if (!data) return null
    const { weekly_summary, weekly_points, league_table } = data
    const codes = meta.leagues.map(l => l.code)
    const [a, b] = codes

    // Head to head, compared as mean points per drafter — NOT league totals.
    // 2425 ran 5 Prem vs 7 Conf, so raw totals hand the bigger league every
    // gameweek on squad count alone. With equal sizes this is totals/6 for both
    // and the outcomes are identical, so normalising costs nothing.
    const sizeOf = c => meta.leagues.find(l => l.code === c)?.size
      ?? new Set(weekly_summary.filter(r => r.league === c).map(r => r.short_name)).size
    const sizes = Object.fromEntries(codes.map(c => [c, sizeOf(c)]))
    const unequal = new Set(Object.values(sizes)).size > 1

    const h2h = meta.gameweeks.map(g => {
      const point = { gameweek: g }
      for (const c of codes) {
        const total = weekly_summary
          .filter(r => r.gameweek === g && r.league === c)
          .reduce((s, r) => s + (Number(r.points_scored) || 0), 0)
        point[`${c}_total`] = total
        point[c] = Math.round((total / (sizes[c] || 1)) * 10) / 10
      }
      return point
    })
    const wins = Object.fromEntries(codes.map(c => [c, 0]))
    for (const p of h2h) {
      const best = codes.reduce((x, c) => ((p[c] ?? 0) > (p[x] ?? 0) ? c : x), codes[0])
      const tied = codes.every(c => p[c] === p[codes[0]])
      if (!tied) wins[best] += 1
    }
    const totals = Object.fromEntries(codes.map(c => [c, h2h.reduce((s, p) => s + (p[`${c}_total`] ?? 0), 0)]))
    const perDrafter = Object.fromEntries(codes.map(c =>
      [c, Math.round((totals[c] / (sizes[c] || 1)) * 10) / 10]))

    // squads at the latest gameweek, for overlap + exclusivity
    const latest = meta.current_gameweek
    const squads = new Map() // `${league}|${short}` -> Set(element)
    const ownedBy = new Map() // `${league}|${element}` -> short
    for (const r of weekly_summary) {
      if (r.gameweek !== latest) continue
      const key = `${r.league}|${r.short_name}`
      if (!squads.has(key)) squads.set(key, new Set())
      squads.get(key).add(r.element)
      ownedBy.set(`${r.league}|${r.element}`, r.short_name)
    }

    const rowsOf = c => league_table.filter(r => r.league === c).sort((x, y) => x.rank - y.rank)
    const overlap = {
      rows: rowsOf(b),
      cols: rowsOf(a),
      count: (rb, ca) => {
        const sb = squads.get(`${b}|${rb}`) ?? new Set()
        const sa = squads.get(`${a}|${ca}`) ?? new Set()
        let n = 0
        for (const el of sb) if (sa.has(el)) n++
        return n
      },
    }

    // players held in one league but nobody's squad in the other
    let exclusives = null
    if (can(meta, 'ownership_by_league')) {
      const byElement = new Map()
      for (const r of weekly_points) {
        if (r.gameweek !== latest || r.element == null) continue
        if (!byElement.has(r.element)) {
          byElement.set(r.element, { element: r.element, web_name: r.web_name, position: r.position, team_name: r.team_name, points: 0, owners: {} })
        }
        const e = byElement.get(r.element)
        e.points = Number(r.total_points) || 0
        if (r.league) e.owners[r.league] = ownedBy.get(`${r.league}|${r.element}`) ?? null
      }
      exclusives = [...byElement.values()]
        .map(e => ({ ...e, only: codes.find(c => e.owners[c]) && codes.find(c => !e.owners[c]) }))
        .filter(e => codes.some(c => e.owners[c]) && codes.some(c => !e.owners[c]))
        .sort((x, y) => y.points - x.points)
        .slice(0, 20)
    }

    return { codes, h2h, wins, totals, perDrafter, sizes, unequal, overlap, exclusives, latest }
  }, [data, meta])

  if (error) return <div className="notice">Couldn&apos;t load league data: {String(error.message)}</div>
  if (loading || !view) return <Loading what="league comparison" />

  const [a, b] = view.codes
  const nameOf = c => meta.leagues.find(l => l.code === c)?.name ?? c

  return (
    <>
      <Section title="Leagues head to head" note="both leagues shown together">
        <div className="stat-grid" style={{ marginBottom: 12 }}>
          {view.codes.map(c => (
            <Stat
              key={c}
              label={nameOf(c)}
              value={view.perDrafter[c].toLocaleString()}
              sub={`per drafter · ${view.totals[c].toLocaleString()} total · ${view.wins[c]} GW${view.wins[c] === 1 ? '' : 's'} won`}
            />
          ))}
          <Stat
            label="Margin per drafter"
            value={`${view.perDrafter[a] > view.perDrafter[b] ? nameOf(a) : nameOf(b)} +${Math.abs(Math.round((view.perDrafter[a] - view.perDrafter[b]) * 10) / 10).toLocaleString()}`}
          />
        </div>

        {view.unequal && (
          <div className="notice" style={{ marginBottom: 10 }}>
            <strong>Unequal leagues.</strong> {meta.label} ran{' '}
            {view.codes.map(c => `${view.sizes[c]} ${nameOf(c)}`).join(' vs ')}, so these
            comparisons use <strong>mean points per drafter</strong> — raw totals would hand every
            gameweek to the bigger league on squad count alone.
          </div>
        )}

        <h3 style={{ marginBottom: 6 }}>Points per drafter, by gameweek</h3>
        <div className="chart">
          <ResponsiveContainer>
            <BarChart data={view.h2h} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="gameweek" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={18} />
              <YAxis tickLine={false} axisLine={false} width={44} />
              <Tooltip content={<ChartTip />} />
              <ReferenceLine y={0} stroke="var(--muted)" />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              <Bar dataKey={a} fill="#00AEEF" name={nameOf(a)} />
              <Bar dataKey={b} fill="#FF6A13" name={nameOf(b)} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="Player overlap" note={`shared squad members at GW${view.latest}`}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{nameOf(b)} ↓ / {nameOf(a)} →</th>
                {view.overlap.cols.map(c => <th key={c.short_name}>{c.short_name}</th>)}
              </tr>
            </thead>
            <tbody>
              {view.overlap.rows.map(r => (
                <tr key={r.short_name}>
                  <td>{r.short_name}</td>
                  {view.overlap.cols.map(c => {
                    const n = view.overlap.count(r.short_name, c.short_name)
                    return (
                      <td
                        key={c.short_name}
                        className="num"
                        style={{ background: n ? `color-mix(in srgb, var(--accent) ${n * 12}%, transparent)` : undefined }}
                      >
                        {n || ''}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Owned in one league, free in the other" note={`top 20 by season points at GW${view.latest}`}>
        {view.exclusives ? (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Player</th><th>Pos</th><th>Pts</th>
                  {view.codes.map(c => <th key={c}>{nameOf(c)}</th>)}
                </tr>
              </thead>
              <tbody>
                {view.exclusives.map(e => (
                  <tr key={e.element}>
                    <td>{e.web_name}{e.team_name ? <span className="muted small"> {e.team_name}</span> : null}</td>
                    <td>{e.position}</td>
                    <td className="num">{e.points}</td>
                    {view.codes.map(c => (
                      <td key={c} className={e.owners[c] ? '' : 'muted'}>
                        {e.owners[c] ?? 'free'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Unavailable
            what="Cross-league ownership"
            season={meta.label}
            reason="That season's weekly points table has no per-league owner column."
          />
        )}
      </Section>
    </>
  )
}
