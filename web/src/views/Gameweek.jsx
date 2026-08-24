import { useMemo } from 'react'
import { useTables, can } from '../lib/data.js'
import { navigate } from '../lib/router.js'
import { fullName, label, round, signed, rankMove } from '../lib/names.js'
import { headToHeadTable, fixturesFor } from '../lib/standings.js'
import {
  LeagueToggle, Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead,
} from '../components/ui.jsx'
import SquadGrid from '../components/SquadGrid.jsx'

const STARTERS = 11
// Matches the notebook's form window: mean over the last 5 gameweeks, divided by
// however many have actually been played when fewer than 5 exist.
const FORM_GAMES = 5

export default function Gameweek({ season, meta, league, setLeague, route }) {
  const gw = Number(route.param) || meta.current_gameweek
  // Only a league played as weekly fixtures has these, and only seasons built
  // since they existed ship the files at all — so they are asked for by name
  // rather than always, which would 404 the older archives.
  const h2h = meta.leagues?.find(l => l.code === league)?.scoring === 'h2h'
  const { data, loading, error } = useTables(season, [
    'weekly_summary', 'league_table', 'transfers', 'trades',
    ...(h2h ? ['h2h_matches'] : []),
  ])

  const view = useMemo(() => {
    if (!data) return null
    const { weekly_summary, league_table, transfers, trades } = data

    const table = league_table.filter(r => r.league === league)
    const rows = weekly_summary.filter(r => r.league === league && r.gameweek === gw)
    const gwIndex = meta.gameweeks.indexOf(gw)

    // Standings AS AT the selected gameweek. league_table ships rank, last_rank and
    // form for the *final* gameweek only, so reading them directly would show
    // season-end figures while viewing GW8. All three are recoverable from the
    // per-gameweek arrays the pipeline already sends.
    const cumulativeAt = (t, i) => t.cumulative_by_gameweek?.[i] ?? 0
    const ranksAt = i => {
      if (i < 0) return null
      const totals = table.map(t => cumulativeAt(t, i))
      return Object.fromEntries(table.map((t, idx) => [
        t.short_name,
        // method='min', so tied drafters share the better rank
        totals.filter(other => other > totals[idx]).length + 1,
      ]))
    }
    const ranksNow = ranksAt(gwIndex)
    const ranksPrev = ranksAt(gwIndex - 1)

    const formAt = (t, i) => {
      const points = t.points_by_gameweek ?? []
      if (!points.length || i < 0) return null
      const window = points.slice(Math.max(0, i - FORM_GAMES + 1), i + 1)
      const divisor = Math.min(FORM_GAMES, i + 1)
      return divisor ? window.reduce((s, p) => s + (Number(p) || 0), 0) / divisor : null
    }

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
        cumulative: cumulativeAt(t, gwIndex),
        rank: ranksNow?.[t.short_name] ?? t.rank,
        // 0 means "no previous week", which rankMove treats as no movement
        last_rank: ranksPrev?.[t.short_name] ?? 0,
        form_points: formAt(t, gwIndex),
      }
    }).sort((a, b) => a.rank - b.rank)

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

    // The league's own table, as it stood after the selected gameweek — folded
    // from the fixtures rather than read off the shipped table, which is only
    // ever season-to-date.
    const fixtures = (data.h2h_matches ?? []).filter(m => m.league === league)
    const standings = h2h
      ? headToHeadTable(fixtures, table.map(t => t.short_name), gw)
      : null

    return {
      table, drafters, best, worst, leagueTotal, leagueAvg, totalLost, subs, moves,
      standings, fixtures: fixturesFor(fixtures, gw),
    }
  }, [data, league, gw, meta.gameweeks, h2h])

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

      {view.standings && (
        <Section
          title="League table"
          note={`after gameweek ${gw} · won on weekly results, not on points banked`}
        >
          {view.standings.some(r => r.provisional) && (
            <div className="notice" style={{ marginBottom: 10 }}>
              Gameweek {gw} is still being played, so these results are{' '}
              <strong>provisional</strong> — bonus points can still change them, and
              the official table won&apos;t move until they do.
            </div>
          )}
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>#</th><th>Drafter</th><th>P</th><th>W</th><th>D</th><th>L</th>
                  <th>PF</th><th>PA</th><th>Pts</th><th>Form</th>
                </tr>
              </thead>
              <tbody>
                {view.standings.map(r => {
                  const move = rankMove(r.rank, r.lastRank)
                  return (
                    <tr key={r.shortName}>
                      <td className="num">
                        {r.rank}
                        {move && <span className={`rank-move ${move.className}`}>{move.text}</span>}
                      </td>
                      <td>
                        {fullName(meta, r.shortName)}
                        <span className="muted small"> {r.shortName}</span>
                      </td>
                      <td className="num">{r.played}</td>
                      <td className="num">{r.won}</td>
                      <td className="num">{r.drawn}</td>
                      <td className="num">{r.lost}</td>
                      <td className="num">{r.pointsFor}</td>
                      <td className="num">{r.pointsAgainst}</td>
                      <td className="num"><strong>{r.points}</strong></td>
                      <td className="muted small">{r.form.join(' ') || '–'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {view.fixtures.length > 0 && (
            <>
              <SubHead>This gameweek</SubHead>
              <div className="table-wrap">
                <table className="data">
                  <tbody>
                    {view.fixtures.map(f => (
                      <tr key={`${f.home}-${f.away}`}>
                        <td style={{ textAlign: 'right' }}>
                          {f.winner === f.home ? <strong>{fullName(meta, f.home)}</strong>
                                               : fullName(meta, f.home)}
                        </td>
                        <td className="num">{f.started ? f.home_points : '–'}</td>
                        <td className="muted small">v</td>
                        <td className="num">{f.started ? f.away_points : '–'}</td>
                        <td>
                          {f.winner === f.away ? <strong>{fullName(meta, f.away)}</strong>
                                               : fullName(meta, f.away)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Section>
      )}

      <Section
        title={view.standings ? 'Points scored' : 'Standings after this gameweek'}
        note={view.standings
          ? 'the same league ranked on points banked — not the competition, but the better read on who is playing well'
          : undefined}
      >
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
