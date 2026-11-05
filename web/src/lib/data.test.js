import { describe, it, expect } from 'vitest'
import { executedTrades } from './data.js'

describe('executedTrades', () => {
  const rows = [
    { gameweek: 4, state: 'p', offered_by: 'MN' },
    { gameweek: 6, state: 'o', offered_by: 'TS' },   // offered, never accepted
    { gameweek: 7, state: 'r', offered_by: 'CJ' },   // rejected
    { gameweek: 9, state: 'p', offered_by: 'TS' },
  ]

  it('keeps only processed trades', () => {
    expect(executedTrades(rows).map(t => t.gameweek)).toEqual([4, 9])
  })

  it('tolerates a missing table', () => {
    expect(executedTrades(undefined)).toEqual([])
    expect(executedTrades(null)).toEqual([])
  })

  it('drops rows with no state at all', () => {
    expect(executedTrades([{ gameweek: 1 }])).toEqual([])
  })
})
