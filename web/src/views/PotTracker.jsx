import { useAsync, loadTableIfPresent } from '../lib/data.js'
import { fullName } from '../lib/names.js'
import { Section, Loading, Unavailable, Stat, StatRow, Collapsible, SubHead } from '../components/ui.jsx'

/**
 * The side pot: £20 buy-in each, then the lowest scorer over each calendar
 * month's gameweeks adds £10. Only a league whose config keeps the rule emits
 * the data (Dunelmliga), so the tab never exists elsewhere — see Header's
 * `when` predicate on the pot_tracker capability.
 *
 * Deep-linked as #/<season>/pot.
 */
export default function PotTracker({ season, meta }) {
  const pot = useAsync(() => loadTableIfPresent(season, 'pot_tracker'), [season])

  if (pot.error) {
    return <div className="notice">Couldn&apos;t load the pot: {String(pot.error.message)}</div>
  }
  if (pot.loading) return <Loading what="the pot" />
  if (!pot.data) {
    return (
      <Section title="Pot Tracker">
        <Unavailable what="The pot" season={meta.label}
                     reason="This season has no pot data." />
      </Section>
    )
  }

  const { rules, drafters, months, pot_total: potTotal, settled_months: settled } = pot.data
  const money = amount => `${rules.currency}${amount}`

  // "Loser if the month ended today": the first month still open that has scores.
  const current = months.find(m => !m.settled && Object.keys(m.points).length > 0)
  const currentLow = current
    ? Object.entries(current.points).reduce((a, [short, pts]) =>
        (a == null || pts < a.pts ? { short, pts } : a), null)
    : null

  const played = months.filter(m => Object.keys(m.points).length > 0)

  return (
    <>
      <Section
        title="Pot Tracker"
        note={`${money(rules.buy_in)} buy-in each · the month's lowest scorer adds ${money(rules.monthly_stake)}`}
      >
        <StatRow>
          <Stat label="The pot" value={money(potTotal)}
                sub={`${drafters.length} buy-ins + ${settled} monthly ${settled === 1 ? 'stake' : 'stakes'}`} />
          <Stat label="Buy-ins" value={money(drafters.length * rules.buy_in)}
                sub={`${drafters.length} × ${money(rules.buy_in)}`} />
          <Stat label="Months settled" value={`${settled}/${months.length}`}
                sub="a month settles once its last gameweek is final" />
          {currentLow && (
            <Stat label="Paying so far" value={fullName(meta, currentLow.short)}
                  sub={`${current.label} · ${currentLow.pts} pts · if the month ended today`} />
          )}
        </StatRow>

        <SubHead note="Fewest FPL points scored across the month's gameweeks pays. A tie is flagged and settled offline — the pot still gains one stake.">
          Month by month
        </SubHead>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th>Month</th><th>GWs</th><th>Pays</th><th>Stake</th><th>Settled</th></tr>
            </thead>
            <tbody>
              {months.map(m => (
                <tr key={m.month}>
                  <td>{m.label}</td>
                  <td className="num">
                    {m.gameweeks.length
                      ? `${m.gameweeks[0]}–${m.gameweeks[m.gameweeks.length - 1]}`
                      : '–'}
                  </td>
                  <td>
                    {m.settled
                      ? m.losers.map(short => fullName(meta, short)).join(' & ')
                        + (m.tied ? ' (tie)' : '')
                      : Object.keys(m.points).length ? 'in play' : '–'}
                  </td>
                  <td className="num">{m.settled ? `−${money(rules.monthly_stake)}` : ''}</td>
                  <td>{m.settled ? '✓' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Collapsible title="Monthly points" summary="who scored what, month by month" open>
        {played.length === 0 ? (
          <p className="muted small">No gameweeks played yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Drafter</th>
                  {played.map(m => <th key={m.month}>{m.label.slice(0, 3)}</th>)}
                </tr>
              </thead>
              <tbody>
                {drafters.map(short => (
                  <tr key={short}>
                    <td>{fullName(meta, short)}</td>
                    {played.map(m => {
                      const value = m.points[short]
                      const values = Object.values(m.points)
                      const isLow = value != null && value === Math.min(...values)
                      return (
                        <td key={m.month} className="num"
                            style={isLow ? { color: 'var(--accent)', fontWeight: 700 } : undefined}>
                          {value ?? ''}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="legend">
          Bold = lowest in that month {`(pays ${money(rules.monthly_stake)} once the month settles)`}.
          Buy-in {money(rules.buy_in)} each; ties split offline.
        </p>
      </Collapsible>
    </>
  )
}
