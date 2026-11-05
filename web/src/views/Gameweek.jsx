import { useEffect, useMemo, useState } from 'react'
import { useTables, useAsync, loadTableIfPresent, can, executedTrades } from '../lib/data.js'
import { navigate } from '../lib/router.js'
import { fullName, label, round, signed, rankMove } from '../lib/names.js'
import { headToHeadTable, fixturesFor } from '../lib/standings.js'
import {
  LeagueToggle, Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead, Modal,
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

  // Weekly talking points — optional file, absent on seasons built before it existed.
  const beatsFile = useAsync(
    () => (can(meta, 'weekly_beats') ? loadTableIfPresent(season, 'weekly_beats') : Promise.resolve(null)),
    [season, meta],
  )

  // Points-breakdown drill-down: which squad cell is open, and that gameweek's
  // breakdown file, fetched lazily on first open and promise-cached after.
  const canBreakdown = can(meta, 'points_breakdown')
  const [selected, setSelected] = useState(null)   // { row, short }
  useEffect(() => { setSelected(null) }, [season, league, gw])
  const breakdown = useAsync(
    () => (selected && canBreakdown
      ? loadTableIfPresent(season, `points_breakdown/${gw}`)
      : Promise.resolve(null)),
    [season, gw, canBreakdown, selected != null],
  )

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
        // Net bench points: how far short of the hindsight-optimal XI the
        // lineup fell. This is the group's "benched points" — not what places
        // 12-15 scored in total, most of which could never have started.
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
    const biggestBench = drafters.reduce((a, b) => (b.lostToSubs > (a?.lostToSubs ?? -1) ? b : a), null)
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
    for (const t of executedTrades(trades)) {
      if (t.league !== league || t.gameweek !== gw) continue
      moves.push({
        type: 'Trade', who: t.offered_by, inName: t.player_in, outName: t.player_out,
        inPoints: t.player_in_points, outPoints: t.player_out_points,
        net: t.net_points, counterparty: t.received_by,
      })
    }
    moves.sort((a, b) => Math.abs(b.net ?? 0) - Math.abs(a.net ?? 0))

    // Best transfer of the week, on in-week net points. Trades are excluded: their
    // net is measured from the trade to season end, not within this gameweek.
    const bestMove = moves.reduce((a, m) => (
      m.type !== 'Trade' && m.net != null && m.net > (a?.net ?? -Infinity) ? m : a
    ), null)

    // The league's own table, as it stood after the selected gameweek — folded
    // from the fixtures rather than read off the shipped table, which is only
    // ever season-to-date.
    const fixtures = (data.h2h_matches ?? []).filter(m => m.league === league)
    const standings = h2h
      ? headToHeadTable(fixtures, table.map(t => t.short_name), gw)
      : null

    return {
      table, drafters, best, worst, biggestBench, bestMove,
      leagueTotal, leagueAvg, totalLost, subs, moves,
      standings, fixtures: fixturesFor(fixtures, gw),
    }
  }, [data, league, gw, meta.gameweeks, h2h])

  if (error) return <div className="notice">Couldn&apos;t load gameweek data: {String(error.message)}</div>
  if (loading || !view) return <Loading what={`gameweek ${gw}`} />

  const beats = (beatsFile.data ?? [])
    .filter(b => b.league === league && b.gameweek === gw && BEAT_KINDS.has(b.kind))

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
            <Stat label="Benched points"
                  value={view.biggestBench ? Math.round(view.biggestBench.lostToSubs) : '–'}
                  sub={view.biggestBench
                    ? `${fullName(meta, view.biggestBench.short_name)} · net, vs their optimal XI`
                    : ''} />
          )}
          {view.bestMove && (
            <Stat label="Best transfer" value={signed(view.bestMove.net)}
                  sub={`${fullName(meta, view.bestMove.who)} · ${view.bestMove.inName} in, ${view.bestMove.outName} out`} />
          )}
          {can(meta, 'optimal_points') && (
            <Stat label="Lost vs optimal XI" value={Math.round(view.totalLost)}
                  sub="league-wide" />
          )}
        </StatRow>

        {beats.length > 0 && (
          <>
            <SubHead>Talking points</SubHead>
            <ul className="beats">
              {beats.map((b, i) => <li key={i}><BeatLine beat={b} meta={meta} /></li>)}
            </ul>
          </>
        )}
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
           league={league} gameweek={gw}
           onSelect={canBreakdown ? (row, short) => setSelected({ row, short }) : undefined} />
      </Collapsible>

      {selected && (
        <Modal
          title={`${selected.row.web_name} — gameweek ${gw}`}
          onClose={() => setSelected(null)}
        >
          <PlayerBreakdown row={selected.row} short={selected.short} meta={meta}
                           state={breakdown} />
        </Modal>
      )}

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

