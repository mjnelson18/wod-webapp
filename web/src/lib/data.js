import { useEffect, useState } from 'react'

/**
 * Static JSON loading. The frontend never talks to the FPL API — it only fetches
 * files the pipeline wrote under <base>/data/.
 *
 * Tables are fetched lazily and cached: weekly_summary alone is ~3 MB for a full
 * season, so a view must not pull it unless it actually needs it.
 */

const BASE = `${import.meta.env.BASE_URL}data`
const cache = new Map()

function get(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(`${BASE}/${path}`).then(r => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`)
      return r.json()
    }).catch(err => { cache.delete(path); throw err }))
  }
  return cache.get(path)
}

export const loadSeasons = () => get('seasons.json')
export const loadMeta = season => get(`${season}/meta.json`)
export const loadTable = (season, name) => get(`${season}/${name}.json`)

/** Generic async hook. `deps` gates refetching; returns {data, error, loading}. */
export function useAsync(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let live = true
    setState(s => ({ ...s, loading: true, error: null }))
    Promise.resolve()
      .then(fn)
      .then(data => { if (live) setState({ data, error: null, loading: false }) })
      .catch(error => { if (live) setState({ data: null, error, loading: false }) })
    return () => { live = false }
  }, deps)
  return state
}

/** Load several tables for a season at once. */
export function useTables(season, names) {
  const key = names.join(',')
  return useAsync(
    () => Promise.all(names.map(n => loadTable(season, n)))
      .then(results => Object.fromEntries(names.map((n, i) => [n, results[i]]))),
    [season, key],
  )
}

/**
 * Capability gate. Seasons carry different columns — 2425 has no ownership,
 * fixtures, cost, draft round or trades — so views ask before rendering rather
 * than erroring on missing data.
 */
export function can(meta, capability) {
  return Boolean(meta?.capabilities?.[capability])
}

export const DRAFTER_COLOURS = [
  '#00AEEF', '#FF6A13', '#00A651', '#E4002B', '#A020F0', '#8B4513',
]

/** Stable colour per drafter within a league, ordered by the meta drafter list. */
export function colourMap(meta, league) {
  const drafters = (meta?.drafters ?? []).filter(d => d.league === league)
  return Object.fromEntries(drafters.map((d, i) => [d.short_name, DRAFTER_COLOURS[i % DRAFTER_COLOURS.length]]))
}
