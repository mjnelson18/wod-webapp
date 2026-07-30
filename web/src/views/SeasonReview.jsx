import { useAsync, loadTable } from '../lib/data.js'
import { loadReview, renderReview } from '../lib/review.jsx'
import { Section, Loading, Collapsible, Stat, StatRow } from '../components/ui.jsx'

/**
 * The written season review: one page, both leagues, told in order.
 *
 * Two layers on purpose. The honours strip and the numbers below are read from
 * `season_review_facts.json`, so they always match the data. The prose between
 * them is written by hand once the season is done — it's the one part of the
 * site that isn't generated, and it isn't regenerated on the cron either.
 */
export default function SeasonReview({ season, meta }) {
  const { data, loading, error } = useAsync(
    () => Promise.all([
      loadTable(season, 'season_review_facts'),
      loadReview(season),
    ]).then(([facts, prose]) => ({ facts, prose })),
    [season],
  )

  if (loading) return <Loading what="the season review" />
  if (error) {
    return (
      <div className="notice">
        <strong>Couldn&apos;t load the review.</strong> {String(error.message ?? error)}
      </div>
    )
  }

  const { facts, prose } = data
  const incomplete = facts && !facts.complete

  return (
    <>
      <Section
        title={`${meta.label} in review`}
        note={incomplete
          ? `Written up at the end of the season — ${facts.current_gameweek} gameweeks played so far.`
          : 'How the season actually went, both leagues, in order.'}
      >
        <Honours facts={facts} />
      </Section>

      {prose
        ? <Section><article className="review">{renderReview(prose, season)}</article></Section>
        : (
          <div className="notice">
            <strong>No write-up yet.</strong> The numbers above are generated; the review
            itself gets written once the season finishes.
          </div>
        )}

      {facts && (
        <Section title="The numbers behind it" note="Everything the review was written from.">
          {facts.leagues.map(league => <LeagueFacts key={league.code} league={league} />)}
          <CrossLeagueFacts cross={facts.cross_league} leagues={facts.leagues} />
        </Section>
      )}
    </>
  )
}

/** Who won what — read straight from the facts, so it can't go stale. */
function Honours({ facts }) {
  if (!facts?.leagues?.length) return null
  return (
    <>
      {facts.leagues.map(league => (
        <div key={league.code} className="honours">
          <h3>{league.name}</h3>
          <StatRow>
            <Stat
              label="Champion"
              value={who(league.champion)}
              sub={league.title_margin != null
                ? `${league.champion.total} pts · by ${league.title_margin}`
                : `${league.champion.total} pts`}
            />
            {league.promoted?.length > 0 && (
              <Stat label="Promoted" value={league.promoted.map(who).join(', ')} />
            )}
            {league.relegated?.length > 0 && (
              <Stat label="Relegated" value={league.relegated.map(who).join(', ')} />
            )}
            <Stat label="Last" value={who(league.wooden_spoon)}
                  sub={`${league.spread} behind the champion`} />
            {league.extremes?.highest_gameweek && (
              <Stat
                label="Best week"
                value={`${league.extremes.highest_gameweek.points}`}
                sub={`${who(league.extremes.highest_gameweek)} · GW${league.extremes.highest_gameweek.gameweek}`}
              />
            )}
          </StatRow>
        </div>
      ))}
    </>
  )
}

