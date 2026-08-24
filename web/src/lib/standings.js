/**
 * The official table for a league played as weekly fixtures.
 *
 * Folded in the browser from `h2h_matches` rather than read from `h2h_table`,
 * because the gameweek view can be pointed at any week and the shipped table is
 * only ever season-to-date. Same rule and same inputs as the pipeline's version,
 * so at the latest gameweek the two agree by construction.
 *
 * A match that has started but not finished still counts — the site is near-live
 * — and `provisional` says so, because until the last bonus point lands the
 * official table has not moved.
 */
const WIN = 3
const DRAW = 1

function blank(shortName) {
  return {
    shortName, played: 0, won: 0, drawn: 0, lost: 0,
    pointsFor: 0, pointsAgainst: 0, points: 0, provisional: false, form: [],
  }
}

function fold(matches, drafters, upto) {
  const rows = new Map(drafters.map(d => [d, blank(d)]))

  for (const m of matches) {
    if (!m.started || m.gameweek > upto) continue
    for (const [self, other, scored, conceded] of [
      [m.home, m.away, m.home_points, m.away_points],
      [m.away, m.home, m.away_points, m.home_points],
    ]) {
      const row = rows.get(self)
      if (!row) continue
      const result = scored > conceded ? 'W' : scored < conceded ? 'L' : 'D'
      row.played += 1
      row.pointsFor += scored
      row.pointsAgainst += conceded
      row.points += result === 'W' ? WIN : result === 'D' ? DRAW : 0
      row[result === 'W' ? 'won' : result === 'L' ? 'lost' : 'drawn'] += 1
      if (!m.finished) row.provisional = true
      row.form.push({ gameweek: m.gameweek, result, opponent: other })
    }
  }
  return [...rows.values()]
}

/** Points, then points scored — FPL's own tie-break. Ties share the better rank. */
function ranked(rows) {
  const key = r => [r.points, r.pointsFor]
  const beats = (a, b) => a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])
  return rows
    .map(r => ({ ...r, rank: rows.filter(o => beats(key(o), key(r))).length + 1 }))
    .sort((a, b) => a.rank - b.rank)
}

export function headToHeadTable(matches, drafters, upto) {
  const now = ranked(fold(matches, drafters, upto))
  // Last week's positions, for the movement arrows. Zero before a ball is kicked,
  // which rankMove already reads as "no previous position".
  const before = upto > 1
    ? Object.fromEntries(ranked(fold(matches, drafters, upto - 1)).map(r => [r.shortName, r.rank]))
    : {}
  return now.map(r => ({
    ...r,
    lastRank: before[r.shortName] ?? 0,
    form: r.form.slice(-5).map(f => f.result),
  }))
}

/** The fixtures for one gameweek, in table order. */
export function fixturesFor(matches, gameweek) {
  return matches.filter(m => m.gameweek === gameweek)
}
