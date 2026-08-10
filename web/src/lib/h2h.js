/**
 * Head-to-head counterfactual.
 *
 * Re-scores a finished season as if every gameweek had been a paired fixture
 * (3 win / 1 draw / 0 loss) rather than a straight points total, then asks how
 * often the final table would have differed.
 *
 * This lives in the frontend rather than the pipeline because the search space
 * is tiny. A fair schedule is a 1-factorization of the complete graph on the
 * drafters — n-1 rounds in which everyone plays everyone exactly once — and for
 * six drafters there are only 720 ordered ones. Every schedule is enumerated,
 * so these are exact probabilities, not a sample. The whole thing is ~82k
 * integer comparisons per league, which is cheaper than fetching a JSON file.
 *
 * Gameweek scores are held FIXED. This is "the same performances under a
 * different scoring system", not a simulation of how people would have played
 * had they been chasing weekly wins.
 */

/**
 * Refuse to enumerate past this. Six drafters gives 720; eight would give tens
 * of millions, which is a hang rather than a slow render.
 */
export const MAX_SCHEDULES = 5000
const MAX_DRAFTERS = 8

/** Every way to split `pool` into disjoint pairs. */
function matchingsOf(pool) {
  if (pool.length === 0) return [[]]
  const [first, ...rest] = pool
  const out = []
  for (let i = 0; i < rest.length; i++) {
    const remaining = rest.filter((_, j) => j !== i)
    for (const sub of matchingsOf(remaining)) out.push([[first, rest[i]], ...sub])
  }
  return out
}

/** Pair -> bit position, so a matching can be tested for edge overlap with `&`. */
function edgeBits(n) {
  const bit = new Map()
  let k = 0
  for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) bit.set(`${a}|${b}`, k++)
  return bit
}

/**
 * All ordered 1-factorizations for `n` drafters: every fair season-long rotation,
 * including which round falls first. Returns null when n is odd (no pairing
 * exists without a bye) or the space is too big to enumerate.
 */
export function enumerateSchedules(n, cap = MAX_SCHEDULES) {
  if (n < 2 || n % 2 !== 0 || n > MAX_DRAFTERS) return null

  const rounds = n - 1
  const matchings = matchingsOf([...Array(n).keys()])
  const bit = edgeBits(n)
  const masks = matchings.map(m => m.reduce((acc, [a, b]) => acc | (1 << bit.get(`${a}|${b}`)), 0))

  const schedules = []
  const chosen = []
  let overflowed = false

  const extend = used => {
    if (overflowed) return
    if (chosen.length === rounds) {
      if (schedules.length >= cap) { overflowed = true; return }
      schedules.push(chosen.slice())
      return
    }
    for (let i = 0; i < matchings.length; i++) {
      if (used & masks[i]) continue
      chosen.push(i)
      extend(used | masks[i])
      chosen.pop()
      if (overflowed) return
    }
  }
  extend(0)

  return overflowed ? null : { matchings, schedules, rounds }
}

/**
 * Run every schedule and tally the outcomes.
 *
 * `drafters` must be in actual finishing order, so drafter i's real position is
 * i. `scores[i][g]` is the realised gameweek score (post auto-subs) and
 * `totals[i]` the season total, used as the table tiebreak exactly as FPL's own
 * head-to-head leagues do.
 */
export function headToHead({ drafters, scores, totals, promoted = 0, relegated = 0, cap = MAX_SCHEDULES }) {
  const n = drafters.length
  const enumerated = enumerateSchedules(n, cap)
  if (!enumerated || n === 0) return null

  const { matchings, schedules, rounds } = enumerated
  const weeks = scores[0]?.length ?? 0
  if (!weeks) return null

  // points[matching][gameweek][drafter] — every schedule is then just a lookup
  // per week, which is what keeps the whole enumeration cheap.
  const points = matchings.map(m =>
    Array.from({ length: weeks }, (_, g) => {
      const row = new Array(n).fill(0)
      for (const [a, b] of m) {
        const sa = scores[a][g], sb = scores[b][g]
        if (sa > sb) row[a] = 3
        else if (sb > sa) row[b] = 3
        else { row[a] = 1; row[b] = 1 }
      }
      return row
    }))

  const histogram = Array.from({ length: n }, () => new Array(n).fill(0))
  const best = new Array(n).fill(-Infinity)
  const worst = new Array(n).fill(Infinity)
  const promotedCount = new Array(n).fill(0)
  const relegatedCount = new Array(n).fill(0)

  let championChanged = 0
  let promotedChanged = 0
  let relegatedChanged = 0

  const order = [...Array(n).keys()]

  for (const schedule of schedules) {
    const tally = new Array(n).fill(0)
    for (let g = 0; g < weeks; g++) {
      const row = points[schedule[g % rounds]][g]
      for (let i = 0; i < n; i++) tally[i] += row[i]
    }

    // Head-to-head points, then season total, then actual rank so the ordering
    // is fully determined and never leans on sort stability.
    const table = order.slice().sort((x, y) => (tally[y] - tally[x]) || (totals[y] - totals[x]) || (x - y))

    for (let pos = 0; pos < n; pos++) histogram[table[pos]][pos]++
    for (let i = 0; i < n; i++) {
      if (tally[i] > best[i]) best[i] = tally[i]
      if (tally[i] < worst[i]) worst[i] = tally[i]
    }

    if (table[0] !== 0) championChanged++
    if (promoted > 0) {
      const up = table.slice(0, promoted)
      up.forEach(i => promotedCount[i]++)
      if (!up.every(i => i < promoted)) promotedChanged++
    }
    if (relegated > 0) {
      const down = table.slice(n - relegated)
      down.forEach(i => relegatedCount[i]++)
      if (!down.every(i => i >= n - relegated)) relegatedChanged++
    }
  }

  const total = schedules.length
  const share = count => count / total

  // 38 gameweeks over 5 rounds doesn't divide evenly, so the last cycle is
  // truncated and some pairs meet one more time than others. Which pairs those
  // are is decided purely by round order — it is the whole source of spread.
  const extraRounds = weeks % rounds

  return {
    total,
    rounds,
    weeks,
    matchings: matchings.length,
    cycles: Math.floor(weeks / rounds),
    extraRounds,
    pairsMeetingMore: (extraRounds * n) / 2,
    pairsTotal: (n * (n - 1)) / 2,
    meetMore: Math.ceil(weeks / rounds),
    meetLess: Math.floor(weeks / rounds),
    maxPoints: weeks * 3,
    drafters: drafters.map((d, i) => ({
      shortName: d,
      actualPosition: i,
      histogram: histogram[i].map(share),
      modalPosition: histogram[i].indexOf(Math.max(...histogram[i])),
      bestPoints: best[i],
      worstPoints: worst[i],
      bestPosition: histogram[i].findIndex(c => c > 0),
      worstPosition: histogram[i].length - 1 - [...histogram[i]].reverse().findIndex(c => c > 0),
      promoted: promoted > 0 ? share(promotedCount[i]) : null,
      relegated: relegated > 0 ? share(relegatedCount[i]) : null,
    })),
    championChanged: share(championChanged),
    promotedChanged: promoted > 0 ? share(promotedChanged) : null,
    relegatedChanged: relegated > 0 ? share(relegatedChanged) : null,
  }
}
