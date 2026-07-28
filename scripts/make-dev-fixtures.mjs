/**
 * DEV FIXTURES ONLY — not part of the pipeline.
 *
 * Reads reference/historical/*.csv and emits canonical-shaped JSON into
 * web/public/data/<season>/ so the frontend can be built against real numbers
 * while the Python pipeline is blocked (see docs/notebook-recon.md).
 *
 * The Python pipeline is the real producer of this shape. When it lands, delete
 * this script — but keep the schema below, which is the pipeline/frontend contract.
 *
 *   node scripts/make-dev-fixtures.mjs
 *
 * Emits per season:
 *   meta.json           season + leagues + drafters + capabilities flags
 *   league_table.json   one row per drafter
 *   weekly_summary.json one row per drafter per squad slot per gameweek
 *   weekly_points.json  one row per element per gameweek (reduced, see below)
 *   draft_picks.json    one row per pick
 *   transfers.json      waiver + free agent moves, including failed attempts
 *   trades.json         drafter-to-drafter swaps
 *   players.json        one row per footballer
 *   teams.json          team id -> short name
 *
 * `capabilities` is how seasons degrade gracefully: a view checks the flag and
 * renders an "unavailable for this season" notice rather than erroring. 2425's
 * CSVs lack ownership-per-league, fixtures, difficulty, cost, draft round and
 * trades entirely, which makes it the useful test case.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const HIST = join(ROOT, 'reference', 'historical')
const OUT = join(ROOT, 'web', 'public', 'data')

const LEAGUE_NAMES = { Prem: 'Premiership', Conf: 'Conference' }

/** Minimal RFC4180-ish CSV parser: handles quoted fields, embedded commas and newlines. */
function parseCsv(text) {
  const rows = []
  let row = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } else { quoted = false }
      } else field += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(field); field = '' }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = '' }
    else if (c !== '\r') field += c
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row) }
  if (!rows.length) return []
  const header = rows[0].map((h, i) => (h === '' ? `_col${i}` : h))
  return rows.slice(1)
    .filter(r => r.length > 1)
    .map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])))
}

function readCsv(name) {
  const path = join(HIST, name)
  if (!existsSync(path)) return null
  return parseCsv(readFileSync(path, 'utf8'))
}

