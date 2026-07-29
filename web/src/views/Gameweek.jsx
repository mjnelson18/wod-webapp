import { useMemo } from 'react'
import { useTables, can } from '../lib/data.js'
import { navigate } from '../lib/router.js'
import { fullName, label, round, signed, rankMove } from '../lib/names.js'
import {
  LeagueToggle, Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead,
} from '../components/ui.jsx'
import SquadGrid from '../components/SquadGrid.jsx'

const STARTERS = 11

export default function Gameweek({ season, meta, league, setLeague, route }) {
  const gw = Number(route.param) || meta.current_gameweek
  const { data, loading, error } = useTables(season, [
    'weekly_summary', 'league_table', 'transfers', 'trades',
  ])

  const view = useMemo(() => {
    if (!data) return null
    const { weekly_summary, league_table, transfers, trades } = data

    const table = league_table.filter(r => r.league === league).sort((a, b) => a.rank - b.rank)
    const rows = weekly_summary.filter(r => r.league === league && r.gameweek === gw)
    const gwIndex = meta.gameweeks.indexOf(gw)

    // per-drafter totals for this gameweek
    const drafters = table.map(t => {
      const squad = rows.filter(r => r.short_name === t.short_name)
      const scored = squad.reduce((s, r) => s + (Number(r.points_scored) || 0), 0)
      const optimal = squad.reduce((s, r) => s + (Number(r.optimal_points) || 0), 0)
      const beforeSubs = squad.reduce((s, r) => s + (Number(r.points_before_auto_subs) || 0), 0)
      return {
        ...t,
        squad,
        scored,
        optimal,
        beforeSubs,
        lostToSubs: Math.max(0, optimal - scored),
        autoSubGain: scored - beforeSubs,
        cumulative: t.cumulative_by_gameweek?.[gwIndex] ?? null,
      }
    })

    const best = drafters.reduce((a, b) => (b.scored > (a?.scored ?? -1) ? b : a), null)
    const worst = drafters.reduce((a, b) => (b.scored < (a?.scored ?? 1e9) ? b : a), null)
    const leagueTotal = drafters.reduce((s, d) => s + d.scored, 0)
    const leagueAvg = drafters.length ? leagueTotal / drafters.length : 0
    const totalLost = drafters.reduce((s, d) => s + d.lostToSubs, 0)

    // subs detail: who was subbed on/off, and what it cost or gained
    const subs = []
    for (const d of drafters) {
      for (const r of d.squad) {
        const benched = (r.place ?? 99) > STARTERS
        const on = r.originally_starting === 0 && !benched
        const off = r.originally_starting === 1 && benched
        if (!on && !off) continue
        subs.push({
          short_name: d.short_name, web_name: r.web_name, position: r.position,
          team_name: r.team_name, points: Number(r.total_points) || 0,
          kind: on ? 'on' : 'off',
        })
      }
    }

    // accepted moves only, this gameweek — successful transfers plus trades
    const moves = []
    for (const t of transfers) {
      if (t.league !== league || t.gameweek !== gw) continue
      if (t.result !== 'successful') continue
      moves.push({
        type: t.kind === 'waiver' ? 'Waiver' : 'Free agent',
        who: t.short_name, inName: t.player_in, outName: t.player_out,
        inPoints: t.player_in_points, outPoints: t.player_out_points,
        net: t.net_points, counterparty: null,
      })
    }
    for (const t of trades ?? []) {
      if (t.league !== league || t.gameweek !== gw) continue
      moves.push({
        type: 'Trade', who: t.offered_by, inName: t.player_in, outName: t.player_out,
        inPoints: t.player_in_points, outPoints: t.player_out_points,
        net: t.net_points, counterparty: t.received_by,
      })
    }
    moves.sort((a, b) => Math.abs(b.net ?? 0) - Math.abs(a.net ?? 0))

    return { table, drafters, best, worst, leagueTotal, leagueAvg, totalLost, subs, moves }
  }, [data, league, gw, meta.gameweeks])

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
            <button key={g} className="chip" aria-pressed={g === gw}
                    onClick={() => navigate({ season, view: 'gw', param: g })}>
              {g}
            </button>
          ))}
        </div>

        <StatRow>
          <Stat label="Gameweek high"
                value={view.best ? view.best.scored : '–'}
                sub={view.best ? fullName(meta, view.best.short_name) : ''} />
          <Stat label="Gameweek low"
                value={view.worst ? view.worst.scored : '–'}
                sub={view.worst ? fullName(meta, view.worst.short_name) : ''} />
          <Stat label="League average" value={round(view.leagueAvg)} sub={`${view.leagueTotal} total`} />
          {can(meta, 'optimal_points') && (
            <Stat label="Left on the bench" value={Math.round(view.totalLost)}
                  sub="league-wide vs optimal XI" />
          )}
        </StatRow>
      </Section>

      <Section title="Standings after this gameweek">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>#</th><th>Drafter</th><th>GW</th><th>Total</th>
                <th>Form</th><th>vs optimal</th>
              </tr>
            </thead>
            <tbody>
              {view.drafters.map(d => {
                const move = rankMove(d.rank, d.last_rank)
                return (
                  <tr key={d.short_name}>
                    <td className="num">
                      {d.rank}
                      {move && <span className={`rank-move ${move.className}`}>{move.text}</span>}
                    </td>
                    <td>{fullName(meta, d.short_name)}<span className="muted small"> {d.short_name}</span></td>
                    <td className="num">{d.scored}</td>
                    <td className="num">{d.cumulative ?? d.total}</td>
                    <td className="num">{round(d.form_points)}</td>
                    <td className="num">{d.lostToSubs > 0 ? `−${Math.round(d.lostToSubs)}` : '0'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <Collapsible
        title="Squads"
        summary="colour grid · swipe across"
        open
      >
        <SquadGrid columns={view.drafters.map(d => ({
          short: d.short_name, table: d, gwTotal: d.scored, cells: d.squad,
        }))} meta={meta} transfers={data.transfers} trades={data.trades}
           league={league} gameweek={gw} />
      </Collapsible>

      <Collapsible
        title="Substitutions"
        count={view.subs.length}
        summary={`${Math.round(view.totalLost)} pts left on benches`}
      >
        {view.subs.length === 0 ? (
          <p className="muted small">No auto-subs this gameweek.</p>
        ) : (
          <>
            <SubHead note="Auto-subs applied when a starter didn't play">Subbed players</SubHead>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>Drafter</th><th>Player</th><th>Pos</th><th>Pts</th><th>Sub</th></tr>
                </thead>
                <tbody>
                  {view.subs.map((s, i) => (
                    <tr key={i}>
                      <td>{fullName(meta, s.short_name)}</td>
                      <td>{s.web_name}{s.team_name ? <span className="muted small"> {s.team_name}</span> : null}</td>
                      <td>{s.position}</td>
                      <td className="num">{s.points}</td>
                      <td>{s.kind === 'on' ? 'came on' : 'went off'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <SubHead note="Points a perfect line-up would have added">Cost per drafter</SubHead>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>Drafter</th><th>Scored</th><th>Optimal</th><th>Lost</th><th>Auto-sub gain</th></tr>
                </thead>
                <tbody>
                  {[...view.drafters].sort((a, b) => b.lostToSubs - a.lostToSubs).map(d => (
                    <tr key={d.short_name}>
                      <td>{fullName(meta, d.short_name)}</td>
                      <td className="num">{d.scored}</td>
                      <td className="num">{round(d.optimal)}</td>
                      <td className="num">{d.lostToSubs > 0 ? `−${Math.round(d.lostToSubs)}` : '0'}</td>
                      <td className="num">{signed(d.autoSubGain)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Collapsible>

      <Collapsible
        title="Transfers & trades"
        count={view.moves.length}
        summary="accepted moves this gameweek"
      >
        {view.moves.length === 0 ? (
          <p className="muted small">No accepted moves this gameweek.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Drafter</th><th>Type</th><th>In</th><th>Pts</th>
                  <th>Out</th><th>Pts</th><th>Net</th>
                </tr>
              </thead>
              <tbody>
                {view.moves.map((m, i) => (
                  <tr key={i}>
                    <td>
                      {fullName(meta, m.who)}
                      {m.counterparty && (
                        <span className="muted small"> ↔ {fullName(meta, m.counterparty)}</span>
                      )}
                    </td>
                    <td>{m.type}</td>
                    <td>{m.inName}</td>
                    <td className="num">{m.inPoints ?? '–'}</td>
                    <td>{m.outName}</td>
                    <td className="num">{m.outPoints ?? '–'}</td>
                    <td className={`num ${(m.net ?? 0) > 0 ? 'up' : (m.net ?? 0) < 0 ? 'down' : ''}`}>
                      {signed(m.net)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Collapsible>

    </>
  )
}
