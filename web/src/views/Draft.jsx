import { useMemo, useState } from 'react'
import { useTables, can } from '../lib/data.js'
import { fullName, label, leagueName, pct } from '../lib/names.js'
import {
  Section, Loading, Unavailable, Stat, StatRow, Collapsible, Segmented, LeagueToggle,
} from '../components/ui.jsx'

/**
 * Draft view — every squad in a league side by side, plus each drafter's board
 * in pick order.
 *
 * Deliberately built on what the draft *returned* rather than on a preseason
 * projection. Projections are a separate exercise living outside the pipeline,
 * and for a finished season the interesting question isn't what a pick was
 * expected to be worth, it's what it actually delivered and how much of that
 * the drafter kept.
 *
 * Season points come from `draft_performance`, which carries `total_points` and
 * `points_realised_by_drafter` under unambiguous names. `draft_picks` now agrees
 * with it in every season — it used to mean the season total in the 2425 archive
 * and the drafter's realised share in 2526 — but reading the pair from one table
 * keeps the two quantities impossible to confuse. See docs/data-contract.md.
 */
export default function Draft({ season, meta, league, setLeague }) {
  const { data, loading, error } = useTables(season, ['draft_picks', 'draft_performance', 'players'])
  const [sort, setSort] = useState('pool')

  const v = useMemo(() => {
    if (!data) return null
    const { draft_picks, draft_performance, players } = data

    const picks = draft_picks.filter(p => p.league === league)
    if (!picks.length) return { empty: true }

    const perf = new Map(draft_performance
      .filter(p => p.league === league)
      .map(p => [p.element, p]))
    const playerBy = new Map(players.map(p => [p.element, p]))

    // Round 1 order defines each drafter's slot in the snake.
    const slots = new Map([...picks]
      .filter(p => p.round === 1)
      .sort((a, b) => a.index - b.index)
      .map((p, i) => [p.short_name, i + 1]))

    const byDrafter = new Map()
    for (const pick of [...picks].sort((a, b) => a.index - b.index)) {
      if (!byDrafter.has(pick.short_name)) byDrafter.set(pick.short_name, [])
      const pf = perf.get(pick.element)
      const player = playerBy.get(pick.element)
      byDrafter.get(pick.short_name).push({
        ...pick,
        seasonPoints: pf?.total_points ?? null,
        captured: pf?.points_realised_by_drafter ?? null,
        lost: pf?.points_realised_by_other ?? null,
        stillOwned: pf?.still_owned ?? null,
        currentOwner: pf?.current_owner ?? null,
        cost: player?.now_cost ?? pick.now_cost ?? null,
        rank: pick.draft_rank ?? null,
      })
    }

    const squads = [...byDrafter].map(([short_name, list]) => {
      const scored = list.filter(p => p.seasonPoints != null)
      const pool = sum(scored.map(p => p.seasonPoints))
      const captured = sum(list.map(p => p.captured ?? 0))
      const ranked = list.filter(p => p.rank != null)
      const costed = list.filter(p => p.cost != null)
      const best = [...scored].sort((a, b) => b.seasonPoints - a.seasonPoints)[0] ?? null
      const worst = [...scored].sort((a, b) => a.seasonPoints - b.seasonPoints)[0] ?? null
      return {
        short_name,
        slot: slots.get(short_name) ?? null,
        picks: list,
        n: list.length,
        pool,
        captured,
        captureRate: pool ? captured / pool : null,
        lost: sum(list.map(p => p.lost ?? 0)),
        held: list.filter(p => p.stillOwned).length,
        // The shape of their board, not just its centre. A mean alone hides the
        // difference between someone who spread evenly and someone who paired a
        // couple of stars with a tail of long shots.
        rankSpread: rankSpread(ranked.map(p => p.rank)),
        // Chalk versus reach, both knowable on the night: how many picks came
        // from the consensus top 30, and how many from outside its top 100.
        chalk: ranked.length ? ranked.filter(p => p.rank <= 30).length : null,
        reaches: ranked.length ? ranked.filter(p => p.rank > 100).length : null,
        cost: costed.length === list.length ? sum(costed.map(p => p.cost)) : null,
        best, worst,
      }
    })

    const order = { pool: (a, b) => b.pool - a.pool,
      captured: (a, b) => b.captured - a.captured,
      capture: (a, b) => (b.captureRate ?? 0) - (a.captureRate ?? 0),
      slot: (a, b) => (a.slot ?? 99) - (b.slot ?? 99) }
    squads.sort(order[sort] ?? order.pool)

    const totalPool = sum(squads.map(s => s.pool))
    return {
      squads,
      hasRank: squads.some(s => s.rankSpread != null),
      hasCost: squads.some(s => s.cost != null),
      best: squads.reduce((x, s) => (s.pool > (x?.pool ?? -1) ? s : x), null),
      spread: squads.length ? squads[0].pool - squads[squads.length - 1].pool : 0,
      leagueAvgCapture: totalPool ? sum(squads.map(s => s.captured)) / totalPool : null,
    }
  }, [data, league, sort])

  if (error) return <Unavailable what="Draft" season={season} reason={String(error.message ?? error)} />
  if (loading || !v) return <Loading what="draft" />
  if (v.empty) {
    return (
      <Unavailable
        what="Draft"
        season={season}
        reason={`No draft has been recorded for the ${leagueName(meta, league)} yet.`}
      />
    )
  }

  const spreadPct = v.best && v.spread ? Math.round((v.spread / v.best.pool) * 100) : 0

  return (
    <>
      <Section
        title={`${leagueName(meta, league)} draft`}
        note="What each drafter's picks went on to score, and how much of it they kept."
        aside={<LeagueToggle meta={meta} league={league} setLeague={setLeague} />}
      >
        <StatRow>
          <Stat
            label="Best draft"
            value={v.best ? fullName(meta, v.best.short_name) : '–'}
            sub={v.best ? `${v.best.pool} pts from their 15 picks` : null}
          />
          <Stat label="Spread, best to worst" value={v.spread} sub={`${spreadPct}% of the top squad`} />
          <Stat
            label="League capture rate"
            value={v.leagueAvgCapture == null ? '–' : pct(v.leagueAvgCapture, 0)}
            sub="share of their picks' points kept"
          />
        </StatRow>

        <div style={{ margin: '10px 0' }}>
          <Segmented
            ariaLabel="Sort squads"
            value={sort}
            onChange={setSort}
            options={[
              { value: 'pool', label: 'Points drafted', title: "What their picks scored, whoever owned them" },
              { value: 'captured', label: 'Points kept' },
              { value: 'capture', label: 'Capture rate' },
              { value: 'slot', label: 'Draft order' },
            ]}
          />
        </div>

        <div className="table-wrap">
          <table className="data">
            <thead>
              {/* Two header rows: what was knowable on the night, then what the
                  season revealed. Judging a draft means not mixing the two. */}
              <tr className="group-head">
                <th />
                <th className="num" colSpan={1 + (v.hasRank ? 2 : 0)}>Known at the draft</th>
                <th className="num" colSpan={6 + (v.hasCost ? 1 : 0)}>Known only afterwards</th>
              </tr>
              <tr>
                <th>Drafter</th>
                <th className="num" title="Position in the round-one order">Slot</th>
                {v.hasRank && (
                  <th
                    className="num"
                    title="FPL's preseason consensus rank across their picks: the earliest-ranked player they took, the middle of their board, the mean, and the latest-ranked. A tight spread means they drafted evenly; a long tail means stars plus long shots."
                  >
                    Rank best·med·avg·worst
                  </th>
                )}
                {v.hasRank && <th className="num" title="Picks taken from the consensus top 30 / from outside its top 100">Chalk / reach</th>}
                <th className="num" title="Total scored by the players they drafted, whoever ended up owning them">Points drafted</th>
                <th className="num" title="Of that, the points scored while they still owned the player">Kept</th>
                <th className="num">Capture</th>
                <th className="num" title="Points their picks scored for a rival after being dropped or traded">Lost to rivals</th>
                <th className="num" title="Picks still on their roster at the end of the season">Held</th>
                {v.hasCost && <th className="num" title="Latest recorded valuation of the drafted squad — not the price on draft night, which no source records">Value now</th>}
                <th>Best pick</th>
              </tr>
            </thead>
            <tbody>
              {v.squads.map(s => (
                <tr key={s.short_name}>
                  <td><strong>{fullName(meta, s.short_name)}</strong></td>
                  <td className="num muted">{s.slot ?? '–'}</td>
                  {v.hasRank && (
                    <td className="num muted">
                      {s.rankSpread == null
                        ? '–'
                        : `${s.rankSpread.best}·${s.rankSpread.median}·${s.rankSpread.mean}·${s.rankSpread.worst}`}
                    </td>
                  )}
                  {v.hasRank && (
                    <td className="num muted">
                      {s.chalk == null ? '–' : `${s.chalk} / ${s.reaches}`}
                    </td>
                  )}
                  <td className="num"><strong>{s.pool}</strong></td>
                  <td className="num">{s.captured}</td>
                  <td className="num">{s.captureRate == null ? '–' : pct(s.captureRate, 0)}</td>
                  <td className="num muted">{s.lost}</td>
                  <td className="num muted">{s.held}/{s.n}</td>
                  {v.hasCost && <td className="num muted">{s.cost == null ? '–' : `£${s.cost.toFixed(1)}m`}</td>}
                  <td className="muted">
                    {s.best ? `${s.best.web_name} (${s.best.seasonPoints})` : '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          <strong>Points drafted</strong> counts everything the players they picked scored that
          season, even after being dropped — it measures the draft itself.{' '}
          <strong>Kept</strong> is the part they actually banked.
        </p>
        <p className="small muted">
          The left-hand block is what anyone could see on draft night; everything to its right
          needed the season to happen. {v.hasRank
            ? 'The rank figures are FPL’s preseason consensus across a drafter’s fifteen picks. Median well below mean means a handful of long shots dragging the tail; best and worst show how far they ranged.'
            : `${season} has no consensus rank in its source data, so the only pre-draft fact recorded is the pick order.`}
        </p>
        <p className="small muted">
          Three things you might expect on the left aren&apos;t there, because no source records
          them for {season}: <strong>previous-season points</strong> and <strong>players new to
          the Premier League</strong> both need a player key that survives a season change, which
          the 2425 archive doesn&apos;t carry; and <strong>the valuation at the draft</strong> is
          nowhere — cost is a single later snapshot, and the field that would recover the opening
          price lives on the fantasy API, which had already rolled over. Fixable from 2627 on.
        </p>
      </Section>

      <Section title="Every board, pick by pick">
        {v.squads.map(s => (
          <Collapsible
            key={s.short_name}
            title={fullName(meta, s.short_name)}
            count={s.pool}
            summary={`${s.captured} kept · ${s.held}/${s.n} held all season`}
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">R</th>
                    <th>Player</th>
                    <th>Pos</th>
                    {can(meta, 'team_names') && <th>Club</th>}
                    {v.hasRank && <th className="num">Rank</th>}
                    <th className="num">Scored</th>
                    <th className="num">Kept</th>
                    <th>Ended with</th>
                  </tr>
                </thead>
                <tbody>
                  {s.picks.map(p => (
                    <tr key={p.element}>
                      <td className="num muted">{p.round}</td>
                      <td>{p.web_name}</td>
                      <td className="muted">{p.position}</td>
                      {can(meta, 'team_names') && <td className="muted">{p.team_name}</td>}
                      {v.hasRank && <td className="num muted">{p.rank ?? '–'}</td>}
                      <td className="num">{p.seasonPoints ?? '–'}</td>
                      <td className="num">{p.captured ?? '–'}</td>
                      <td className="muted">
                        {p.stillOwned
                          ? '—'
                          : p.currentOwner
                            ? label(p.currentOwner)
                            : 'dropped'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Collapsible>
        ))}
      </Section>
    </>
  )
}

const sum = xs => xs.reduce((a, b) => a + (Number(b) || 0), 0)

/** Best / median / mean / worst consensus rank across a set of picks. */
function rankSpread(ranks) {
  const values = ranks.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
  if (!values.length) return null
  const middle = values.length >> 1
  return {
    best: values[0],
    median: Math.round(values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2),
    mean: Math.round(sum(values) / values.length),
    worst: values[values.length - 1],
  }
}
