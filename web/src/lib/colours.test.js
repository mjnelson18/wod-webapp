import { describe, it, expect } from 'vitest'
import { colourMap, DRAFTER_COLOURS } from './data.js'

describe('colourMap', () => {
  const drafter = (short_name, league) => ({ short_name, name: null, league })
  const prem = ['TS', 'JP', 'LB', 'AN', 'MN', 'LD']
  const conf = ['AC', 'CR', 'PV', 'HC', 'IR', 'BP']

  it('gives the same colours whatever order the meta lists drafters in', () => {
    const standings = { drafters: prem.map(s => drafter(s, 'Prem')) }
    const reshuffled = { drafters: [...prem].reverse().map(s => drafter(s, 'Prem')) }
    expect(colourMap(standings, 'Prem')).toEqual(colourMap(reshuffled, 'Prem'))
  })

  it('deals alphabetically by initials, case-insensitively', () => {
    const meta = { drafters: ['mn', 'AN', 'ts'].map(s => drafter(s, 'Prem')) }
    expect(colourMap(meta, 'Prem')).toEqual({
      AN: DRAFTER_COLOURS[0], mn: DRAFTER_COLOURS[1], ts: DRAFTER_COLOURS[2],
    })
  })

  it('deals each league independently from the first colour', () => {
    const meta = { drafters: [...prem.map(s => drafter(s, 'Prem')), ...conf.map(s => drafter(s, 'Conf'))] }
    const p = colourMap(meta, 'Prem')
    const c = colourMap(meta, 'Conf')
    expect(Object.keys(p).sort()).toEqual([...prem].sort())
    expect(Object.keys(c).sort()).toEqual([...conf].sort())
    expect(p.AN).toBe(DRAFTER_COLOURS[0])   // first alphabetically in the Prem
    expect(c.AC).toBe(DRAFTER_COLOURS[0])   // first alphabetically in the Conf
    expect(new Set(Object.values(p)).size).toBe(6)
    expect(new Set(Object.values(c)).size).toBe(6)
  })

  it('does not reorder the meta it was given', () => {
    const meta = { drafters: prem.map(s => drafter(s, 'Prem')) }
    colourMap(meta, 'Prem')
    expect(meta.drafters.map(d => d.short_name)).toEqual(prem)
  })
})
