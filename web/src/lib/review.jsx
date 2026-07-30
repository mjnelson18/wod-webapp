import { buildHash } from './router.js'

/**
 * Season review prose.
 *
 * The written review lives in the repo rather than in the data pack: it's
 * authored once when a season ends and edited by hand, so it belongs in git
 * history, not in JSON that gets regenerated every ten minutes. The numbers
 * around it come from `season_review_facts.json`, which means the honours strip
 * can never drift from the data even if the prose ages.
 *
 * Bundled per season as its own lazy chunk, so opening the gameweek grid never
 * downloads an essay about a season you aren't looking at.
 */
const MODULES = import.meta.glob('../content/season-review/*.md', {
  query: '?raw', import: 'default',
})

const BY_SEASON = Object.fromEntries(
  Object.entries(MODULES).map(([path, load]) => [path.match(/([^/]+)\.md$/)[1], load]),
)

/** Synchronous, so the header can decide whether to show the tab at all. */
export function hasReview(season) {
  return Boolean(BY_SEASON[String(season)])
}

export function loadReview(season) {
  const load = BY_SEASON[String(season)]
  return load ? load() : Promise.resolve(null)
}

/**
 * A deliberately small markdown subset — headings, paragraphs, blockquotes,
 * bold, italic and links — because we author the prose as well as the renderer.
 * A full markdown dependency would be ~12 KB gzip to support syntax this file
 * will never contain.
 *
 * Links understand `gw:14`, which resolves to that season's gameweek tab, so a
 * review can point at the week it's describing.
 */
const INLINE = /\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\(([^)]+)\)/g

function href(target, season) {
  const gameweek = /^gw:(\d+)$/.exec(target)
  if (gameweek) return buildHash({ season, view: 'gw', param: gameweek[1] })
  const view = /^view:(\w+)$/.exec(target)
  if (view) return buildHash({ season, view: view[1] })
  return target
}

function inline(text, season) {
  const nodes = []
  let last = 0
  let key = 0
  let match
  INLINE.lastIndex = 0
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    if (match[1]) nodes.push(<strong key={key++}>{match[1]}</strong>)
    else if (match[2]) nodes.push(<em key={key++}>{match[2]}</em>)
    else nodes.push(<a key={key++} href={href(match[4], season)}>{match[3]}</a>)
    last = match.index + match[0].length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function renderReview(text, season) {
  if (!text) return null
  return text.trim().split(/\n{2,}/).map((block, i) => {
    const body = block.trim()
    if (body.startsWith('### ')) return <h3 key={i}>{inline(body.slice(4), season)}</h3>
    if (body.startsWith('## ')) return <h2 key={i}>{inline(body.slice(3), season)}</h2>
    if (body.startsWith('# ')) return <h2 key={i}>{inline(body.slice(2), season)}</h2>
    if (body.startsWith('> ')) {
      const quote = body.split('\n').map(line => line.replace(/^>\s?/, '')).join(' ')
      return <blockquote key={i}>{inline(quote, season)}</blockquote>
    }
    return <p key={i}>{inline(body.replace(/\n/g, ' '), season)}</p>
  })
}
