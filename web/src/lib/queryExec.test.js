/**
 * The query-spec executor, on a tiny hand-made season — every expected row can
 * be worked out by hand. Nothing here touches the network: loadRows serves the
 * fixtures below.
 */

import { describe, it, expect } from 'vitest'
import { runSpec, personaliseHeadline, QueryError } from './queryExec.js'

// The offering drafter RECEIVES player_in and gives up player_out; the other
// side therefore gives player_in and receives player_out (see data contract).
// Story: MN trades for Haaland in GW4, gives him up again in GW9.
const TRADES = [
  { league: 'DL', gameweek: 4, offered_by: 'MN', received_by: 'TS',
    player_in: 'Haaland', player_out: 'Watkins', net_points: 12, state: 'p' },
  { league: 'DL', gameweek: 9, offered_by: 'TS', received_by: 'MN',
    player_in: 'Haaland', player_out: 'Saka', net_points: -4, state: 'p' },
  { league: 'DL', gameweek: 11, offered_by: 'MN', received_by: 'CJ',
    player_in: 'Rogers', player_out: 'Palmer', net_points: 0, state: 'o' },
]

const WEEKLY_SUMMARY = [
  { gameweek: 1, short_name: 'MN', place: 1, total_points: 9, web_name: 'Salah' },
  { gameweek: 1, short_name: 'MN', place: 12, total_points: 6, web_name: 'Wood' },
  { gameweek: 1, short_name: 'TS', place: 12, total_points: 2, web_name: 'Muñoz' },
  { gameweek: 2, short_name: 'MN', place: 13, total_points: 5, web_name: 'Wood' },
  { gameweek: 2, short_name: 'TS', place: 12, total_points: 8, web_name: 'Gyökeres' },
]

const TABLES = { trades: TRADES, weekly_summary: WEEKLY_SUMMARY }
const loadRows = name => Promise.resolve(TABLES[name])

const spec = overrides => ({
  answerable: true, reason: null, table: 'trades', seasons: null, where: [],
  group_by: null, aggregate: null, select: null, sort: [], limit: 50,
  headline: null, ...overrides,
})

describe('filtering', () => {
  it('ORs the groups and ANDs within them — the trade-direction case', async () => {
    const { rows } = await runSpec(spec({
      where: [
        { all: [{ col: 'offered_by', op: 'eq', value: 'MN' },
                { col: 'player_out', op: 'contains', value: 'haaland' }] },
        { all: [{ col: 'received_by', op: 'eq', value: 'MN' },
                { col: 'player_in', op: 'contains', value: 'haaland' }] },
      ],
    }), loadRows)
    // GW9: TS offered Saka for Haaland, so MN (received_by) gave Haaland up.
    expect(rows.map(r => r.gameweek)).toEqual([9])
  })

  it('compares numbers numerically and strings case-insensitively', async () => {
    const gte = await runSpec(spec({ where: [{ all: [{ col: 'gameweek', op: 'gte', value: 9 }] }] }), loadRows)
    expect(gte.rows.map(r => r.gameweek)).toEqual([9, 11])
    const eq = await runSpec(spec({ where: [{ all: [{ col: 'offered_by', op: 'eq', value: 'mn' }] }] }), loadRows)
    expect(eq.rows.map(r => r.gameweek)).toEqual([4, 11])
  })

  it('supports in and neq', async () => {
    const result = await runSpec(spec({
      where: [{ all: [{ col: 'gameweek', op: 'in', value: [4, 11] },
                      { col: 'state', op: 'neq', value: 'o' }] }],
    }), loadRows)
    expect(result.rows.map(r => r.gameweek)).toEqual([4])
  })
})

describe('grouping and aggregation', () => {
  it('answers "most points left on the bench"', async () => {
    const { rows, headline } = await runSpec(spec({
      table: 'weekly_summary',
      where: [{ all: [{ col: 'place', op: 'gte', value: 12 }] }],
      group_by: ['short_name'],
      aggregate: [{ fn: 'sum', col: 'total_points', as: 'bench_points' }],
      sort: [{ col: 'bench_points', dir: 'desc' }],
      limit: 1,
      headline: '{short_name} has left {bench_points} points on the bench',
    }), loadRows)
    expect(rows).toEqual([{ short_name: 'MN', bench_points: 11 }])  // 6 + 5
    expect(headline).toBe('MN has left 11 points on the bench')
  })

  it('count with a null column counts rows', async () => {
    const { rows } = await runSpec(spec({
      group_by: ['offered_by'],
      aggregate: [{ fn: 'count', col: null, as: 'trades_made' }],
      sort: [{ col: 'trades_made', dir: 'desc' }, { col: 'offered_by', dir: 'asc' }],
    }), loadRows)
    expect(rows).toEqual([
      { offered_by: 'MN', trades_made: 2 },
      { offered_by: 'TS', trades_made: 1 },
    ])
  })
})

describe('shaping', () => {
  it('sorts, limits and projects', async () => {
    const { rows } = await runSpec(spec({
      sort: [{ col: 'net_points', dir: 'desc' }],
      limit: 2,
      select: ['player_in', 'net_points'],
    }), loadRows)
    expect(rows).toEqual([
      { player_in: 'Haaland', net_points: 12 },
      { player_in: 'Rogers', net_points: 0 },
    ])
  })

  it('caps the limit at 50 and tolerates unknown select columns', async () => {
    const { rows } = await runSpec(spec({ limit: 9999, select: ['player_in', 'nonsense'] }), loadRows)
    expect(rows).toHaveLength(3)
    expect(Object.keys(rows[0])).toEqual(['player_in'])
  })

  it('drops a headline whose placeholder is missing from the result', async () => {
    const { headline } = await runSpec(spec({
      limit: 1, headline: 'Traded for {no_such_column}',
    }), loadRows)
    expect(headline).toBeNull()
  })
})

