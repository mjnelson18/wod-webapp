import { useMemo, useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from 'recharts'
import { useTables, colourMap, can } from '../lib/data.js'
import { LeagueToggle, Section, Loading, Unavailable, ChartTip } from '../components/ui.jsx'

const BIN = 10

export default function SeasonTrends({ season, meta, league, setLeague }) {
  const { data, loading, error } = useTables(season, ['league_table', 'weekly_summary'])
  const [mode, setMode] = useState('cumulative')
  const colours = useMemo(() => colourMap(meta, league), [meta, league])

  const view = useMemo(() => {
    if (!data) return null
    const rows = data.league_table.filter(r => r.league === league).sort((a, b) => a.rank - b.rank)
    const gws = meta.gameweeks

    // one row per gameweek, one key per drafter — the shape Recharts wants
    const series = gws.map((g, i) => {
      const point = { gameweek: g }
      for (const r of rows) {
        point[r.short_name] = mode === 'cumulative'
          ? r.cumulative_by_gameweek?.[i]
          : mode === 'weekly'
            ? r.points_by_gameweek?.[i]
            : Math.round(((r.cumulative_by_gameweek?.[i] ?? 0) / (i + 1)) * 10) / 10
      }
      return point
    })

    // score histogram: how often each drafter landed in each 10-point band
    const scores = rows.flatMap(r => (r.points_by_gameweek ?? []).map(p => ({ short: r.short_name, p })))
    const lo = Math.floor(Math.min(...scores.map(s => s.p)) / BIN) * BIN
    const hi = Math.ceil((Math.max(...scores.map(s => s.p)) + 1) / BIN) * BIN
    const bins = []
    for (let b = lo; b < hi; b += BIN) {
      const row = { band: `${b}–${b + BIN - 1}` }
      for (const r of rows) {
        row[r.short_name] = scores.filter(s => s.short === r.short_name && s.p >= b && s.p < b + BIN).length
      }
      bins.push(row)
    }

    return { rows, series, bins }
  }, [data, league, meta.gameweeks, mode])

  if (error) return <div className="notice">Couldn&apos;t load season data: {String(error.message)}</div>
  if (loading || !view) return <Loading what="season trends" />

  const label = { cumulative: 'Cumulative points', weekly: 'Points per gameweek', average: 'Rolling average' }[mode]

  return (
    <>
      <Section
        title="Season Trends"
        aside={<LeagueToggle meta={meta} league={league} setLeague={setLeague} />}
      >
        <div className="toggle" style={{ marginBottom: 10 }}>
          {['cumulative', 'weekly', 'average'].map(m => (
            <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>
              {m === 'cumulative' ? 'Total' : m === 'weekly' ? 'Per GW' : 'Average'}
            </button>
          ))}
        </div>

        <h3 style={{ marginBottom: 6 }}>{label}</h3>
        <div className="chart">
          <ResponsiveContainer>
            <LineChart data={view.series} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="gameweek" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={18} />
              {/* domain is data-driven — the old chart hardcoded 35–55 and clipped */}
              <YAxis tickLine={false} axisLine={false} width={44} domain={['auto', 'auto']} />
              <Tooltip content={<ChartTip />} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              {view.rows.map(r => (
                <Line
                  key={r.short_name}
                  type="monotone"
                  dataKey={r.short_name}
                  stroke={colours[r.short_name]}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 3 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="Distribution of gameweek scores" note={`${BIN}-point bands · count of gameweeks`}>
        <div className="chart">
          <ResponsiveContainer>
            <BarChart data={view.bins} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="band" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} width={44} allowDecimals={false} />
              <Tooltip content={<ChartTip labelPrefix="" />} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              {view.rows.map(r => (
                <Bar key={r.short_name} dataKey={r.short_name} stackId="a" fill={colours[r.short_name]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="Table" note={`after gameweek ${meta.current_gameweek}`}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>#</th><th>Drafter</th><th>Total</th><th>GW</th><th>Form</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map(r => (
                <tr key={r.short_name}>
                  <td className="num">{r.rank}</td>
                  <td>
                    <span className="swatch" style={{ background: colours[r.short_name], display: 'inline-block', width: 8, height: 8, borderRadius: 2, marginRight: 6 }} />
                    {r.name ?? r.short_name}
                  </td>
                  <td className="num">{r.total}</td>
                  <td className="num">{r.gameweek_points}</td>
                  <td className="num">{r.form_points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {!can(meta, 'fixtures') && (
        <Unavailable what="Fixture difficulty and opposition views" season={meta.label} />
      )}
    </>
  )
}
