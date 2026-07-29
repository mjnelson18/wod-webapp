import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ReferenceLine,
} from 'recharts'
import { useTables, can } from '../lib/data.js'
import { fullName, leagueName, round, signed } from '../lib/names.js'
import {
  Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead, ChartTip,
} from '../components/ui.jsx'

const TOP_N = 20
const LOOKAHEAD = 6

/**
 * Cross-league view — the one place that deliberately shows both leagues together
 * rather than using the Prem/Conf toggle.
 */
export default function Compare({ season, meta }) {
  const { data, loading, error } = useTables(season, [
    'weekly_summary', 'weekly_points', 'league_table', 'available_players', 'fixtures',
  ])

  const v = useMemo(() => {
    if (!data) return null
    const { weekly_summary, weekly_points, league_table, available_players, fixtures } = data
    const codes = meta.leagues.map(l => l.code)
    const [a, b] = codes

    // Compared per drafter, not as league totals: 2425 ran 5 v 7, and raw totals
    // hand every gameweek to the bigger league on squad count alone.
    const sizeOf = c => meta.leagues.find(l => l.code === c)?.size
      ?? new Set(weekly_summary.filter(r => r.league === c).map(r => r.short_name)).size
    const sizes = Object.fromEntries(codes.map(c => [c, sizeOf(c)]))
    const unequal = new Set(Object.values(sizes)).size > 1

    const h2h = meta.gameweeks.map(g => {
      const row = { gameweek: g }
      for (const c of codes) {
        const total = weekly_summary.filter(r => r.gameweek === g && r.league === c)
          .reduce((s, r) => s + (Number(r.points_scored) || 0), 0)
        row[`${c}_total`] = total
        row[c] = round(total / (sizes[c] || 1))
      }
      row.margin = round((row[a] ?? 0) - (row[b] ?? 0))
      return row
    })
    const wins = Object.fromEntries(codes.map(c => [c, 0]))
    for (const p of h2h) {
      const best = codes.reduce((x, c) => ((p[c] ?? 0) > (p[x] ?? 0) ? c : x), codes[0])
      if (!codes.every(c => p[c] === p[codes[0]])) wins[best] += 1
    }
    const totals = Object.fromEntries(codes.map(c => [c, h2h.reduce((s, p) => s + (p[`${c}_total`] ?? 0), 0)]))
    const perDrafter = Object.fromEntries(codes.map(c => [c, round(totals[c] / (sizes[c] || 1))]))

    // squads at the latest gameweek
    const latest = meta.current_gameweek
    const squads = new Map()
    const ownedBy = new Map()
    for (const r of weekly_summary) {
      if (r.gameweek !== latest) continue
      const key = `${r.league}|${r.short_name}`
      if (!squads.has(key)) squads.set(key, new Set())
      squads.get(key).add(r.element)
      ownedBy.set(`${r.league}|${r.element}`, r.short_name)
    }
    const rowsOf = c => league_table.filter(r => r.league === c).sort((x, y) => x.rank - y.rank)
    const overlap = {
      rows: rowsOf(b), cols: rowsOf(a),
      count: (rb, ca) => {
        const sb = squads.get(`${b}|${rb}`) ?? new Set()
        const sa = squads.get(`${a}|${ca}`) ?? new Set()
        let n = 0
        for (const el of sb) if (sa.has(el)) n++
        return n
      },
    }

    // season totals per player, plus who holds them in each league
    let players = null
    if (can(meta, 'ownership_by_league')) {
      const byElement = new Map()
      for (const r of weekly_points) {
        if (r.element == null) continue
        if (!byElement.has(r.element)) {
          byElement.set(r.element, {
            element: r.element, web_name: r.web_name, position: r.position,
            team_name: r.team_name, total: 0, owners: {},
          })
        }
        const e = byElement.get(r.element)
        e.total += Number(r.total_points) || 0
        if (r.league) e.owners[r.league] = ownedBy.get(`${r.league}|${r.element}`) ?? null
      }
      // total was summed once per league, so halve it back
      for (const e of byElement.values()) e.total = Math.round(e.total / codes.length)
      const all = [...byElement.values()].sort((x, y) => y.total - x.total)
      players = {
        top: all.slice(0, TOP_N),
        exclusive: all.filter(e => codes.some(c => e.owners[c]) && codes.some(c => !e.owners[c]))
          .slice(0, TOP_N),
      }
    }

    // upcoming fixtures for the best available players
    const aheadWeeks = meta.gameweeks.filter(g => g > latest && g <= latest + LOOKAHEAD)
    const fixtureFor = (team, gw) => (fixtures ?? []).find(f => f.team_name === team && f.gameweek === gw)
    const available = (available_players ?? []).map(p => ({
      ...p,
      upcoming: aheadWeeks.map(g => fixtureFor(p.team_name, g) ?? null),
    }))

    return { codes, sizes, unequal, h2h, wins, totals, perDrafter, overlap,
             players, available, aheadWeeks, latest }
  }, [data, meta])

  if (error) return <div className="notice">Couldn&apos;t load league data: {String(error.message)}</div>
  if (loading || !v) return <Loading what="cross-league comparison" />

  const [a, b] = v.codes
  const nameOf = c => leagueName(meta, c)
  const ahead = v.perDrafter[a] > v.perDrafter[b] ? a : b

  return (
    <>
      <Section title="Cross-league" note="both leagues shown together">
        <StatRow>
          {v.codes.map(c => (
            <Stat key={c} label={nameOf(c)} value={v.perDrafter[c].toLocaleString()}
                  sub={`per drafter · ${v.totals[c].toLocaleString()} total`} />
          ))}
          <Stat label="Gameweeks won"
                value={v.codes.map(c => v.wins[c]).join(' – ')}
                sub={v.codes.map(c => c).join(' v ')} />
          <Stat label="Margin per drafter"
                value={`${nameOf(ahead)} +${Math.abs(round(v.perDrafter[a] - v.perDrafter[b]))}`} />
        </StatRow>

        {v.unequal && (
          <div className="notice" style={{ marginTop: 10 }}>
            <strong>Unequal leagues.</strong> {meta.label} ran{' '}
            {v.codes.map(c => `${v.sizes[c]} ${nameOf(c)}`).join(' vs ')}, so these comparisons use
            {' '}<strong>mean points per drafter</strong> — raw totals would hand every gameweek to
            the bigger league on squad count alone.
          </div>
        )}
      </Section>

      <Collapsible title="Match play" summary="weekly head to head" open>
        <SubHead note="Points per drafter each gameweek — the taller bar wins the week">
          Weekly comparison
        </SubHead>
        <div className="chart">
          <ResponsiveContainer>
            <BarChart data={v.h2h} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="gameweek" tickLine={false} axisLine={false}
                     interval="preserveStartEnd" minTickGap={18} />
              <YAxis tickLine={false} axisLine={false} width={44} />
              <Tooltip content={<ChartTip />} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              <Bar dataKey={a} fill="#00AEEF" name={nameOf(a)} />
              <Bar dataKey={b} fill="#FF6A13" name={nameOf(b)} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <SubHead note={`Positive favours ${nameOf(a)}`}>Points difference</SubHead>
        <div className="chart">
          <ResponsiveContainer>
            <BarChart data={v.h2h} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="gameweek" tickLine={false} axisLine={false}
                     interval="preserveStartEnd" minTickGap={18} />
              <YAxis tickLine={false} axisLine={false} width={44} />
              <Tooltip content={<ChartTip />} />
              <ReferenceLine y={0} stroke="var(--muted)" />
              <Bar dataKey="margin" name="Margin" fill="#A020F0" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Collapsible>

      <Collapsible title="Missed by a league"
                   count={v.players?.exclusive?.length ?? 0}
                   summary="highest scorers undrafted in one league">
        {!v.players ? (
          <Unavailable what="Cross-league ownership" season={meta.label}
            reason="That season's weekly points table has no per-league owner column." />
        ) : (
          <PlayerOwnershipTable players={v.players.exclusive} codes={v.codes}
                                nameOf={nameOf} meta={meta} />
        )}
      </Collapsible>

      <Collapsible title="Player overlap" summary={`shared squads at GW${v.latest}`}>
        <SubHead note="How many players each pair of drafters both hold">Overlap counts</SubHead>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{nameOf(b)} ↓ / {nameOf(a)} →</th>
                {v.overlap.cols.map(c => (
                  <th key={c.short_name} title={fullName(meta, c.short_name)}>{c.short_name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {v.overlap.rows.map(r => (
                <tr key={r.short_name}>
                  <td title={fullName(meta, r.short_name)}>{r.short_name}</td>
                  {v.overlap.cols.map(c => {
                    const n = v.overlap.count(r.short_name, c.short_name)
                    return (
                      <td key={c.short_name} className="num"
                          style={{ background: n ? `color-mix(in srgb, var(--accent) ${n * 12}%, transparent)` : undefined }}>
                        {n || ''}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>

      <Collapsible title="Top scorers" count={v.players?.top?.length ?? 0}
                   summary="and who owns them in each league">
        {!v.players ? (
          <Unavailable what="Ownership" season={meta.label} />
        ) : (
          <PlayerOwnershipTable players={v.players.top} codes={v.codes}
                                nameOf={nameOf} meta={meta} />
        )}
      </Collapsible>

      <Collapsible title="Best available"
                   count={v.available.length}
                   summary="undrafted form players and their fixtures">
        {v.available.length === 0 ? (
          <Unavailable what="Available players" season={meta.label}
            reason="Needs per-league ownership, which this season's data doesn't carry." />
        ) : (
          <>
            <SubHead note="Mean points over the last 6 gameweeks, top 5 per position">
              Undrafted form players
            </SubHead>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Player</th><th>League</th><th>Pos</th><th>Form</th>
                    {v.aheadWeeks.map(g => <th key={g}>GW{g}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {v.available.map(p => (
                    <tr key={`${p.league}-${p.element}`}>
                      <td>{p.web_name}<span className="muted small"> {p.team_name}</span></td>
                      <td>{p.league}</td>
                      <td>{p.position}</td>
                      <td className="num">{p.form_points}</td>
                      {p.upcoming.map((f, i) => (
                        <td key={i} style={{ background: difficultyColour(f?.opposition_difficulty) }}>
                          {f ? `${f.opposition}${f.home_away === 'H' ? '' : ' (a)'}` : '–'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {v.aheadWeeks.length === 0 && (
              <p className="small muted">Season complete — no upcoming fixtures to show.</p>
            )}
          </>
        )}
      </Collapsible>
    </>
  )
}

function difficultyColour(value) {
  if (value == null) return undefined
  const step = Math.max(1, Math.min(5, Math.round(Number(value))))
  const alpha = { 1: 8, 2: 16, 3: 28, 4: 44, 5: 62 }[step]
  return `color-mix(in srgb, ${step <= 2 ? 'var(--accent)' : '#d00000'} ${alpha}%, transparent)`
}

function PlayerOwnershipTable({ players, codes, nameOf, meta }) {
  if (!players?.length) return <p className="muted small">No players to show.</p>
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Player</th><th>Pos</th><th>Pts</th>
            {codes.map(c => <th key={c}>{nameOf(c)}</th>)}
          </tr>
        </thead>
        <tbody>
          {players.map(p => (
            <tr key={p.element}>
              <td>{p.web_name}{p.team_name ? <span className="muted small"> {p.team_name}</span> : null}</td>
              <td>{p.position}</td>
              <td className="num">{p.total}</td>
              {codes.map(c => (
                <td key={c} className={p.owners[c] ? '' : 'muted'}>
                  {p.owners[c] ? fullName(meta, p.owners[c]) : 'free'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