describe('cross-season execution', () => {
  // Two tiny seasons: Salah drafted in both, Haaland only in the newer one,
  // and the older season has no trades table at all (like the 2425 archive).
  const BY_SEASON = {
    2425: {
      draft_picks: [
        { short_name: 'MN', web_name: 'Salah' },
        { short_name: 'TS', web_name: 'Son' },
      ],
    },
    2526: {
      draft_picks: [
        { short_name: 'MN', web_name: 'Salah' },
        { short_name: 'TS', web_name: 'Haaland' },
      ],
      trades: TRADES,
    },
  }
  const loadBySeason = (name, season) => Promise.resolve(BY_SEASON[season]?.[name] ?? null)
  const seasons = [{ id: '2425', label: '2024/25' }, { id: '2526', label: '2025/26' }]

  it('unions the seasons, tags rows, and groups across them by name', async () => {
    const { rows, headline } = await runSpec(spec({
      table: 'draft_picks', seasons: 'all',
      group_by: ['web_name'],
      aggregate: [{ fn: 'count', col: null, as: 'times_drafted' }],
      sort: [{ col: 'times_drafted', dir: 'desc' }, { col: 'web_name', dir: 'asc' }],
      headline: '{web_name} has been drafted {times_drafted} times',
    }), loadBySeason, { seasons })
    expect(rows).toEqual([
      { web_name: 'Salah', times_drafted: 2 },
      { web_name: 'Haaland', times_drafted: 1 },
      { web_name: 'Son', times_drafted: 1 },
    ])
    expect(headline).toBe('Salah has been drafted 2 times')
  })

  it('exposes season and season_label as columns', async () => {
    const { rows } = await runSpec(spec({
      table: 'draft_picks', seasons: 'all',
      where: [{ all: [{ col: 'web_name', op: 'eq', value: 'Haaland' }] }],
      select: ['web_name', 'season', 'season_label'],
    }), loadBySeason, { seasons })
    expect(rows).toEqual([{ web_name: 'Haaland', season: '2526', season_label: '2025/26' }])
  })

  it('skips a season that lacks the table, and only errors when all do', async () => {
    const some = await runSpec(spec({ table: 'trades', seasons: 'all' }), loadBySeason, { seasons })
    expect(some.rows).toHaveLength(3)
    expect(some.rows.every(r => r.season === '2526')).toBe(true)

    await expect(runSpec(spec({ table: 'players', seasons: 'all' }), loadBySeason, { seasons }))
      .rejects.toBeInstanceOf(QueryError)
  })

  it('runs only the listed seasons, and refuses unknown ones', async () => {
    const { rows } = await runSpec(spec({
      table: 'draft_picks', seasons: ['2425'],
    }), loadBySeason, { seasons })
    expect(rows.every(r => r.season === '2425')).toBe(true)
    expect(rows).toHaveLength(2)

    await expect(runSpec(spec({ table: 'draft_picks', seasons: ['1999'] }), loadBySeason, { seasons }))
      .rejects.toBeInstanceOf(QueryError)
  })

  it('tolerates a column that only newer seasons carry', async () => {
    const withExtra = (name, season) => Promise.resolve(
      season === '2526' ? [{ web_name: 'Salah', round: 1 }] : [{ web_name: 'Salah' }])
    const { rows } = await runSpec(spec({
      table: 'draft_picks', seasons: 'all',
      where: [{ all: [{ col: 'round', op: 'eq', value: 1 }] }],
    }), withExtra, { seasons })
    // The 2425 row has no round, so only the 2526 row matches — no column error.
    expect(rows).toEqual([{ web_name: 'Salah', round: 1, season: '2526', season_label: '2025/26' }])
  })

  it('falls back to single-season when the caller has no season list', async () => {
    const { rows } = await runSpec(
      spec({ seasons: 'all' }),
      name => Promise.resolve(TABLES[name]),
    )
    expect(rows).toHaveLength(3)
    expect(rows[0].season).toBeUndefined()
  })
})

describe('personaliseHeadline', () => {
  const drafters = [
    { short_name: 'MN', name: 'Mike Nelson' },
    { short_name: 'TS', name: 'Tom Shiel' },
  ]

  it('swaps whole-word short names for full names', () => {
    expect(personaliseHeadline('MN let Watkins go, TS pounced', drafters))
      .toBe('Mike Nelson let Watkins go, Tom Shiel pounced')
  })

  it('leaves initials buried in other words alone', () => {
    expect(personaliseHeadline('TSitsipas and the MNightly show', drafters))
      .toBe('TSitsipas and the MNightly show')
    expect(personaliseHeadline(null, drafters)).toBeNull()
  })
})

describe('refusals', () => {
  it('surfaces the model saying no, with its reason', async () => {
    await expect(runSpec(spec({ answerable: false, reason: 'No fixture data here.' }), loadRows))
      .rejects.toThrow('No fixture data here.')
  })

  it('refuses unknown tables, columns and operators as typed errors', async () => {
    await expect(runSpec(spec({ table: 'secrets' }), loadRows)).rejects.toBeInstanceOf(QueryError)
    await expect(runSpec(spec({ where: [{ all: [{ col: 'nope', op: 'eq', value: 1 }] }] }), loadRows))
      .rejects.toBeInstanceOf(QueryError)
    await expect(runSpec(spec({ where: [{ all: [{ col: 'gameweek', op: 'regex', value: '.*' }] }] }), loadRows))
      .rejects.toBeInstanceOf(QueryError)
  })
})
