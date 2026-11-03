/**
 * Client for the /ask endpoint on the trigger worker (trigger/worker.js).
 *
 * The endpoint URL comes from VITE_ASK_ENDPOINT in web/.env.<slug> — a build
 * constant, not a secret. When it is unset the Ask box simply doesn't render:
 * the static site never errors over an optional feature.
 */

const ENDPOINT = import.meta.env.VITE_ASK_ENDPOINT

export const askAvailable = () => Boolean(ENDPOINT)

/** Error codes the UI knows how to phrase: busy | budget | unavailable | bad_question. */
export class AskError extends Error {
  constructor(code) {
    super(code)
    this.name = 'AskError'
    this.code = code
  }
}

/**
 * The whitelisted context the worker's prompt builder accepts — nothing more.
 * `season` is the selected season's id and `seasonsIndex` the seasons.json
 * payload (null is fine: the prompt then only knows the selected season).
 */
export function askContext(meta, season, seasonsIndex) {
  return {
    label: meta?.label,
    gameweek: meta?.current_gameweek,
    season,
    seasons: (seasonsIndex?.seasons ?? []).map(s => ({ id: s.season, label: s.label })),
    leagues: (meta?.leagues ?? []).map(l => ({ code: l.code, name: l.name, scoring: l.scoring })),
    drafters: (meta?.drafters ?? []).map(d => ({
      short_name: d.short_name, name: d.name, league: d.league,
    })),
  }
}

/** Ask the worker to turn a question into a query spec. Throws AskError only. */
export async function fetchSpec(question, context) {
  if (!ENDPOINT) throw new AskError('unavailable')

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 20000)
  let res
  try {
    res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, context }),
      signal: controller.signal,
    })
  } catch {
    throw new AskError('unavailable')
  } finally {
    clearTimeout(timer)
  }

  if (res.status === 429) {
    let code = 'busy'
    try { code = (await res.json()).error === 'budget' ? 'budget' : 'busy' } catch { /* keep busy */ }
    throw new AskError(code)
  }
  if (res.status === 400) throw new AskError('bad_question')
  if (!res.ok) throw new AskError('unavailable')

  let payload
  try {
    payload = await res.json()
  } catch {
    throw new AskError('unavailable')
  }
  if (!payload?.spec) throw new AskError('unavailable')
  return payload.spec
}