/* ---------- weekly talking points ---------- */

// The beat kinds this build knows how to phrase. Anything else in the file is a
// newer pipeline talking to an older client — skipped, never an error.
const BEAT_KINDS = new Set([
  'lead_change', 'season_high', 'season_low', 'personal_outlier',
  'bench_pain', 'instant_transfer', 'trade_executed', 'h2h_upset', 'keeper_call',
])

// The tail of a keeper_call line: a perfect record of wrong calls is the joke,
// a streak is the habit, and otherwise it is just this week's cost.
function keeperCallTail(d) {
  if (d.weeks >= 3 && d.wrong === d.weeks) {
    return <> — the wrong keeper <strong>{d.wrong} weeks out of {d.weeks}</strong> this season</>
  }
  if (d.streak >= 3) return <> — the wrong call {d.streak} weeks running</>
  return <> — {d.points_lost} points left in gloves on the bench</>
}

const beatName = (meta, person) =>
  person?.name || fullName(meta, person?.short_name) || person?.short_name || '?'

/** One fixed sentence per beat kind — the pipeline supplies facts, never prose. */
function BeatLine({ beat, meta }) {
  const d = beat.data ?? {}
  switch (beat.kind) {
    case 'lead_change':
      return (
        <>
          <strong>{beatName(meta, d.new)}</strong>
          {d.tied ? ' draws level at the top with ' : ' takes the lead from '}
          {beatName(meta, d.previous)}
          {!d.tied && d.lead > 0 && <>, {d.lead} clear</>}
        </>
      )
    case 'season_high':
      return <><strong>{beatName(meta, d)}</strong> hits {d.points} — the best week by anyone this season</>
    case 'season_low':
      return <><strong>{beatName(meta, d)}</strong> posts {d.points}, the season&apos;s lowest week so far</>
    case 'personal_outlier':
      return (
        <>
          <strong>{beatName(meta, d)}</strong> scored {d.points}, well{' '}
          {d.direction === 'above' ? 'above' : 'below'} their usual {d.average}
        </>
      )
    case 'bench_pain':
      return <><strong>{beatName(meta, d)}</strong> left {d.points_lost} points behind against the optimal XI</>
    case 'keeper_call':
      return (
        <>
          <strong>{beatName(meta, d)}</strong> started {d.started} ({d.started_points}) with{' '}
          {d.benched} ({d.benched_points}) on the bench{keeperCallTail(d)}
        </>
      )
    case 'instant_transfer':
      return (
        <>
          <strong>{beatName(meta, d)}</strong>&apos;s {d.kind === 'waiver' ? 'waiver' : 'pickup'} paid off at once:{' '}
          {d.player_in} in for {d.player_out}, {signed(d.net_points)} this week
        </>
      )
    case 'trade_executed':
      return (
        <>
          Trade through: <strong>{beatName(meta, d.offered_by)}</strong> gets {d.player_in} from{' '}
          {beatName(meta, d.received_by)} for {d.player_out}
        </>
      )
    case 'h2h_upset':
      return (
        <>
          Upset: <strong>{beatName(meta, d.winner)}</strong> (#{d.winner_rank} on points) beat{' '}
          {beatName(meta, d.loser)} (#{d.loser_rank}){d.provisional ? ' — provisional' : ''}
        </>
      )
    default:
      return null
  }
}

/* ---------- points-breakdown modal body ---------- */

function PlayerBreakdown({ row, short, meta, state }) {
  const benched = (row.place ?? 99) > STARTERS
  const record = state.data?.find(r => r.element === row.element)

  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        {row.position}{row.team_name ? ` · ${row.team_name}` : ''} · {fullName(meta, short)} ·{' '}
        {benched ? 'benched' : 'started'}
        {row.originally_starting === 1 && benched && ' (auto-subbed off)'}
        {row.originally_starting === 0 && !benched && ' (auto-subbed on)'}
      </p>
      {state.loading ? (
        <div className="spinner">Loading breakdown…</div>
      ) : !record ? (
        <p className="muted small">No breakdown for this gameweek — the player may not have featured.</p>
      ) : (
        record.fixtures.map((fixture, i) => (
          <div key={i}>
            {record.fixtures.length > 1 && (
              <SubHead note="double gameweek — one table per match">Match {i + 1}</SubHead>
            )}
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>Stat</th><th>Value</th><th>Pts</th></tr>
                </thead>
                <tbody>
                  {fixture.items.map((item, j) => (
                    <tr key={j}>
                      <td>{item.name}</td>
                      <td className="num">{item.value}</td>
                      <td className="num">{item.points}</td>
                    </tr>
                  ))}
                  <tr>
                    <td><strong>Total</strong></td>
                    <td />
                    <td className="num"><strong>{fixture.total}</strong></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}
    </>
  )
}
