/**
 * What the room's taste changed since last year's draft — by player and by club.
 *
 * Draft night tells you where the league's collective opinion landed. Comparing it
 * with the previous draft tells you where that opinion *moved*, which is usually the
 * more interesting story: a club going from two players drafted to nine is the room
 * repricing a whole squad.
 *
 * Two joins, and one of them is a trap:
 *
 *   clubs   joined on the three-letter club code, which is stable across seasons.
 *   players joined on `web_name`, NOT on `element`.
 *
 * FPL reassigns element ids every season — of the 19 ids present in both the 2425
 * and 2526 drafts, zero refer to the same footballer (id 16 is Rice in 2425 and
 * Saka in 2526). Joining on it produces a table that looks entirely plausible and
 * is entirely wrong. web_name is the only stable identifier the pick tables carry.
 *
 * The residual risk with names is a genuine collision — two different players
 * sharing a web_name across seasons. Position isn't a safe tie-breaker (players get
 * reclassified) and neither is club (they transfer), so among the ~100 drafted names
 * a season this is accepted as the lesser error.
 *
 * Everything is computed per league, because that is the room whose taste changed.
 * Note that a league's membership itself changes: two drafters are promoted and two
 * relegated each season, so "the Premiership cooled on Arsenal" is a claim about the
 * league, not about the same six people.
 */

/** '2627' -> '2526'. Null if the id isn't the two-year form. */
export function previousSeason(season) {
  const text = String(season ?? '')
  if (!/^\d{4}$/.test(text)) return null
  const start = Number(text.slice(0, 2))
  if (start <= 0) return null
  const pad = n => String(n).padStart(2, '0')
  return `${pad(start - 1)}${pad(start)}`
}

const byClub = picks => {
  const out = new Map()
  for (const pick of picks) {
    const club = pick.team_name
    if (!club) continue
    const entry = out.get(club) ?? { club, n: 0, earliest: null }
    entry.n += 1
    if (entry.earliest == null || pick.index < entry.earliest) entry.earliest = pick.index
    out.set(club, entry)
  }
  return out
}

/**
 * Draft capital by club, this year against last.
 *
 * `clubs` / `priorClubs` are the seasons' team lists. They separate "the room
 * ignored them" from "they weren't in the division" — without that a promoted club
 * reads as a nine-player swing out of nowhere.
 */
export function clubMarket(picks, priorPicks, { clubs, priorClubs } = {}) {
  const now = byClub(picks)
  const before = byClub(priorPicks ?? [])
  const names = new Set([...now.keys(), ...before.keys()])

  return [...names].map(club => {
    const a = now.get(club)
    const b = before.get(club)
    const n = a?.n ?? 0
    const priorN = b?.n ?? 0
    let status = null
    if (priorClubs && !priorClubs.has(club)) status = 'new_to_division'
    else if (clubs && !clubs.has(club)) status = 'left_division'
    return {
      club,
      n,
      priorN,
      delta: n - priorN,
      earliest: a?.earliest ?? null,
      priorEarliest: b?.earliest ?? null,
      status,
    }
  }).sort((x, y) => y.delta - x.delta || y.n - x.n || x.club.localeCompare(y.club))
}

/**
 * Player-level movement between the two drafts.
 *
 * `move` is positive when a player went earlier this year than last — the room
 * warmed to him. Players who appear in only one of the two drafts are split out
 * rather than given a fake delta, and each carries why: taken by the other league,
 * or new to the division, or simply not drafted.
 */
export function playerMarket(picks, priorPicks, {
  priorAllPicks = [], allPicks = [], priorClubs,
} = {}) {
  const key = pick => pick.web_name
  const before = new Map((priorPicks ?? []).map(p => [key(p), p]))
  const now = new Map(picks.map(p => [key(p), p]))
  const priorAnywhere = new Set(priorAllPicks.map(key))
  const nowAnywhere = new Set(allPicks.map(key))

  const moved = []
  const arrivals = []
  for (const pick of picks) {
    const was = before.get(key(pick))
    if (was) {
      moved.push({
        ...pick,
        priorIndex: was.index,
        priorDrafter: was.short_name,
        move: was.index - pick.index,
      })
      continue
    }
    arrivals.push({
      ...pick,
      status: priorAnywhere.has(key(pick)) ? 'other_league'
        : (priorClubs && !priorClubs.has(pick.team_name)) ? 'new_to_division'
          : 'undrafted_last_year',
    })
  }

  const departures = (priorPicks ?? [])
    .filter(pick => !now.has(key(pick)))
    .map(pick => ({
      ...pick,
      status: nowAnywhere.has(key(pick)) ? 'other_league' : 'undrafted_this_year',
    }))
    .sort((a, b) => a.index - b.index)

  return {
    hotter: moved.filter(p => p.move > 0).sort((a, b) => b.move - a.move),
    cooler: moved.filter(p => p.move < 0).sort((a, b) => a.move - b.move),
    held: moved.filter(p => p.move === 0),
    arrivals: arrivals.sort((a, b) => a.index - b.index),
    departures,
    matched: moved.length,
  }
}

export const clubSet = teams => new Set(
  (teams ?? []).map(t => t.team ?? t.team_name).filter(Boolean),
)