/** '' -> null, numeric strings -> Number, else the string. */
const val = v => {
  if (v === undefined || v === null || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? v : n
}
const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
const int = v => Math.trunc(num(v))

/** Pick+coerce a subset of columns, dropping any the season doesn't have. */
function project(rows, spec) {
  return rows.map(r => {
    const out = {}
    for (const [key, src] of Object.entries(spec)) {
      out[key] = typeof src === 'function' ? src(r) : (src in r ? val(r[src]) : null)
    }
    return out
  })
}

function buildSeason(season, label) {
  const has = name => existsSync(join(HIST, name))
  const ws = readCsv(`Weekly Summary_${season}.csv`)
  if (!ws) { console.log(`  ${season}: no Weekly Summary, skipping`); return null }

  const cols = new Set(Object.keys(ws[0]))
  const capabilities = {
    fixtures: cols.has('opposition'),
    difficulty: cols.has('team_difficulty'),
    cost: has(`All Players Summary_${season}.csv`) &&
          new Set(Object.keys(readCsv(`All Players Summary_${season}.csv`)[0])).has('now_cost'),
    ownership_by_league: cols.has('drafter_name'),
    draft_round: cols.has('round'),
    cumulative: cols.has('points_scored_cumulative'),
    team_names: cols.has('team_name'),
    trades: has(`trade_history_${season}.csv`),
    optimal_points: cols.has('optimal_points'),
  }

  // ---- weekly_summary: the richest table, drives most views ----
  const weekly_summary = project(ws, {
    gameweek: 'gameweek', league: 'league_code', short_name: 'short_name',
    element: 'element', place: 'place', web_name: 'web_name', position: 'position',
    team_id: 'team_id', team_name: 'team_name',
    total_points: 'total_points', points_scored: 'points_scored',
    points_before_auto_subs: 'points_before_auto_subs',
    originally_starting: 'originally_starting',
    optimal_points: 'optimal_points',
    player_total_points: 'player_total_points',
    points_scored_cumulative: 'points_scored_cumulative',
    drafter_name: 'drafter_name', draft_index: 'draft_index', round: 'round',
    in_original_draft: 'in_original_draft',
    opposition: 'opposition', home_away: 'home_away',
    team_difficulty: 'team_difficulty', opposition_difficulty: 'opposition_difficulty',
  })
  for (const r of weekly_summary) r.short_name = String(r.short_name ?? '').toUpperCase()

  const gameweeks = [...new Set(weekly_summary.map(r => r.gameweek))].sort((a, b) => a - b)
  const currentGw = Math.max(...gameweeks)

  // ---- league table: totals + rank + 5-game form, derived from weekly_summary ----
  const byDrafter = new Map()
  for (const r of weekly_summary) {
    const key = `${r.league}|${r.short_name}`
    if (!byDrafter.has(key)) byDrafter.set(key, { league: r.league, short_name: r.short_name, total: 0, gw: new Map() })
    const d = byDrafter.get(key)
    d.total += num(r.points_scored)
    d.gw.set(r.gameweek, (d.gw.get(r.gameweek) ?? 0) + num(r.points_scored))
  }
  const FORM_GAMES = 5
  let league_table = [...byDrafter.values()].map(d => {
    const formWeeks = gameweeks.filter(g => g > currentGw - FORM_GAMES)
    const formTotal = formWeeks.reduce((s, g) => s + (d.gw.get(g) ?? 0), 0)
    return {
      league: d.league, short_name: d.short_name,
      total: d.total,
      gameweek_points: d.gw.get(currentGw) ?? 0,
      form_points: Math.round((formTotal / Math.min(FORM_GAMES, gameweeks.length)) * 10) / 10,
      points_by_gameweek: gameweeks.map(g => d.gw.get(g) ?? 0),
    }
  })
  // rank within league, and cumulative for the trend chart
  for (const lg of new Set(league_table.map(r => r.league))) {
    const rows = league_table.filter(r => r.league === lg).sort((a, b) => b.total - a.total)
    rows.forEach((r, i) => { r.rank = i + 1 })
    const formRanked = [...rows].sort((a, b) => b.form_points - a.form_points)
    formRanked.forEach((r, i) => { r.form_rank = i + 1 })
  }
  for (const r of league_table) {
    let run = 0
    r.cumulative_by_gameweek = r.points_by_gameweek.map(p => (run += p))
  }
  league_table.sort((a, b) => a.league.localeCompare(b.league) || a.rank - b.rank)

  // ---- names from draft picks / league entries where available ----
  const dp = readCsv(`Draft Picks_${season}.csv`) ?? []
  const nameByShort = new Map()
  for (const r of dp) {
    const sn = String(r.short_name ?? '').toUpperCase()
    if (r.first_name && !nameByShort.has(sn)) nameByShort.set(sn, `${r.first_name} ${r.last_name ?? ''}`.trim())
  }
  for (const r of league_table) r.name = nameByShort.get(r.short_name) ?? r.short_name

  const draft_picks = project(dp, {
    league: 'league_code', short_name: r => String(r.short_name ?? '').toUpperCase(),
    index: 'index', pick: 'pick', round: 'round',
    element: 'element', web_name: 'web_name', position: 'position',
    team_name: 'team_name', draft_rank: 'draft_rank',
    now_cost: 'now_cost', selected_by_percent: 'selected_by_percent',
    total_points: 'total_points',
  })

  // ---- weekly_points, reduced: owned rows + undrafted top-20 per gameweek ----
  // The raw table is ~59k rows for 2526, 88% of it undrafted players nobody asks
  // about. Views only need owned rows plus the best available/undrafted names.
  const ppwRaw = readCsv(`Player Points Weekly_${season}.csv`) ?? []
  let weekly_points = []
  if (ppwRaw.length && 'short_name' in ppwRaw[0]) {
    const owned = ppwRaw.filter(r => r.short_name && !String(r.short_name).startsWith('Not Drafted'))
    const undrafted = ppwRaw.filter(r => String(r.short_name ?? '').startsWith('Not Drafted') && int(r.rank_in_week) <= 20)
    weekly_points = project([...owned, ...undrafted], {
      gameweek: 'gameweek', league: 'league_code', element: 'id',
      web_name: 'web_name', position: 'position', team_name: 'team_name',
      total_points: 'total_points', rank_in_week: 'rank_in_week',
      owner: 'short_name', place: 'place', is_benched: 'isBenched',
      drafter_name: 'drafter_name',
    })
  } else {
    // 2425: only id/total_points/gameweek exist — no ownership, no names.
    weekly_points = project(ppwRaw, {
      gameweek: 'gameweek', element: 'id', total_points: 'total_points',
      league: () => null, web_name: () => null, owner: () => null,
      rank_in_week: () => null, position: () => null, team_name: () => null,
      place: () => null, is_benched: () => null, drafter_name: () => null,
    })
  }

  // ---- transfers: 2425 uses a different schema (person, no league, names only) ----
  const txRaw = readCsv(`Transfers_${season}.csv`) ?? []
  const transfers = project(txRaw, {
    league: r => ('league_code' in r ? val(r.league_code) : null),
    gameweek: r => val(r.gameweek ?? r.event),
    short_name: r => String(r.short_name ?? r.person ?? '').toUpperCase() || null,
    kind: 'kind', result: 'result', priority: 'priority',
    element_in: 'element_in', element_out: 'element_out',
    player_in: 'player_in', player_out: 'player_out',
    player_in_points: 'player_in_points_scored_in_week',
    player_out_points: 'player_out_points_scored_in_week',
    net_points: r => val(r.net_points_of_transfer_in_week ?? r.net_points_of_trade_in_week),
  })

  // ---- trades ----
  const trRaw = readCsv(`trade_history_${season}.csv`) ?? []
  const trades = project(trRaw, {
    league: 'league_code', gameweek: 'GW traded',
    offered_by: r => String(r.offered_by ?? '').toUpperCase(),
    received_by: r => String(r.received_by ?? '').toUpperCase(),
    element_in: 'element_in', player_in: 'player_in',
    element_out: 'element_out', player_out: 'player_out',
    player_in_points: 'player_in_total_points',
    player_out_points: 'player_out_total_points',
    net_points: 'net_points_from_trade',
    state: () => 'p',
  })

  const players = project(readCsv(`All Players Summary_${season}.csv`) ?? [], {
    element: 'id', web_name: 'web_name', position: 'position',
    team_id: 'team', team_name: 'team_name', total_points: 'total_points',
    goals_scored: 'goals_scored', assists: 'assists', bonus: 'bonus',
    clean_sheets: 'clean_sheets', minutes: 'minutes',
    draft_rank: 'draft_rank', now_cost: 'now_cost', selected_by_percent: 'selected_by_percent',
  })

  const teams = project(readCsv(`Teams_${season}.csv`) ?? [], { team_id: 'team', team_name: 'team_name' })

  // 2425 was the one-off 5/7 split with 3 up / 1 down; everything after is 6/6, 2 up / 2 down.
  const sizes = {}
  for (const r of league_table) sizes[r.league] = (sizes[r.league] ?? 0) + 1
  const promoRelegation = season === '2425'
    ? { Prem: { relegated: 1 }, Conf: { promoted: 3 } }
    : { Prem: { relegated: 2 }, Conf: { promoted: 2 } }

  const meta = {
    season, label,
    source: 'dev-fixture-from-csv',
    current_gameweek: currentGw,
    total_gameweeks: gameweeks.length,
    complete: true,
    gameweeks,
    leagues: [...new Set(league_table.map(r => r.league))].sort().reverse().map(code => ({
      code, name: LEAGUE_NAMES[code] ?? code, size: sizes[code], ...(promoRelegation[code] ?? {}),
    })),
    drafters: league_table.map(r => ({ short_name: r.short_name, name: r.name, league: r.league })),
    capabilities,
  }

  const dir = join(OUT, season)
  mkdirSync(dir, { recursive: true })
  const files = {
    'meta.json': meta,
    'league_table.json': league_table,
    'weekly_summary.json': weekly_summary,
    'weekly_points.json': weekly_points,
    'draft_picks.json': draft_picks,
    'transfers.json': transfers,
    'trades.json': trades,
    'players.json': players,
    'teams.json': teams,
  }
  let totalKb = 0
  for (const [name, data] of Object.entries(files)) {
    const json = JSON.stringify(data)
    writeFileSync(join(dir, name), json)
    totalKb += json.length / 1024
  }
  const caps = Object.entries(capabilities).filter(([, v]) => !v).map(([k]) => k)
  console.log(`  ${season}: ${weekly_summary.length} summary rows, ${weekly_points.length} point rows, ` +
              `${Math.round(totalKb)} KB${caps.length ? ` | missing: ${caps.join(', ')}` : ''}`)
  return meta
}

console.log('building dev fixtures from reference/historical CSVs')
const seasons = [['2526', '2025/26'], ['2425', '2024/25']]
const built = seasons.map(([s, l]) => buildSeason(s, l)).filter(Boolean)

mkdirSync(OUT, { recursive: true })
writeFileSync(join(OUT, 'seasons.json'), JSON.stringify({
  seasons: built.map(m => ({
    season: m.season, label: m.label, current_gameweek: m.current_gameweek, complete: m.complete,
  })).sort((a, b) => b.season.localeCompare(a.season)),
  default: built.map(m => m.season).sort().reverse()[0],
}, null, 2))
console.log(`wrote ${built.length} seasons + seasons.json to web/public/data`)
