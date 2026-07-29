import { useEffect, useMemo, useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { useTables, colourMap, can } from '../lib/data.js'
import { fullName, label, pct, round, signed } from '../lib/names.js'
import {
  LeagueToggle, Section, Loading, Unavailable, Stat, StatRow,
  Collapsible, SubHead, Segmented, ChartTip,
} from '../components/ui.jsx'

const BIN = 10

// Columns of the season summary table that can be charted over the season.
const SUMMARY_SERIES = [
  { value: 'points_scored', label: 'Points banked' },
  { value: 'draft_points', label: 'Draft points' },
  { value: 'points_gained_through_waivers', label: 'Waiver gains' },
  { value: 'net_points_lost_through_subs', label: 'Sub cost' },
  { value: 'points_gained_with_auto_subs', label: 'Auto-sub gains' },
  { value: 'optimal_points', label: 'Optimal points' },
  { value: 'bench_strength', label: 'Bench points' },
]

const SUMMARY_COLUMNS = [
  ['draft_points', 'Draft'],
  ['points_gained_through_waivers', 'Waivers'],
  ['squad_points', 'Squad'],
  ['bench_strength', 'Bench'],
  ['optimal_points', 'Optimal'],
  ['points_lost_choosing_starting_XI', 'XI choice'],
  ['points_before_auto_subs', 'Pre-subs'],
  ['points_gained_with_auto_subs', 'Auto-subs'],
  ['net_points_lost_through_subs', 'Net subs'],
  ['points_scored', 'Banked'],
]

export default function SeasonTrends({ season, meta, league, setLeague }) {
  const { data, loading, error } = useTables(season, [
    'league_table', 'weekly_summary', 'transfers', 'trades',
    'season_summary', 'season_summary_by_gameweek', 'formations',
    'draft_performance', 'player_usage', 'draft_share', 'draft_share_by_gameweek',
    'lorenz', 'distribution_position', 'distribution_team',
  ])
  const [mode, setMode] = useState('cumulative')
  const [seriesMetric, setSeriesMetric] = useState('points_scored')
  const [lorenzMode, setLorenzMode] = useState('pct')
  // 'all' shows the early picks across every drafter, which is the interesting
  // view en masse; picking a drafter shows their full 15.
  const [draftFilter, setDraftFilter] = useState('all')

  // A drafter selected in one league won't exist in another (or in another
  // season, after promotion and relegation), which would leave an empty table.
  useEffect(() => { setDraftFilter('all') }, [season, league])
  const colours = useMemo(() => colourMap(meta, league), [meta, league])

  const v = useMemo(() => {
    if (!data) return null
    const inLeague = rows => (rows ?? []).filter(r => r.league === league)
    const rows = inLeague(data.league_table).sort((a, b) => a.rank - b.rank)
    const gws = meta.gameweeks

    const points = gws.map((g, i) => {
      const point = { gameweek: g }
      for (const r of rows) {
        point[r.short_name] = mode === 'cumulative' ? r.cumulative_by_gameweek?.[i]
          : mode === 'weekly' ? r.points_by_gameweek?.[i]
          : round((r.cumulative_by_gameweek?.[i] ?? 0) / (i + 1))
      }
      return point
    })

    // score histogram
    const scores = rows.flatMap(r => (r.points_by_gameweek ?? []).map(p => ({ s: r.short_name, p })))
    const lo = Math.floor(Math.min(...scores.map(x => x.p)) / BIN) * BIN
    const hi = Math.ceil((Math.max(...scores.map(x => x.p)) + 1) / BIN) * BIN
    const bins = []
    for (let b = lo; b < hi; b += BIN) {
      const row = { band: `${b}–${b + BIN - 1}` }
      for (const r of rows) row[r.short_name] = scores.filter(x => x.s === r.short_name && x.p >= b && x.p < b + BIN).length
      bins.push(row)
    }

    // cumulative sub cost per gameweek, from weekly_summary
    const summary = inLeague(data.weekly_summary)
    const subCost = gws.map(g => {
      const row = { gameweek: g }
      for (const r of rows) {
        const upTo = summary.filter(x => x.short_name === r.short_name && x.gameweek <= g)
        const optimal = upTo.reduce((s, x) => s + (Number(x.optimal_points) || 0), 0)
        const scored = upTo.reduce((s, x) => s + (Number(x.points_scored) || 0), 0)
        row[r.short_name] = round(Math.max(0, optimal - scored))
      }
      return row
    })

    // transfer + trade activity by type
    const types = ['waiver ok', 'free agent ok', 'waiver failed', 'trade']
    const activity = rows.map(r => {
      const mine = inLeague(data.transfers).filter(t => t.short_name === r.short_name)
      const myTrades = (data.trades ?? []).filter(t =>
        t.league === league && (t.offered_by === r.short_name || t.received_by === r.short_name))
      return {
        short_name: r.short_name,
        'waiver ok': mine.filter(t => t.kind === 'waiver' && t.result === 'successful').length,
        'free agent ok': mine.filter(t => t.kind === 'free agent' && t.result === 'successful').length,
        'waiver failed': mine.filter(t => t.result && t.result !== 'successful').length,
        trade: myTrades.length,
      }
    })
    const activityByWeek = gws.map(g => {
      const row = { gameweek: g }
      for (const r of rows) {
        row[r.short_name] = inLeague(data.transfers)
          .filter(t => t.short_name === r.short_name && t.gameweek <= g && t.result === 'successful').length
          + (data.trades ?? []).filter(t => t.league === league && t.gameweek <= g
              && (t.offered_by === r.short_name || t.received_by === r.short_name)).length
      }
      return row
    })

    const summaryRows = inLeague(data.season_summary)
    const series = gws.map(g => {
      const row = { gameweek: g }
      for (const r of rows) {
        const hit = inLeague(data.season_summary_by_gameweek)
          .find(x => x.short_name === r.short_name && x.gameweek === g)
        row[r.short_name] = hit ? hit[seriesMetric] : null
      }
      return row
    })

    // Lorenz curves. Squad sizes differ (60-81 players), so for the share view the
    // curves are interpolated onto a common grid to give Recharts one aligned
    // dataset; for the count view x is the player number and shorter squads simply
    // stop early.
    const lorenzRows = inLeague(data.lorenz)
    const byDrafter = new Map()
    for (const r of lorenzRows) {
      if (!byDrafter.has(r.short_name)) byDrafter.set(r.short_name, [])
      byDrafter.get(r.short_name).push(r)
    }
    for (const list of byDrafter.values()) list.sort((a, b) => a.player_index - b.player_index)

    const interpolate = (list, x, xKey) => {
      if (!list.length) return null
      if (x <= list[0][xKey]) return list[0].points_pct
      const last = list[list.length - 1]
      if (x >= last[xKey]) return last.points_pct
      for (let i = 1; i < list.length; i++) {
        const prev = list[i - 1], next = list[i]
        if (x <= next[xKey]) {
          const span = next[xKey] - prev[xKey]
          if (span === 0) return next.points_pct
          const t = (x - prev[xKey]) / span
          return prev.points_pct + t * (next.points_pct - prev.points_pct)
        }
      }
      return last.points_pct
    }

    const maxSquad = Math.max(0, ...[...byDrafter.values()].map(l => l.length - 1))
    const lorenz = lorenzMode === 'pct'
      ? Array.from({ length: 51 }, (_, i) => {
          const x = i / 50
          const row = { x: Math.round(x * 100), equal: Math.round(x * 100) }
          for (const [short, list] of byDrafter) {
            const y = interpolate(list, x, 'players_pct')
            row[short] = y == null ? null : round(y * 100)
          }
          return row
        })
      : Array.from({ length: maxSquad + 1 }, (_, i) => {
          const row = { x: i }
          for (const [short, list] of byDrafter) {
            const hit = list.find(r => r.player_index === i)
            row[short] = hit ? round(hit.points_pct * 100) : null
          }
          return row
        })

    const usage = inLeague(data.player_usage)
    const share = inLeague(data.draft_share)

    // share of banked points coming from own picks, cumulative per gameweek
    const shareRows = inLeague(data.draft_share_by_gameweek)
    const shareSeries = gws.map(g => {
      const row = { gameweek: g }
      for (const r of rows) {
        const hit = shareRows.find(x => x.short_name === r.short_name && x.gameweek === g)
        row[r.short_name] = hit?.pct_from_draft == null ? null : round(hit.pct_from_draft * 100)
      }
      return row
    })
    const forms = inLeague(data.formations)

    // Draft round from the overall pick number and the league size — a snake
    // draft of N drafters means every N picks is one round.
    const leagueSize = meta.leagues.find(l => l.code === league)?.size || rows.length || 6
    const perf = inLeague(data.draft_performance)
      .map(p => ({ ...p, round: Math.floor(((p.draft_index ?? 1) - 1) / leagueSize) + 1 }))
      .sort((a, b) => a.draft_index - b.draft_index)

    const EARLY_ROUNDS = 5
    const squadRounds = Math.max(0, ...perf.map(p => p.round))
    const earlyRounds = Math.min(EARLY_ROUNDS, squadRounds)
    const draftRows = draftFilter === 'all'
      ? perf.filter(p => p.round <= earlyRounds)
      : perf.filter(p => p.short_name === draftFilter)

    const leader = rows[0]
    const totalLost = summaryRows.filter(r => !r.is_average)
      .reduce((s, r) => s + Math.abs(Number(r.net_points_lost_through_subs) || 0), 0)
    const bestPick = [...perf].sort((a, b) =>
      (b.points_realised_by_drafter ?? 0) - (a.points_realised_by_drafter ?? 0))[0]

    return { rows, gws, points, bins, subCost, activity, activityByWeek, types,
             summaryRows, series, usage, share, perf, forms, leader, totalLost, bestPick,
             lorenz, maxSquad, draftRows, earlyRounds, squadRounds, shareSeries }
  }, [data, league, meta, mode, seriesMetric, lorenzMode, draftFilter])

  if (error) return <div className="notice">Couldn&apos;t load season data: {String(error.message)}</div>
  if (loading || !v) return <Loading what="season trends" />

  const modeLabel = { cumulative: 'Cumulative points', weekly: 'Points per gameweek', average: 'Rolling average' }[mode]

  return (
    <>
      <Section title="Season Trends"
               aside={<LeagueToggle meta={meta} league={league} setLeague={setLeague} />}>
        <StatRow>
          <Stat label="Leader" value={v.leader ? v.leader.total : '–'}
                sub={v.leader ? fullName(meta, v.leader.short_name) : ''} />
          <Stat label="Gameweeks played" value={meta.current_gameweek}
                sub={meta.complete ? 'season complete' : 'in progress'} />
          {can(meta, 'optimal_points') && (
            <Stat label="Points lost to subs" value={Math.round(v.totalLost)} sub="league-wide, all season" />
          )}
          {v.bestPick && (
            <Stat label="Best draft pick" value={v.bestPick.points_realised_by_drafter}
                  sub={`${v.bestPick.web_name} · ${fullName(meta, v.bestPick.short_name)}`} />
          )}
        </StatRow>
      </Section>

      <Collapsible title="Points" summary="cumulative, per gameweek, distribution" open>
        <Segmented ariaLabel="Points mode" value={mode} onChange={setMode}
          options={[{ value: 'cumulative', label: 'Total' },
                    { value: 'weekly', label: 'Per GW' },
                    { value: 'average', label: 'Average' }]} />
        <SubHead>{modeLabel}</SubHead>
        <DrafterLines data={v.points} rows={v.rows} colours={colours} />

        <SubHead note={`${BIN}-point bands · count of gameweeks`}>Distribution of gameweek scores</SubHead>
        <DrafterBars data={v.bins} rows={v.rows} colours={colours} xKey="band" stacked />
      </Collapsible>

      <Collapsible title="Substitutions"
                   summary={`${Math.round(v.totalLost)} pts lost league-wide`}>
        {!can(meta, 'optimal_points')
          ? <Unavailable what="Substitution analysis" season={meta.label} />
          : (
            <>
              <SubHead note="Cumulative gap between the optimal XI and what was banked">
                Points lost to sub choices
              </SubHead>
              <DrafterLines data={v.subCost} rows={v.rows} colours={colours} />
            </>
          )}
      </Collapsible>

      <Collapsible title="Transfers & trades"
                   count={v.activity.reduce((s, a) => s + a['waiver ok'] + a['free agent ok'] + a.trade, 0)}
                   summary="activity by drafter and type">
        <SubHead note="Successful waivers and free agents, failed attempts, and trades">
          Moves by type
        </SubHead>
        <div className="chart">
          <ResponsiveContainer>
            <BarChart data={v.activity} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="short_name" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} width={40} allowDecimals={false} />
              <Tooltip content={<ChartTip labelPrefix="" />} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              <Bar dataKey="waiver ok" stackId="a" fill="#2b9348" />
              <Bar dataKey="free agent ok" stackId="a" fill="#00AEEF" />
              <Bar dataKey="trade" stackId="a" fill="#A020F0" />
              <Bar dataKey="waiver failed" stackId="b" fill="#d00000" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <SubHead note="Running count of accepted moves, including trades">Activity over the season</SubHead>
        <DrafterLines data={v.activityByWeek} rows={v.rows} colours={colours} />
      </Collapsible>

      <Collapsible title="Draft picks" count={v.perf.length} summary="who banked the points">
        <SubHead note="Realised by the drafter who picked them, by a later owner, or by nobody">
          Value of each pick
        </SubHead>

        <div className="chips" style={{ marginBottom: 8 }}>
          <button className="chip" aria-pressed={draftFilter === 'all'}
                  onClick={() => setDraftFilter('all')}>
            Early picks
          </button>
          {v.rows.map(r => (
            <button key={r.short_name} className="chip"
                    aria-pressed={draftFilter === r.short_name}
                    title={fullName(meta, r.short_name)}
                    onClick={() => setDraftFilter(r.short_name)}>
              {r.short_name}
            </button>
          ))}
        </div>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>#</th><th>Rd</th><th>Player</th><th>Drafter</th><th>Total</th>
                <th>To drafter</th><th>To others</th><th>Unrealised</th><th>Kept</th>
              </tr>
            </thead>
            <tbody>
              {v.draftRows.map(p => (
                <tr key={`${p.short_name}-${p.element}`}>
                  <td className="num">{p.draft_index}</td>
                  <td className="num">{p.round}</td>
                  <td>{p.web_name}<span className="muted small"> {p.position}</span></td>
                  <td>{label(p.short_name)}</td>
                  <td className="num">{p.total_points}</td>
                  <td className="num">{p.points_realised_by_drafter}</td>
                  <td className="num">{p.points_realised_by_other || ''}</td>
                  <td className="num">{p.points_unrealised || ''}</td>
                  <td>{p.still_owned ? '✓' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          {draftFilter === 'all'
            ? `Rounds 1–${v.earlyRounds} across every drafter — pick a drafter above for their full ${v.squadRounds} picks.`
            : `All ${v.draftRows.length} picks by ${fullName(meta, draftFilter)}.`}
        </p>
      </Collapsible>

      <Collapsible title="Players" summary="squad churn and scoring concentration">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Drafter</th><th>Used</th><th>Started</th><th>Scorers</th>
                <th>Gini</th><th>Top scorer</th><th>Pts</th><th>Share</th>
              </tr>
            </thead>
            <tbody>
              {[...v.usage].sort((a, b) => b.unique_players_used - a.unique_players_used).map(u => (
                <tr key={u.short_name}>
                  <td>{fullName(meta, u.short_name)}</td>
                  <td className="num">{u.unique_players_used}</td>
                  <td className="num">{u.unique_players_started}</td>
                  <td className="num">{u.scoring_players}</td>
                  <td className="num">{round(u.gini, 3)}</td>
                  <td>{u.top_player}</td>
                  <td className="num">{u.top_player_points}</td>
                  <td className="num">{pct(u.top_player_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          <strong>Gini</strong> measures how unevenly banked points were spread across every player a
          drafter held — non-scorers and never-started included. 0 would be all squad members
          contributing equally; closer to 1 means a few players carried the team.
        </p>

        <SubHead note="Squad ordered worst to best. The straight line is perfect equality — the further a curve sags below it, the more that drafter leaned on a few players.">
          Scoring concentration
        </SubHead>
        <Segmented ariaLabel="Lorenz x-axis" value={lorenzMode} onChange={setLorenzMode}
          options={[{ value: 'pct', label: '% of squad' },
                    { value: 'count', label: 'Player count' }]} />
        <div className="chart">
          <ResponsiveContainer>
            <LineChart data={v.lorenz} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="x" tickLine={false} axisLine={false}
                     type="number" domain={[0, lorenzMode === 'pct' ? 100 : v.maxSquad]}
                     tickFormatter={x => (lorenzMode === 'pct' ? `${x}%` : x)}
                     interval="preserveStartEnd" minTickGap={24} />
              <YAxis tickLine={false} axisLine={false} width={44} domain={[0, 100]}
                     tickFormatter={y => `${y}%`} />
              <Tooltip content={<ChartTip labelPrefix={lorenzMode === 'pct' ? '' : 'Player '}
                                          unit="%" />} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              {lorenzMode === 'pct' && (
                <Line dataKey="equal" name="Equal" stroke="var(--muted)" strokeWidth={1}
                      strokeDasharray="4 4" dot={false} activeDot={false} legendType="plainline" />
              )}
              {v.rows.map(r => (
                <Line key={r.short_name} type="monotone" dataKey={r.short_name}
                      stroke={colours[r.short_name]} strokeWidth={2} dot={false}
                      activeDot={{ r: 3 }} connectNulls={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Collapsible>

      <Collapsible title="Season summary" summary="the full points breakdown">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Drafter</th>
                {SUMMARY_COLUMNS.map(([key, head]) => <th key={key}>{head}</th>)}
              </tr>
            </thead>
            <tbody>
              {v.summaryRows.map(r => (
                <tr key={r.short_name} style={r.is_average ? { fontStyle: 'italic', opacity: 0.75 } : undefined}>
                  <td>{r.is_average ? 'League average' : fullName(meta, r.short_name)}</td>
                  {SUMMARY_COLUMNS.map(([key]) => (
                    <td key={key} className="num">{round(r[key], 0)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <SubHead note="Pick a column to see how it moved over the season">Over time</SubHead>
        <Segmented ariaLabel="Metric" value={seriesMetric} onChange={setSeriesMetric}
                   options={SUMMARY_SERIES} />
        <DrafterLines data={v.series} rows={v.rows} colours={colours} />
      </Collapsible>

      <Collapsible title="Distributions" summary="by position, club, formation and draft">
        <SubHead note="Share of banked points by position">Points by position</SubHead>
        <DistributionTable rows={v.rows} data={data.distribution_position} league={league} meta={meta} field="pct_points" format={pct} />

        <SubHead note="Average points per appearance by position">Average by position</SubHead>
        <DistributionTable rows={v.rows} data={data.distribution_position} league={league} meta={meta} field="avg_points" format={x => round(x, 2)} />

        <SubHead note="Share of banked points by Premier League club">Points by club</SubHead>
        {can(meta, 'team_names')
          ? <DistributionTable rows={v.rows} data={data.distribution_team} league={league} meta={meta} field="pct_points" format={pct} limit={12} />
          : <Unavailable what="Club breakdown" season={meta.label} />}

        <SubHead note="How often each shape was started, and the mean optimal shape">
          Chosen formations
        </SubHead>
        <FormationTable rows={v.rows} formations={v.forms} meta={meta} />

        <SubHead note="Cumulative share of banked points coming from a drafter's own picks — it can only fall as squads churn">
          Points from the draft, over time
        </SubHead>
        <div className="chart">
          <ResponsiveContainer>
            <LineChart data={v.shareSeries} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="gameweek" tickLine={false} axisLine={false}
                     interval="preserveStartEnd" minTickGap={18} />
              <YAxis tickLine={false} axisLine={false} width={44} domain={[0, 100]}
                     tickFormatter={y => `${y}%`} />
              <Tooltip content={<ChartTip unit="%" />} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
              {v.rows.map(r => (
                <Line key={r.short_name} type="monotone" dataKey={r.short_name}
                      stroke={colours[r.short_name]} strokeWidth={2} dot={false}
                      activeDot={{ r: 3 }} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <SubHead note="Season total">Points from the draft</SubHead>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Drafter</th><th>From draft</th><th>Total</th><th>Share</th></tr></thead>
            <tbody>
              {[...v.share].sort((a, b) => b.pct_from_draft - a.pct_from_draft).map(s => (
                <tr key={s.short_name}>
                  <td>{fullName(meta, s.short_name)}</td>
                  <td className="num">{s.draft_points}</td>
                  <td className="num">{s.points_scored}</td>
                  <td className="num">{pct(s.pct_from_draft)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>
    </>
  )
}

/* ---------- shared chart wrappers: initials on axes, never full names ---------- */

function DrafterLines({ data, rows, colours }) {
  return (
    <div className="chart">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="gameweek" tickLine={false} axisLine={false}
                 interval="preserveStartEnd" minTickGap={18} />
          <YAxis tickLine={false} axisLine={false} width={44} domain={['auto', 'auto']} />
          <Tooltip content={<ChartTip />} />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
          {rows.map(r => (
            <Line key={r.short_name} type="monotone" dataKey={r.short_name}
                  stroke={colours[r.short_name]} strokeWidth={2} dot={false} activeDot={{ r: 3 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function DrafterBars({ data, rows, colours, xKey, stacked }) {
  return (
    <div className="chart">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey={xKey} tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} width={44} allowDecimals={false} />
          <Tooltip content={<ChartTip labelPrefix="" />} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} />
          {rows.map(r => (
            <Bar key={r.short_name} dataKey={r.short_name}
                 stackId={stacked ? 'a' : undefined} fill={colours[r.short_name]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Buckets down the side, drafters across the top — matches the old heatmaps. */
function DistributionTable({ rows, data, league, meta, field, format, limit }) {
  const mine = (data ?? []).filter(d => d.league === league)
  const totals = {}
  for (const d of mine) totals[d.bucket] = (totals[d.bucket] ?? 0) + (d.points_scored ?? 0)
  let buckets = Object.keys(totals).sort((a, b) => totals[b] - totals[a])
  if (limit) buckets = buckets.slice(0, limit)
  if (!buckets.length) return <p className="muted small">No data.</p>

  const cell = (bucket, short) => mine.find(d => d.bucket === bucket && d.short_name === short)?.[field]
  const max = Math.max(...mine.filter(d => buckets.includes(d.bucket)).map(d => d[field] ?? 0), 0.0001)

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>{buckets.length && mine[0]?.cut === 'position' ? 'Position' : 'Club'}</th>
            {rows.map(r => <th key={r.short_name} title={fullName(meta, r.short_name)}>{r.short_name}</th>)}
          </tr>
        </thead>
        <tbody>
          {buckets.map(b => (
            <tr key={b}>
              <td>{b}</td>
              {rows.map(r => {
                const value = cell(b, r.short_name)
                const strength = value == null ? 0 : Math.round((value / max) * 55)
                return (
                  <td key={r.short_name} className="num"
                      style={{ background: strength ? `color-mix(in srgb, var(--accent) ${strength}%, transparent)` : undefined }}>
                    {value == null ? '' : format(value)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FormationTable({ rows, formations, meta }) {
  const shapes = [...new Set((formations ?? []).map(f => f.formation))].sort()
  if (!shapes.length) return <p className="muted small">No formation data.</p>
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Drafter</th>
            {shapes.map(s => <th key={s}>{s}</th>)}
            <th>Mean optimal</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const mine = (formations ?? []).filter(f => f.short_name === r.short_name)
            return (
              <tr key={r.short_name}>
                <td>{fullName(meta, r.short_name)}</td>
                {shapes.map(s => (
                  <td key={s} className="num">{mine.find(f => f.formation === s)?.count || ''}</td>
                ))}
                <td className="num">{mine[0]?.optimal_formation ?? '–'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
