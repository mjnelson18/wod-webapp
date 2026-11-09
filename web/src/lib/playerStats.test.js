import { describe, it, expect } from 'vitest'
import { acquisition, drafterRecord } from './playerStats.js'

const week = (gameweek, extra = {}) => ({
  league: 'Prem', short_name: 'AC', element: 8, gameweek,
  place: 4, total_points: 6, points_scored: 6, ...extra,
})

describe('acquisition', () => {
  const base = { league: 'Prem', short: 'AC', element: 8, gameweek: 9 }

  it('names the draft pick when the row says he was drafted', () => {
    const row = { in_original_draft: 1, round: 9, draft_index: 49.0 }
    expect(acquisition({ ...base, row, transfers: [], trades: [] }))
      .toEqual({ kind: 'draft', round: 9, pick: 49 })
  })

  it('cites the latest successful transfer in, not a later or failed one', () => {
    const transfers = [
      { league: 'Prem', short_name: 'AC', element_in: 8, gameweek: 3, kind: 'waiver', result: 'successful' },
      { league: 'Prem', short_name: 'AC', element_in: 8, gameweek: 5, kind: 'free', result: 'successful' },
      { league: 'Prem', short_name: 'AC', element_in: 8, gameweek: 7, kind: 'waiver', result: 'failed' },
      { league: 'Prem', short_name: 'AC', element_in: 8, gameweek: 12, kind: 'waiver', result: 'successful' },
    ]
    expect(acquisition({ ...base, row: { in_original_draft: 0 }, transfers, trades: [] }))
      .toEqual({ kind: 'free', gameweek: 5 })
  })

  it('prefers a processed trade and says who it came from', () => {
    const trades = [
      { league: 'Prem', state: 'o', offered_by: 'AC', received_by: 'TS', element_in: 8, gameweek: 4 },
      { league: 'Prem', state: 'p', offered_by: 'JP', received_by: 'AC', element_out: 8, gameweek: 6 },
    ]
    const transfers = [
      { league: 'Prem', short_name: 'AC', element_in: 8, gameweek: 2, kind: 'waiver', result: 'successful' },
    ]
    expect(acquisition({ ...base, row: { in_original_draft: 0 }, transfers, trades }))
      .toEqual({ kind: 'trade', gameweek: 6, from: 'JP' })
  })

  it('falls back to the first week held when nothing recorded the move', () => {
    expect(acquisition({ ...base, row: { in_original_draft: 0 }, transfers: [], trades: [], firstOwned: 4 }))
      .toEqual({ kind: 'unknown', gameweek: 4 })
  })
})

describe('drafterRecord', () => {
  const rows = [
    week(4, { total_points: 2, points_scored: 2 }),
    week(5, { place: 13, total_points: 9, points_scored: 0 }),   // benched, 9 wasted
    week(6, { total_points: 4, points_scored: 4 }),
    week(7, { total_points: 6, points_scored: 6 }),
    week(8, { total_points: 10, points_scored: 10 }),           // after the selected week
    week(6, { short_name: 'TS', total_points: 99, points_scored: 99 }),  // another drafter
  ]
  const player = { total_points: 40 }
  const seasonGameweeks = [1, 2, 3, 4, 5, 6, 7]

  it('counts weeks held, starts and realised points up to the selected week only', () => {
    const r = drafterRecord({ rows, league: 'Prem', short: 'AC', element: 8, gameweek: 7, player, seasonGameweeks })
    expect(r.weeksOwned).toBe(4)
    expect(r.started).toBe(3)
    expect(r.realised).toBe(12)
    expect(r.firstOwned).toBe(4)
    expect(r.row.gameweek).toBe(7)
  })

  it('normalises his own scoring per week owned, bench weeks included', () => {
    const r = drafterRecord({ rows, league: 'Prem', short: 'AC', element: 8, gameweek: 7, player, seasonGameweeks })
    expect(r.perWeekOwned).toBeCloseTo(21 / 4)
    expect(r.perWeekSeason).toBeCloseTo(40 / 7)
  })

  it('splits before and since pick-up when held continuously to the latest week', () => {
    const r = drafterRecord({ rows, league: 'Prem', short: 'AC', element: 8, gameweek: 7, player, seasonGameweeks })
    // 40 season points, 21 of them in the four weeks held -> 19 over the three before
    expect(r.perWeekBefore).toBeCloseTo(19 / 3)
  })

  it('cannot say "before" for a past week or a broken spell', () => {
    const past = drafterRecord({ rows, league: 'Prem', short: 'AC', element: 8, gameweek: 6, player, seasonGameweeks })
    expect(past.perWeekBefore).toBeNull()
    const gappy = drafterRecord({
      rows: rows.filter(r => r.gameweek !== 5), league: 'Prem', short: 'AC', element: 8,
      gameweek: 7, player, seasonGameweeks,
    })
    expect(gappy.perWeekBefore).toBeNull()
  })

  it('has no "before" for a player held all season', () => {
    const all = [1, 2, 3].map(g => week(g, { total_points: 5, points_scored: 5 }))
    const r = drafterRecord({ rows: all, league: 'Prem', short: 'AC', element: 8, gameweek: 3,
                              player: { total_points: 15 }, seasonGameweeks: [1, 2, 3] })
    expect(r.perWeekBefore).toBeNull()
    expect(r.perWeekOwned).toBeCloseTo(5)
  })

  it('degrades without a players row', () => {
    const r = drafterRecord({ rows, league: 'Prem', short: 'AC', element: 8, gameweek: 7, player: null, seasonGameweeks })
    expect(r.perWeekSeason).toBeNull()
    expect(r.perWeekBefore).toBeNull()
    expect(r.perWeekOwned).toBeCloseTo(21 / 4)
  })
})
