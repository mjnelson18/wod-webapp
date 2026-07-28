import { useEffect, useState } from 'react'

/**
 * Hash routing, hand-rolled — 4 routes don't justify a router dependency, and
 * hashes mean GitHub Pages needs no 404.html fallback for deep links.
 *
 *   #/2526/gw/38   #/2526/season   #/2526/compare   #/2526/explorer
 */

export const VIEWS = ['gw', 'season', 'compare', 'explorer']

export function parseHash(hash) {
  const parts = (hash || '').replace(/^#\/?/, '').split('/').filter(Boolean)
  const [season, view, param] = parts
  return {
    season: season || null,
    view: VIEWS.includes(view) ? view : 'gw',
    param: param ?? null,
  }
}

export function buildHash({ season, view = 'gw', param = null }) {
  return `#/${[season, view, param].filter(v => v !== null && v !== undefined).join('/')}`
}

export function navigate(route) {
  const next = buildHash(route)
  if (window.location.hash !== next) window.location.hash = next
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
