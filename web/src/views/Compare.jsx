import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ReferenceLine,
} from 'recharts'
import { useTables, can } from '../lib/data.js'
import { navigate } from '../lib/router.js'
import { fullName, label, leagueName, round } from '../lib/names.js'
import {
  Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead, ChartTip,
} from '../components/ui.jsx'

const TOP_N = 20
const LOOKAHEAD = 6
// The old report cut the "not drafted" table at the top 18 scorers of the week.
const NOT_DRAFTED_RANK_CUTOFF = 18
const TOP_PAIRS = 5

/**
 * Cross-league view — the one place that deliberately shows both leagues together
 * rather than using the Prem/Conf toggle.
 *
 * Several sections are inherently per-gameweek (who owned whom, squad overlap,
 * fixtures), so the tab carries its own gameweek selector, deep-linked as
 * #/<season>/compare/<gw>.
 */
export default function Compare({ season, meta, route }) {
  // Only reachable by deep link — the tab is hidden on a single-league site. Every
  // section below measures one league against another, so there is no partial
  // version of this view to fall back to.
  if ((meta?.leagues?.length ?? 0) < 2) {
    return (
      <Section title="Cross-league">
        <Unavailable
          what="A cross-league comparison"
          season={season}
          reason={`${meta?.leagues?.[0]?.name ?? 'This league'} is the only league here, `
                  + 'so there is nothing to compare it against.'}
        />
      </Section>
    )
  }

  const gw = Number(route?.param) || meta.current_gameweek
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

    // --- squads at the SELECTED gameweek ---------------------------------
    const squads = new Map()
    const ownedBy = new Map()
    for (const r of weekly_summary) {
      if (r.gameweek !== gw) continue
      const key = `${r.league}|${r.short_name}`
      if (!squads.has(key)) squads.set(key, new Set())
      squads.get(key).add(r.element)
      ownedBy.set(`${r.league}|${r.element}`, r.short_name)
    }
    const rowsOf = c => league_table.filter(r => r.league === c).sort((x, y) => x.rank - y.rank)

    const countShared = (rb, ca) => {
      const sb = squads.get(`${b}|${rb}`) ?? new Set()
      const sa = squads.get(`${a}|${ca}`) ?? new Set()
      let n = 0
      for (const el of sb) if (sa.has(el)) n++
      return n
    }
    const overlap = { rows: rowsOf(b), cols: rowsOf(a), count: countShared }

    // most-alike pairs this week
    const pairs = []
    for (const rb of overlap.rows) {
      for (const ca of overlap.cols) {
        pairs.push({ b: rb.short_name, a: ca.short_name, n: countShared(rb.short_name, ca.short_name) })
      }
    }
    pairs.sort((x, y) => y.n - x.n)
    const topPairs = pairs.filter(p => p.n > 0).slice(0, TOP_PAIRS)
    const highlighted = new Set(topPairs.map(p => `${p.b}|${p.a}`))

    // --- top scorers of the selected week, undrafted in at least one league ---
    // Per gameweek, as the old report had it: the week's top scorers with who
    // owned them. A season-total version wrongly flags stars who were merely
    // traded away late (Haaland at GW38).
    let notDrafted = null
    let weekTop = null
    if (can(meta, 'ownership_by_league')) {
      const byElement = new Map()
      for (const r of weekly_points) {
        if (r.gameweek !== gw || r.element == null) continue
        if (!byElement.has(r.element)) {
          byElement.set(r.element, {
            element: r.element, web_name: r.web_name, position: r.position,
            team_name: r.team_name, points: Number(r.total_points) || 0,
            rank: r.rank_in_week, owners: {},
          })
        }
        const e = byElement.get(r.element)
        if (r.rank_in_week != null) e.rank = r.rank_in_week
        if (r.league) e.owners[r.league] = label(r.owner) === 'Not Drafted' ? null : label(r.owner)
      }
      const all = [...byElement.values()].sort(
        (x, y) => (x.rank ?? 999) - (y.rank ?? 999) || y.points - x.points)
      notDrafted = all
        .filter(e => e.rank != null && e.rank <= NOT_DRAFTED_RANK_CUTOFF)
        .filter(e => codes.some(c => !e.owners[c]))
      weekTop = all.slice(0, TOP_N)
    }

    // --- fixtures: results for the week, plus the look-ahead from here ----
    const all = fixtures ?? []
    const results = all.filter(f => f.gameweek === gw && f.home_away === 'H')
      .sort((x, y) => String(x.kickoff_time ?? '').localeCompare(String(y.kickoff_time ?? '')))
    // The look-ahead comes from the FIXTURE table, not from meta.gameweeks. meta.gameweeks is
    // the list of gameweeks that have been PLAYED — [1] in August — so filtering it for weeks
    // after the current one is always empty and the whole "next 6 gameweeks" section, plus the
    // upcoming-fixture columns on the free agents, silently rendered nothing all season.
    // Fixtures are published for all 38 weeks up front, which is exactly what a look-ahead needs.
    const scheduled = new Set(all.map(f => f.gameweek))
    const aheadWeeks = Array.from({ length: LOOKAHEAD }, (_, i) => gw + 1 + i)
      .filter(g => scheduled.has(g))
    const teams = [...new Set(all.map(f => f.team_name))].filter(Boolean).sort()
    const lookahead = teams.map(team => ({
      team,
      weeks: aheadWeeks.map(g => all.find(f => f.team_name === team && f.gameweek === g) ?? null),
    })).filter(r => r.weeks.some(Boolean))

    // "Available" is point-in-time: filter to the selected gameweek, or these are
    // the latest week's free agents shown under an earlier one.
    const fixtureFor = (team, g) => all.find(f => f.team_name === team && f.gameweek === g)
    const available = (available_players ?? [])
      .filter(p => p.gameweek == null || p.gameweek === gw)
      .map(p => ({ ...p, upcoming: aheadWeeks.map(g => fixtureFor(p.team_name, g) ?? null) }))

    return { codes, sizes, unequal, h2h, wins, totals, perDrafter, overlap, topPairs,
             highlighted, notDrafted, weekTop, results, lookahead, aheadWeeks, available }
  }, [data, meta, gw])

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
          <Stat label="Gameweeks won" value={v.codes.map(c => v.wins[c]).join(' – ')}
                sub={v.codes.join(' v ')} />
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

      <Section title={`Gameweek ${gw}`} note="ownership, overlap and fixtures below are for this week">
        <div className="chips">
          {meta.gameweeks.map(g => (
            <button key={g} className="chip" aria-pressed={g === gw}
                    onClick={() => navigate({ season, view: 'compare', param: g })}>
              {g}
            </button>
          ))}
        </div>
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
                   count={v.notDrafted?.length ?? 0}
                   summary={`top ${NOT_DRAFTED_RANK_CUTOFF} in GW${gw}, free somewhere`}>
        {!v.notDrafted ? (
          <Unavailable what="Cross-league ownership" season={meta.label}
            reason="That season's weekly points table has no per-league owner column." />
        ) : v.notDrafted.length === 0 ? (
          <p className="muted small">
            Every top-{NOT_DRAFTED_RANK_CUTOFF} scorer in gameweek {gw} was owned in both leagues.
          </p>
        ) : (
          <>
            <SubHead note={`Ranked by gameweek ${gw} score. A league showing "free" had nobody holding them that week.`}>
              Top scorers not drafted everywhere
            </SubHead>
            <WeekOwnershipTable players={v.notDrafted} codes={v.codes} nameOf={nameOf} meta={meta} />
          </>
        )}
      </Collapsible>

      <Collapsible title="Player overlap" summary={`shared squads in GW${gw}`}>
        {v.topPairs.length > 0 && (
          <>
            <SubHead note={`Most alike squads in gameweek ${gw}`}>Closest pairs</SubHead>
            <ul className="pair-list">
              {v.topPairs.map(p => (
                <li key={`${p.b}|${p.a}`}>
                  <strong>{p.n}</strong> shared —{' '}
                  {fullName(meta, p.a)} <span className="muted">&amp;</span> {fullName(meta, p.b)}
                </li>
              ))}
            </ul>
          </>
        )}
        <SubHead note="Highlighted cells are the closest pairs above">Overlap counts</SubHead>
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
                    const top = v.highlighted.has(`${r.short_name}|${c.short_name}`)
                    return (
                      <td key={c.short_name} className={`num${top ? ' pair-top' : ''}`}
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

      <Collapsible title="Top scorers" count={v.weekTop?.length ?? 0}
                   summary={`GW${gw} best, and who owned them`}>
        {!v.weekTop ? (
          <Unavailable what="Ownership" season={meta.label} />
        ) : (
          <WeekOwnershipTable players={v.weekTop} codes={v.codes} nameOf={nameOf} meta={meta} />
        )}
      </Collapsible>

      <Collapsible title="Best available"
                   count={v.available.length}
                   summary={`free in GW${gw}, by recent form`}>
        {v.available.length === 0 ? (
          <Unavailable what="Available players" season={meta.label}
            reason="Needs per-league ownership, which this season's data doesn't carry." />
        ) : (
          <>
            <SubHead note={`Unowned as at gameweek ${gw}, ranked by mean points over the previous 6 gameweeks — top 5 per position`}>
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

      <Collapsible title="Fixtures"
                   summary={can(meta, 'fixture_lookahead')
                     ? `GW${gw} results · next ${LOOKAHEAD} gameweeks`
                     : 'not available for this season'}>
        {!can(meta, 'fixture_lookahead') ? (
          <Unavailable what="Fixtures" season={meta.label} />
        ) : (
          <>
            <SubHead note={`Gameweek ${gw}`}>Results</SubHead>
            {v.results.length === 0 ? (
              <p className="muted small">No fixtures found for gameweek {gw}.</p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Home</th><th>Score</th><th>Away</th></tr></thead>
                  <tbody>
                    {v.results.map((f, i) => (
                      <tr key={i}>
                        <td>{f.team_name}</td>
                        <td className="num">{f.team_score ?? '–'} – {f.opposition_score ?? '–'}</td>
                        <td>{f.opposition}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <SubHead note="Shading is fixture difficulty — darker is harder">
              Next {LOOKAHEAD} gameweeks
            </SubHead>
            {v.aheadWeeks.length === 0 ? (
              <p className="muted small">Season complete — nothing ahead of gameweek {gw}.</p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Team</th>
                      {v.aheadWeeks.map(g => <th key={g}>GW{g}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {v.lookahead.map(r => (
                      <tr key={r.team}>
                        <td>{r.team}</td>
                        {r.weeks.map((f, i) => (
                          <td key={i} style={{ background: difficultyColour(f?.opposition_difficulty) }}>
                            {f ? `${f.opposition}${f.home_away === 'H' ? '' : ' (a)'}` : '–'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Collapsible>
    </>
  )
}

function difficultyColour(value) {
  if (value == null) return undefined
  // FPL rates 1 (easiest) to 5 (hardest)
  const step = Math.max(1, Math.min(5, Math.round(Number(value))))
  const alpha = { 1: 8, 2: 16, 3: 28, 4: 44, 5: 62 }[step]
  return `color-mix(in srgb, ${step <= 2 ? 'var(--accent)' : '#d00000'} ${alpha}%, transparent)`
}

/** One week's scorers with the owner in each league, or "free". */
function WeekOwnershipTable({ players, codes, nameOf, meta }) {
  if (!players?.length) return <p className="muted small">No players to show.</p>
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Rank</th><th>Player</th><th>Pos</th><th>Pts</th>
            {codes.map(c => <th key={c}>{nameOf(c)}</th>)}
          </tr>
        </thead>
        <tbody>
          {players.map(p => (
            <tr key={p.element}>
              <td className="num">{p.rank ?? '–'}</td>
              <td>{p.web_name}{p.team_name ? <span className="muted small"> {p.team_name}</span> : null}</td>
              <td>{p.position}</td>
              <td className="num">{p.points}</td>
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
