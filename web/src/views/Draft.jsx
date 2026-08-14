import { useMemo } from 'react'
import { useTables, useAsync, loadTableIfPresent } from '../lib/data.js'
import { fullName, label, leagueName } from '../lib/names.js'
import { previousSeason, clubMarket, playerMarket, clubSet } from '../lib/market.js'
import {
  Section, Loading, Unavailable, Stat, StatRow, Collapsible, LeagueToggle,
} from '../components/ui.jsx'

/**
 * Draft night — the evening itself, judged only on what was knowable at the time.
 *
 * Nothing here uses a player's eventual points. Whether a gamble came off is a
 * question about the season, and that lives in Season Trends → Draft picks; mixing
 * the two is how you end up calling a sound pick bad because the player got hurt
 * in October.
 *
 * Everything rests on `draft_rank`, FPL's preseason consensus. The 2425 archive
 * has no such column, so this view degrades to the pick order alone.
 */
export default function Draft({ season, meta, league, setLeague }) {
  const { data, loading, error } = useTables(season, ['draft_picks'])

  // Last year's draft, for the hot-and-not comparison. Optional by design: the
  // oldest season in the archive has nothing behind it. Deliberately only the pick
  // tables and the club lists — players.json is 190 KB a season and this view is
  // otherwise a 38 KB load on a phone.
  const prevSeason = previousSeason(season)
  const past = useAsync(() => Promise.all([
    prevSeason ? loadTableIfPresent(prevSeason, 'draft_picks') : Promise.resolve(null),
    prevSeason ? loadTableIfPresent(prevSeason, 'teams') : Promise.resolve(null),
    loadTableIfPresent(season, 'teams'),
  ]).then(([picks, priorTeams, teams]) => ({ picks, priorTeams, teams })), [season, prevSeason])

  const v = useMemo(() => {
    if (!data) return null
    const all = data.draft_picks
    const picks = all
      .filter(p => p.league === league)
      .sort((a, b) => a.index - b.index)
    if (!picks.length) return { empty: true }

    const ranked = picks.filter(p => p.draft_rank != null)
    const hasRank = ranked.length > 0

    // What rank normally goes at each slot, fitted across the whole season so
    // both leagues inform the curve. Without it, "took him early" is meaningless:
    // by pick 80 every remaining player is ranked in the hundreds, so a raw
    // rank-minus-slot makes every late pick look like a wild reach.
    const expectedRank = fitBoardCurve(all)

    // Replay the night. A pick "passed over" a player only if that player was
    // still on the board AND someone else took him later — so every miss named
    // here is one a rival actually acted on, not a player the whole league
    // ignored. That distinction matters: a highly ranked player nobody drafts
    // would otherwise sit at the top of the board all night and make every
    // single pick look like a blunder.
    const replay = picks.map((pick, i) => {
      const laterRanked = picks.slice(i + 1).filter(p => p.draft_rank != null)
      const bestLater = laterRanked.reduce(
        (best, p) => (best == null || p.draft_rank < best.draft_rank ? p : best), null,
      )
      const passedOver = hasRank && bestLater && pick.draft_rank != null
        && bestLater.draft_rank < pick.draft_rank
        ? { player: bestLater, gap: pick.draft_rank - bestLater.draft_rank }
        : null
      const reach = pick.draft_rank == null ? null
        : Math.round(pick.draft_rank - expectedRank(pick.index))
      return { ...pick, passedOver, reach }
    })

    const byDrafter = new Map()
    for (const pick of replay) {
      if (!byDrafter.has(pick.short_name)) byDrafter.set(pick.short_name, [])
      byDrafter.get(pick.short_name).push(pick)
    }

    const slots = new Map(picks.filter(p => p.round === 1).map((p, i) => [p.short_name, i + 1]))

    const drafters = [...byDrafter].map(([short_name, list]) => {
      const withRank = list.filter(p => p.draft_rank != null)
      const reaches = list.filter(p => p.reach != null)
      const passes = list.filter(p => p.passedOver)
      return {
        short_name,
        slot: slots.get(short_name) ?? null,
        picks: list,
        n: list.length,
        rankSpread: rankSpread(withRank.map(p => p.draft_rank)),
        chalk: withRank.length ? withRank.filter(p => p.draft_rank <= 30).length : null,
        // A gamble is a pick taken well ahead of where the board had him.
        gambles: reaches.length ? reaches.filter(p => p.reach >= REACH).length : null,
        biggestReach: reaches.length
          ? reaches.reduce((a, b) => (b.reach > a.reach ? b : a)) : null,
        meanReach: reaches.length
          ? Math.round(reaches.reduce((s, p) => s + p.reach, 0) / reaches.length) : null,
        // The single clearest thing they left on the table.
        biggestPass: passes.length
          ? passes.reduce((a, b) => (b.passedOver.gap > a.passedOver.gap ? b : a)) : null,
        bigPasses: withRank.length
          ? passes.filter(p => p.passedOver.gap >= PASS).length : null,
      }
    }).sort((a, b) => (a.slot ?? 99) - (b.slot ?? 99))

    const gambled = drafters.filter(d => d.biggestReach)

    // The player the room kept walking past. Counting how many picks he was the
    // best available at says more than any one drafter's biggest miss: when the
    // same name is everyone's, that is the board misreading him collectively,
    // not one person's blunder.
    const passCounts = new Map()
    for (const pick of replay) {
      if (!pick.passedOver) continue
      const other = pick.passedOver.player
      const entry = passCounts.get(other.element) ?? { player: other, times: 0, until: other.index }
      entry.times += 1
      passCounts.set(other.element, entry)
    }
    const mostPassed = [...passCounts.values()]
      .sort((a, b) => b.times - a.times || a.player.draft_rank - b.player.draft_rank)[0] ?? null

    return {
      drafters,
      hasRank,
      totalPicks: picks.length,
      boldest: gambled.length
        ? gambled.reduce((a, b) => (b.biggestReach.reach > a.biggestReach.reach ? b : a)) : null,
      // Nearest to consensus means smallest deviation either way — a drafter who
      // consistently took better-ranked players than the slot warranted is not
      // "closest to the board", they are just getting value.
      steadiest: gambled.length
        ? gambled.reduce((a, b) => (Math.abs(b.meanReach) < Math.abs(a.meanReach) ? b : a)) : null,
      mostPassed,
    }
  }, [data, league])

  // Where the league's taste moved since the previous draft.
  const market = useMemo(() => {
    const priorAll = past.data?.picks
    if (!data || !priorAll?.length) return null
    const inLeague = rows => rows.filter(p => p.league === league)
    const prior = inLeague(priorAll)
    if (!prior.length) return null   // league didn't exist under this code last year

    const clubs = clubSet(past.data.teams)
    const priorClubs = clubSet(past.data.priorTeams)
    return {
      priorSeason: prevSeason,
      clubs: clubMarket(inLeague(data.draft_picks), prior, {
        clubs: clubs.size ? clubs : null,
        priorClubs: priorClubs.size ? priorClubs : null,
      }),
      players: playerMarket(inLeague(data.draft_picks), prior, {
        priorAllPicks: priorAll,
        allPicks: data.draft_picks,
        priorClubs: priorClubs.size ? priorClubs : null,
      }),
    }
  }, [data, past.data, league, prevSeason])

  if (error) return <Unavailable what="Draft night" season={season} reason={String(error.message ?? error)} />
  if (loading || !v) return <Loading what="the draft" />
  if (v.empty) {
    return (
      <Unavailable
        what="Draft night"
        season={season}
        reason={`No draft has been recorded for the ${leagueName(meta, league)} yet.`}
      />
    )
  }

  return (
    <>
      <Section
        title={`${leagueName(meta, league)} draft night`}
        note="How the board was read on the night — before anyone had kicked a ball."
        aside={<LeagueToggle meta={meta} league={league} setLeague={setLeague} />}
      >
        {!v.hasRank ? (
          <Unavailable
            what="Draft-night analysis"
            season={season}
            reason={`${season}'s source data carries no consensus rank, so there is no board to
                     compare the picks against. The order they were taken in is all that survives.`}
          />
        ) : (
          <>
            <StatRow>
              <Stat
                label="Boldest pick"
                value={v.boldest ? v.boldest.biggestReach.web_name : '–'}
                sub={v.boldest
                  ? `${label(v.boldest.short_name)} took him ${v.boldest.biggestReach.reach} places early`
                  : null}
              />
              <Stat
                label="Most walked past"
                value={v.mostPassed ? v.mostPassed.player.web_name : '–'}
                sub={v.mostPassed
                  ? `rank ${v.mostPassed.player.draft_rank}, still there at ${v.mostPassed.times} picks before going at ${v.mostPassed.until}`
                  : null}
              />
              <Stat
                label="Nearest to consensus"
                value={v.steadiest ? fullName(meta, v.steadiest.short_name) : '–'}
                sub={v.steadiest
                  ? `${Math.abs(v.steadiest.meanReach)} places off the board on average${v.steadiest.meanReach < 0 ? ', taking value' : ''}`
                  : null}
              />
            </StatRow>

            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Drafter</th>
                    <th className="num" title="Position in the round-one order">Slot</th>
                    <th className="num" title="Consensus rank across their picks: earliest-ranked, middle, mean, latest">Rank best·med·avg·worst</th>
                    <th className="num" title="Picks taken from the consensus top 30">Chalk</th>
                    <th className="num" title={`Picks taken ${REACH}+ places ahead of where the board had them`}>Gambles</th>
                    <th title="The pick taken furthest ahead of consensus">Boldest pick</th>
                    <th className="num" title={`Picks where a player ranked ${PASS}+ places better was still available, and went later to someone else`}>Value left</th>
                    <th title="The best-ranked player still on the board when they picked, who a rival then took">Biggest one left</th>
                  </tr>
                </thead>
                <tbody>
                  {v.drafters.map(d => (
                    <tr key={d.short_name}>
                      <td><strong>{fullName(meta, d.short_name)}</strong></td>
                      <td className="num muted">{d.slot ?? '–'}</td>
                      <td className="num muted">
                        {d.rankSpread == null ? '–'
                          : `${d.rankSpread.best}·${d.rankSpread.median}·${d.rankSpread.mean}·${d.rankSpread.worst}`}
                      </td>
                      <td className="num muted">{d.chalk ?? '–'}</td>
                      <td className="num">{d.gambles ?? '–'}</td>
                      <td className="muted">
                        {d.biggestReach
                          ? `${d.biggestReach.web_name} (+${d.biggestReach.reach})`
                          : '–'}
                      </td>
                      <td className="num">{d.bigPasses ?? '–'}</td>
                      <td className="muted">
                        {d.biggestPass
                          ? `${d.biggestPass.passedOver.player.web_name} (+${d.biggestPass.passedOver.gap})`
                          : '–'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="small muted">
              <strong>Gambles</strong> counts picks taken {REACH} or more places ahead of where the
              season&apos;s board normally has that slot, so it measures conviction rather than
              lateness — by pick 80 everyone is taking players ranked in the hundreds.{' '}
              <strong>Value left</strong> counts picks where someone ranked {PASS}+ places better
              was still available <em>and</em> was taken later by a rival, so every miss named here
              is one another drafter acted on rather than a player the whole league passed on.
            </p>
            <p className="small muted">
              Whether any of it came off is a different question, and a season-long one — that
              lives in <strong>Season Trends → Draft picks</strong>.
            </p>
          </>
        )}
      </Section>

      {market && <Market market={market} league={league} meta={meta} />}

      <Section title="Every board, pick by pick">
        {v.drafters.map(d => (
          <Collapsible
            key={d.short_name}
            title={fullName(meta, d.short_name)}
            count={d.slot ? `slot ${d.slot}` : undefined}
            summary={v.hasRank && d.gambles != null
              ? `${d.gambles} gamble${d.gambles === 1 ? '' : 's'} · ${d.bigPasses} left on the board`
              : `${d.n} picks`}
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th className="num">Rd</th>
                    <th>Player</th>
                    <th>Pos</th>
                    <th>Club</th>
                    {v.hasRank && <th className="num">Rank</th>}
                    {v.hasRank && <th className="num" title="Places ahead of where the board has this slot">vs board</th>}
                    {v.hasRank && <th>Best still available</th>}
                  </tr>
                </thead>
                <tbody>
                  {d.picks.map(p => (
                    <tr key={p.element}>
                      <td className="num muted">{p.index}</td>
                      <td className="num muted">{p.round}</td>
                      <td>{p.web_name}</td>
                      <td className="muted">{p.position}</td>
                      <td className="muted">{p.team_name}</td>
                      {v.hasRank && <td className="num muted">{p.draft_rank ?? '–'}</td>}
                      {v.hasRank && (
                        <td className="num" style={p.reach >= REACH ? { color: 'var(--accent, inherit)' } : undefined}>
                          {p.reach == null ? '–' : p.reach > 0 ? `+${p.reach}` : p.reach}
                        </td>
                      )}
                      {v.hasRank && (
                        <td className="muted">
                          {p.passedOver
                            ? `${p.passedOver.player.web_name} (${p.passedOver.player.draft_rank}) → ${label(p.passedOver.player.short_name)}`
                            : '—'}
                        </td>
                      )}
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

const SEASON_LABEL = season => `20${String(season).slice(0, 2)}/${String(season).slice(2)}`

/** How many risers and fallers to name before the full list. */
const NAMED = 6

const ARRIVAL_NOTE = {
  other_league: 'went in the other league last year',
  new_to_division: 'club was not in the division last year',
  undrafted_last_year: 'not drafted last year',
}
const DEPARTURE_NOTE = {
  other_league: 'taken by the other league this year',
  undrafted_this_year: 'not drafted this year',
}

/**
 * Hot and not against the previous draft, by club and by player.
 *
 * Clubs first, because that is where a whole-squad repricing shows up and where the
 * sample is big enough to mean something: six drafters take ninety players, so a
 * club moving by three or four picks is a real shift in opinion. Player movement is
 * noisier by nature — one drafter's conviction can move a single name a long way —
 * so it is presented as named examples rather than a league-wide trend.
 */
function Market({ market, league, meta }) {
  const { clubs, players, priorSeason } = market
  const priorLabel = SEASON_LABEL(priorSeason)
  const movedClubs = clubs.filter(c => c.delta !== 0)
  const hottest = movedClubs[0]
  const coldest = movedClubs[movedClubs.length - 1]
  const topRiser = players.hotter[0]
  const named = [...players.hotter.slice(0, NAMED), ...players.cooler.slice(0, NAMED)]
    .sort((a, b) => b.move - a.move)

  return (
    <>
      <Section
        title={`Hot and not since the ${priorLabel} draft`}
        note={`Where the ${leagueName(meta, league)}'s collective taste moved. Bear in mind the
               league itself turns over — two up, two down — so this is the room's opinion, not
               the same six people changing their minds.`}
      >
        <StatRow>
          <Stat
            label="Club in demand"
            value={hottest && hottest.delta > 0 ? hottest.club : '–'}
            sub={hottest && hottest.delta > 0
              ? `${hottest.priorN} drafted last year, ${hottest.n} this year${hottest.status === 'new_to_division' ? ' — newly promoted' : ''}`
              : 'no club gained ground'}
          />
          <Stat
            label="Club out of favour"
            value={coldest && coldest.delta < 0 ? coldest.club : '–'}
            sub={coldest && coldest.delta < 0
              ? `${coldest.priorN} last year, ${coldest.n === 0 ? 'none at all' : `${coldest.n}`} this year`
              : 'no club lost ground'}
          />
          <Stat
            label="Biggest riser"
            value={topRiser ? topRiser.web_name : '–'}
            sub={topRiser
              ? `pick ${topRiser.priorIndex} → ${topRiser.index}, ${topRiser.move} places earlier`
              : `no player was drafted in both ${priorLabel} and this year`}
          />
        </StatRow>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Club</th>
                <th className="num" title="Players drafted from this club this year">Now</th>
                <th className="num" title={`Players drafted from this club in ${priorLabel}`}>Then</th>
                <th className="num">Change</th>
                <th className="num" title="Earliest overall pick used on this club">First off</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {movedClubs.map(c => (
                <tr key={c.club}>
                  <td><strong>{c.club}</strong></td>
                  <td className="num">{c.n}</td>
                  <td className="num muted">{c.priorN}</td>
                  <td className="num">{c.delta > 0 ? `+${c.delta}` : c.delta}</td>
                  <td className="num muted">{c.earliest ?? '–'}</td>
                  <td className="small muted">
                    {c.status === 'new_to_division' ? 'new to the division'
                      : c.status === 'left_division' ? 'no longer in the division' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!movedClubs.length && (
          <p className="small muted">Every club drew exactly the same number of picks as last year.</p>
        )}

        {named.length > 0 && (
          <>
            <p className="small muted" style={{ marginTop: 12 }}>
              <strong>Players the room repriced.</strong> Drafted in both years, ranked by how far
              their pick moved. Matched on name — FPL reassigns its player ids every season, so
              nothing here can be joined on them.
            </p>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Club</th>
                    <th className="num">{priorLabel}</th>
                    <th className="num">Now</th>
                    <th className="num">Move</th>
                    <th>Taken by</th>
                  </tr>
                </thead>
                <tbody>
                  {named.map(p => (
                    <tr key={`${p.web_name}-${p.index}`}>
                      <td><strong>{p.web_name}</strong></td>
                      <td className="muted">{p.team_name}</td>
                      <td className="num muted">{p.priorIndex}</td>
                      <td className="num">{p.index}</td>
                      <td className="num">{p.move > 0 ? `+${p.move}` : p.move}</td>
                      <td className="muted">
                        {label(p.short_name)}
                        {p.priorDrafter !== p.short_name && (
                          <span className="small"> (was {label(p.priorDrafter)})</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        <p className="small muted">
          {players.matched} of this league&apos;s picks were also drafted here in {priorLabel}
          {players.held.length > 0 && `, ${players.held.length} at the very same pick number`}.
        </p>
      </Section>

      <Section title={`New faces and dropped names vs ${priorLabel}`}>
        <Collapsible
          title="Drafted this year, not last"
          count={players.arrivals.length}
          summary="New to this league's board"
        >
          <MarketList rows={players.arrivals} notes={ARRIVAL_NOTE} />
        </Collapsible>
        <Collapsible
          title="Drafted last year, not this"
          count={players.departures.length}
          summary="Off the board"
        >
          <MarketList rows={players.departures} notes={DEPARTURE_NOTE} pickLabel={priorLabel} />
        </Collapsible>
      </Section>
    </>
  )
}

function MarketList({ rows, notes, pickLabel = 'Pick' }) {
  if (!rows.length) return <p className="small muted">Nobody.</p>
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th className="num" title={`Overall pick number in the ${pickLabel} draft`}>#</th>
            <th>Player</th>
            <th>Club</th>
            <th>Drafter</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(p => (
            <tr key={`${p.web_name}-${p.index}`}>
              <td className="num muted">{p.index}</td>
              <td><strong>{p.web_name}</strong></td>
              <td className="muted">{p.team_name}</td>
              <td className="muted">{label(p.short_name)}</td>
              <td className="small muted">{notes[p.status] ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A pick this far ahead of the board's expectation counts as a gamble. */
const REACH = 40
/** Passing over a player ranked this much better counts as value left behind. */
const PASS = 40

/** Best / median / mean / worst consensus rank across a set of picks. */
function rankSpread(ranks) {
  const values = ranks.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
  if (!values.length) return null
  const middle = values.length >> 1
  const median = values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2
  return {
    best: values[0],
    median: Math.round(median),
    mean: Math.round(values.reduce((a, b) => a + b, 0) / values.length),
    worst: values[values.length - 1],
  }
}

/**
 * Typical consensus rank at each pick slot, as a rolling median over the season's
 * picks. Fitted across both leagues so each slot has more than a single sample.
 */
function fitBoardCurve(picks) {
  const byIndex = new Map()
  for (const p of picks) {
    if (p.draft_rank == null) continue
    if (!byIndex.has(p.index)) byIndex.set(p.index, [])
    byIndex.get(p.index).push(p.draft_rank)
  }
  const indices = [...byIndex.keys()].sort((a, b) => a - b)
  if (!indices.length) return () => 0

  const window = 4
  const fitted = new Map()
  indices.forEach((index, i) => {
    const pool = indices
      .slice(Math.max(0, i - window), i + window + 1)
      .flatMap(ix => byIndex.get(ix))
      .sort((a, b) => a - b)
    fitted.set(index, pool[pool.length >> 1])
  })

  const last = fitted.get(indices[indices.length - 1])
  return index => fitted.get(index) ?? last
}