function LeagueFacts({ league }) {
  const { race, extremes, draft, moves, bench } = league
  return (
    <Collapsible title={league.name} summary={`won by ${who(league.champion)}`}>
      <dl className="facts">
        <Fact term="Final table">
          {league.final_table.map(r => `${r.rank}. ${who(r)} ${r.total}`).join(' · ')}
        </Fact>
        {race?.lead_changes != null && (
          <Fact term="The race">
            {race.lead_changes} lead {race.lead_changes === 1 ? 'change' : 'changes'},
            {' '}{race.distinct_leaders.length} different {race.distinct_leaders.length === 1 ? 'leader' : 'leaders'}
            {race.champion_led_unbroken_from
              ? `; ${who(league.champion)} led from GW${race.champion_led_unbroken_from}`
              : ''}
            {race.biggest_deficit_overturned?.points
              ? `, having been ${race.biggest_deficit_overturned.points} behind at GW${race.biggest_deficit_overturned.gameweek}`
              : ''}
          </Fact>
        )}
        {extremes?.highest_gameweek && (
          <Fact term="Best and worst weeks">
            {who(extremes.highest_gameweek)} {extremes.highest_gameweek.points} in GW{extremes.highest_gameweek.gameweek};
            {' '}{who(extremes.lowest_gameweek)} {extremes.lowest_gameweek.points} in GW{extremes.lowest_gameweek.gameweek}
          </Fact>
        )}
        {draft?.best_pick && (
          <Fact term="Draft">
            Best pick {who(draft.best_pick)} — {draft.best_pick.player} at #{draft.best_pick.index},
            {' '}{draft.best_pick.points_realised_by_drafter} pts
            {draft.round_one_bust
              ? `. Round-one dud: ${who(draft.round_one_bust)} took ${draft.round_one_bust.player} at #${draft.round_one_bust.index} for ${draft.round_one_bust.player_total_points}`
              : ''}
          </Fact>
        )}
        {moves?.best_transfer && (
          <Fact term="Transfers">
            Best: {who(moves.best_transfer)} took {moves.best_transfer.player_in} in
            {' '}GW{moves.best_transfer.gameweek} (+{moves.best_transfer.net_points_since})
            {moves.worst_miss
              ? `. Biggest miss: ${who(moves.worst_miss)} was beaten to ${moves.worst_miss.player} in GW${moves.worst_miss.gameweek}, who then scored ${moves.worst_miss.points_since}`
              : ''}
          </Fact>
        )}
        {moves?.best_trade && (
          <Fact term="Trades">
            {moves.trade_count} processed. Best: {moves.best_trade.player_in} for
            {' '}{moves.best_trade.player_out} in GW{moves.best_trade.gameweek}
            {' '}({moves.best_trade.net_points > 0 ? '+' : ''}{moves.best_trade.net_points})
          </Fact>
        )}
        {bench?.worst_week && (
          <Fact term="Left on the bench">
            Worst week {who(bench.worst_week)}, {bench.worst_week.points_lost} in
            {' '}GW{bench.worst_week.gameweek}. Over the season:
            {' '}{bench.season_lost.map(r => `${who(r)} ${r.points_lost}`).join(', ')}
          </Fact>
        )}
      </dl>
    </Collapsible>
  )
}

function CrossLeagueFacts({ cross, leagues }) {
  if (!cross?.record) return null
  const names = Object.fromEntries(leagues.map(l => [l.code, l.name]))
  const record = Object.entries(cross.record)
    .map(([code, wins]) => `${names[code] ?? code} ${wins}`).join(' — ')
  return (
    <Collapsible title="Prem v Conf" summary={record}>
      <dl className="facts">
        <Fact term="Gameweeks won">{record} (mean points per drafter, not totals)</Fact>
        <Fact term="Season average">
          {Object.entries(cross.season_mean_points)
            .map(([code, mean]) => `${names[code] ?? code} ${mean}`).join(' · ')}
        </Fact>
        {cross.champion_crossover?.map(x => (
          <Fact key={x.champion_of} term={`${names[x.champion_of] ?? x.champion_of} champion`}>
            {x.name ?? x.short_name} on {x.total} would have finished
            {' '}{ordinal(x.would_rank)} of {x.of} in the {names[x.would_rank_in] ?? x.would_rank_in}
          </Fact>
        ))}
      </dl>
    </Collapsible>
  )
}

function Fact({ term, children }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </>
  )
}

/** Full name where the season has one; 2425's CSVs only ever had initials. */
function who(person) {
  if (!person) return ''
  if (person.excluded_entry) return 'an excluded entry'
  return person.name || person.short_name
}

function ordinal(n) {
  const suffix = ['th', 'st', 'nd', 'rd'][(n % 100 - 20) % 10] ?? ['th', 'st', 'nd', 'rd'][n] ?? 'th'
  return `${n}${suffix}`
}
