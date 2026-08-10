import { useMemo } from 'react'
import { useTables } from '../lib/data.js'
import { headToHead } from '../lib/h2h.js'
import { fullName, leagueName } from '../lib/names.js'
import {
  Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead, LeagueToggle,
} from '../components/ui.jsx'

const ORDINALS = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th']

const asPct = (value, digits = 1) =>
  value == null ? '–' : `${(value * 100).toFixed(digits)}%`

/** Probability -> heat step. Stops short of --heat-6 so the label stays legible. */
function heat(share) {
  if (!share) return 'var(--heat-0)'
  if (share < 0.05) return 'var(--heat-1)'
  if (share < 0.15) return 'var(--heat-2)'
  if (share < 0.25) return 'var(--heat-3)'
  if (share < 0.40) return 'var(--heat-4)'
  return 'var(--heat-5)'
}

/**
 * "What if it had been head to head?"
 *
 * Pairs the drafters up each gameweek, awards 3/1/0 on the week's score and
 * re-ranks the league on those points — across every fair fixture rotation
 * there is. See lib/h2h.js for why that is exhaustive rather than sampled.
 *
 * Deep-linked as #/<season>/h2h.
 */
export default function HeadToHead({ season, meta, league, setLeague }) {
  const { data, loading, error } = useTables(season, ['league_table'])

  const results = useMemo(() => {
    if (!data?.league_table) return null
    return Object.fromEntries(meta.leagues.map(l => {
      const rows = data.league_table
        .filter(r => r.league === l.code)
        .sort((a, b) => a.rank - b.rank)
      const usable = rows.length > 0 && rows.every(r => Array.isArray(r.points_by_gameweek))
      return [l.code, usable ? headToHead({
        drafters: rows.map(r => r.short_name),
        scores: rows.map(r => r.points_by_gameweek),
        totals: rows.map(r => r.total),
        promoted: l.promoted ?? 0,
        relegated: l.relegated ?? 0,
      }) : null]
    }))
  }, [data, meta])

  // Promotion and relegation are decided in separate leagues on independent
  // schedules, so the chance next season's line-up is untouched is the product.
  const composition = useMemo(() => {
    if (!results) return null
    const parts = meta.leagues.map(l => {
      const r = results[l.code]
      if (!r) return null
      const changed = r.relegatedChanged ?? r.promotedChanged
      return changed == null ? null : 1 - changed
    })
    return parts.every(p => p != null) ? parts.reduce((a, b) => a * b, 1) : null
  }, [results, meta])

  if (error) return <div className="notice">Couldn&apos;t load the league table: {String(error.message)}</div>
  if (loading || !results) return <Loading what="head-to-head schedules" />

  const config = meta.leagues.find(l => l.code === league)
  const result = results[league]
  const toggle = <LeagueToggle meta={meta} league={league} setLeague={setLeague} />

  if (!result) {
    return (
      <Section title="Head to head" note="what if each gameweek had been a fixture?" aside={toggle}>
        <Unavailable
          what="The head-to-head re-run" season={meta.label}
          reason={
            (config?.size ?? 0) % 2 === 1
              ? `${leagueName(meta, league)} had ${config.size} drafters that season, and an odd league can't be paired off without giving somebody a bye each week — which would need a rule this league has never had to agree on.`
              : 'That season\'s league table has no per-gameweek scores to re-run.'
          }
        />
      </Section>
    )
  }

  const outcome = (config?.relegated ?? 0) > 0
    ? { key: 'relegated', label: 'Relegated', changed: result.relegatedChanged, noun: 'relegated pair' }
    : (config?.promoted ?? 0) > 0
      ? { key: 'promoted', label: 'Promoted', changed: result.promotedChanged, noun: 'promoted pair' }
      : null

  return (
    <>
      <Section
        title="Head to head"
        note="what if each gameweek had been a fixture, not a points total?"
        aside={toggle}
      >
        <StatRow>
          <Stat label="Schedules" value={result.total.toLocaleString()}
                sub="every fair rotation, not a sample" />
          <Stat label="Different champion" value={asPct(result.championChanged)}
                sub={`${fullName(meta, result.drafters[0].shortName)} keeps it otherwise`} />
          {outcome && (
            <Stat label={`Different ${outcome.noun}`} value={asPct(outcome.changed)}
                  sub={`${leagueName(meta, league)}, ${outcome.label.toLowerCase()} on H2H points`} />
          )}
          {composition != null && (
            <Stat label="Line-up unchanged" value={asPct(composition)}
                  sub="both leagues, next season's Premiership" />
          )}
        </StatRow>
      </Section>

      <Section
        title="Where everyone finishes"
        note={`Share of the ${result.total.toLocaleString()} schedules ending in each position. The ringed cell is where they actually finished on points.`}
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Drafter</th>
                {ORDINALS.slice(0, result.drafters.length).map(o => <th key={o}>{o}</th>)}
                {outcome && <th>{outcome.label}</th>}
              </tr>
            </thead>
            <tbody>
              {result.drafters.map(d => (
                <tr key={d.shortName}>
                  <td title={fullName(meta, d.shortName)}>{d.shortName}</td>
                  {d.histogram.map((share, pos) => (
                    <td
                      key={pos}
                      className={`num h2h-cell${share >= 0.40 ? ' hot' : ''}${pos === d.actualPosition ? ' actual' : ''}`}
                      style={{ background: heat(share) }}
                      title={`${fullName(meta, d.shortName)} finishes ${ORDINALS[pos]} in ${asPct(share)} of schedules`}
                    >
                      {share ? (share * 100).toFixed(1) : '·'}
                    </td>
                  ))}
                  {outcome && (
                    <td className={`num${d[outcome.key] >= 0.5 ? ' h2h-likely' : ''}`}>
                      {asPct(d[outcome.key])}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="legend">
          Ringed cell = actual finish on total points. Shading is the share of schedules;{' '}
          {outcome && <>the {outcome.label.toLowerCase()} column is emphasised when it&apos;s more likely than not. </>}
          Scores are held fixed, so this is the same performances scored a different way — not a
          guess at how people would have played chasing weekly wins.
        </p>
      </Section>

      <Collapsible title="How far each season could have swung"
                   summary="best and worst possible H2H points">
        <SubHead note={`Out of a possible ${result.maxPoints}. The spread is pure fixture ordering — the underlying scores never change.`}>
          Points range
        </SubHead>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Drafter</th><th>Worst</th><th>Best</th><th>Swing</th><th>Finish range</th>
              </tr>
            </thead>
            <tbody>
              {result.drafters.map(d => (
                <tr key={d.shortName}>
                  <td title={fullName(meta, d.shortName)}>{d.shortName}</td>
                  <td className="num">{d.worstPoints}</td>
                  <td className="num">{d.bestPoints}</td>
                  <td className="num">{d.bestPoints - d.worstPoints}</td>
                  <td className="num">
                    {d.bestPosition === d.worstPosition
                      ? ORDINALS[d.bestPosition]
                      : `${ORDINALS[d.bestPosition]}–${ORDINALS[d.worstPosition]}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>

      <Collapsible title="How this works" summary="every schedule, not a simulation">
        <p className="small">
          Each gameweek the {result.drafters.length} drafters are paired into{' '}
          {result.drafters.length / 2} fixtures and the higher score takes 3 points, a tie 1 each.
          A fair rotation plays everyone once over {result.rounds} weeks, then repeats. There are
          only {result.matchings} ways to pair {result.drafters.length} drafters in a single week
          and <strong>{result.total.toLocaleString()}</strong> fair rotations in total, so every
          one is run — these are exact percentages rather than estimates from a simulation.
        </p>
        <p className="small">
          {result.weeks} gameweeks don&apos;t divide into {result.rounds}-week cycles, so the last
          cycle is cut short: {result.pairsMeetingMore} of the {result.pairsTotal} pairings meet{' '}
          {result.meetMore} times and the other {result.pairsTotal - result.pairsMeetingMore} meet{' '}
          {result.meetLess}. Everyone still plays {result.weeks} matches — but <em>who</em> you face
          the extra time depends entirely on the running order, and that is the whole reason the
          table moves at all.
        </p>
        <p className="small muted">
          Level teams are separated on total points scored, the same tiebreak FPL&apos;s own
          head-to-head leagues use.
        </p>
      </Collapsible>
    </>
  )
}
