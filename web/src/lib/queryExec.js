/**
 * Query-spec executor: runs the structured spec the /ask worker returns over
 * the season JSON already in the browser. Claude only ever describes the query
 * (lib/ask.js); every number shown comes from real rows run through this file —
 * which is what makes the answers traceable rather than generated.
 *
 * Pure except for `loadRows`, injected so tests run on fixtures and the app on
 * lib/data.js's cached loadTable.
 */

// The tables a spec may name — mirrors QUERY_TABLES in trigger/query-spec.mjs
// (not imported: the worker folder isn't part of the web bundle).
export const QUERY_TABLES = [
  'weekly_summary', 'weekly_points', 'draft_picks',
  'transfers', 'trades', 'players', 'league_table',
]

const MAX_LIMIT = 50

/** A spec the executor refuses to run — rendered as a friendly notice, never thrown to the UI. */
export class QueryError extends Error {
  constructor(message) {
    super(message)
    this.name = 'QueryError'
  }
}

const norm = value => (typeof value === 'string' ? value.toLowerCase() : value)

const comparable = (a, b) => {
  // Numeric comparison when both sides read as numbers, else case-insensitive string.
  const na = Number(a); const nb = Number(b)
  if (a !== '' && b !== '' && !Number.isNaN(na) && !Number.isNaN(nb)) return [na, nb]
  return [norm(String(a)), norm(String(b))]
}

function applyCondition(row, { col, op, value }) {
  const have = row[col]
  switch (op) {
    case 'eq': {
      if (have == null || value == null) return have == null && value == null
      const [a, b] = comparable(have, value)
      return a === b
    }
    case 'neq': {
      if (have == null || value == null) return !(have == null && value == null)
      const [a, b] = comparable(have, value)
      return a !== b
    }
    case 'contains':
      return have != null && String(have).toLowerCase().includes(String(value ?? '').toLowerCase())
    case 'gte': {
      if (have == null) return false
      const [a, b] = comparable(have, value)
      return a >= b
    }
    case 'lte': {
      if (have == null) return false
      const [a, b] = comparable(have, value)
      return a <= b
    }
    case 'in':
      return Array.isArray(value) && value.some(v => {
        if (have == null) return v == null
        const [a, b] = comparable(have, v)
        return a === b
      })
    default:
      throw new QueryError(`unknown operator ${op}`)
  }
}

function checkColumns(spec, known) {
  if (!known.size) return
  for (const group of spec.where ?? []) {
    for (const cond of group.all ?? []) {
      if (!known.has(cond.col)) throw new QueryError(`no column ${cond.col} in ${spec.table}`)
    }
  }
  for (const col of spec.group_by ?? []) {
    if (!known.has(col)) throw new QueryError(`no column ${col} in ${spec.table}`)
  }
  for (const agg of spec.aggregate ?? []) {
    if (agg.col != null && !known.has(agg.col)) {
      throw new QueryError(`no column ${agg.col} in ${spec.table}`)
    }
  }
}

function aggregateRows(rows, groupBy, aggregates) {
  const groups = new Map()
  for (const row of rows) {
    const key = JSON.stringify(groupBy.map(col => row[col] ?? null))
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }

  const out = []
  for (const members of groups.values()) {
    const result = {}
    for (const col of groupBy) result[col] = members[0][col] ?? null
    for (const { fn, col, as } of aggregates) {
      const values = col == null ? [] : members.map(r => Number(r[col])).filter(v => !Number.isNaN(v))
      let value
      if (fn === 'count') value = col == null ? members.length : values.length
      else if (!values.length) value = null
      else if (fn === 'sum') value = values.reduce((s, v) => s + v, 0)
      else if (fn === 'mean') value = Math.round((values.reduce((s, v) => s + v, 0) / values.length) * 100) / 100
      else if (fn === 'min') value = Math.min(...values)
      else if (fn === 'max') value = Math.max(...values)
      else throw new QueryError(`unknown aggregate ${fn}`)
      result[as] = value
    }
    out.push(result)
  }
  return out
}

function fillHeadline(template, row) {
  if (!template || !row) return null
  let missing = false
  const text = template.replace(/\{(\w+)\}/g, (_, key) => {
    const value = row[key]
    if (value == null) { missing = true; return '…' }
    return String(value)
  })
  // A headline with holes reads worse than no headline.
  return missing ? null : text
}

/**
 * Which seasons a spec wants, resolved against what the site publishes.
 * null = run single-season (the current behaviour); otherwise a non-empty
 * list of {id, label} to union over.
 */
function requestedSeasons(spec, seasons) {
  const available = Array.isArray(seasons) ? seasons.filter(s => s?.id != null) : []
  if (spec.seasons == null || !available.length) return null
  if (spec.seasons === 'all') return available
  if (Array.isArray(spec.seasons)) {
    const wanted = spec.seasons.map(String)
    const matched = available.filter(s => wanted.includes(String(s.id)))
    if (!matched.length) {
      throw new QueryError(`no published season matches ${wanted.join(', ')}`)
    }
    return matched
  }
  throw new QueryError('the seasons field makes no sense')
}

/**
 * Run a spec. `loadRows(table)` resolves to that table's rows; for a
 * cross-season spec it is called as `loadRows(table, seasonId)` per season and
 * may resolve to null where a season lacks the table (that season is skipped).
 * `options.seasons` is the published-season list ([{id, label}]) — without it
 * every spec runs single-season. Returns { rows, headline } — rows already
 * filtered, aggregated, sorted, projected and capped.
 */
export async function runSpec(spec, loadRows, options = {}) {
  if (!spec || spec.answerable === false) {
    throw new QueryError(spec?.reason || 'That question cannot be answered from the season tables.')
  }
  if (!QUERY_TABLES.includes(spec.table)) throw new QueryError(`unknown table ${spec.table}`)

  const span = requestedSeasons(spec, options.seasons)
  let all
  const known = new Set()
  if (span) {
    const batches = await Promise.all(span.map(({ id }) =>
      loadRows(spec.table, id).then(rows => (Array.isArray(rows) ? rows : null), () => null)))
    if (batches.every(b => b == null)) {
      throw new QueryError(`none of those seasons publish ${spec.table}`)
    }
    // Rows gain season/season_label; columns are the union across seasons,
    // since older archives carry fewer columns than live seasons.
    all = []
    span.forEach(({ id, label }, i) => {
      const rows = batches[i]
      if (!rows) return
      if (rows.length) for (const key of Object.keys(rows[0])) known.add(key)
      for (const row of rows) all.push({ ...row, season: id, season_label: label ?? String(id) })
    })
    known.add('season').add('season_label')
  } else {
    all = await loadRows(spec.table)
    if (!Array.isArray(all)) throw new QueryError(`${spec.table} did not load`)
    if (all.length) for (const key of Object.keys(all[0])) known.add(key)
  }
  checkColumns(spec, known)

  const groups = Array.isArray(spec.where) ? spec.where : []
  let rows = groups.length
    ? all.filter(row => groups.some(g => (g.all ?? []).every(c => applyCondition(row, c))))
    : [...all]

  const groupBy = Array.isArray(spec.group_by) ? spec.group_by : []
  const aggregates = Array.isArray(spec.aggregate) ? spec.aggregate : []
  if (groupBy.length || aggregates.length) {
    rows = aggregateRows(rows, groupBy, aggregates)
  }

  for (const { col, dir } of [...(spec.sort ?? [])].reverse()) {
    const sign = dir === 'desc' ? -1 : 1
    rows.sort((x, y) => {
      const a = x[col]; const b = y[col]
      if (a == null && b == null) return 0
      if (a == null) return 1       // nulls last, whatever the direction
      if (b == null) return -1
      const [ca, cb] = comparable(a, b)
      return ca < cb ? -sign : ca > cb ? sign : 0
    })
  }

  const limit = Math.max(1, Math.min(Number(spec.limit) || MAX_LIMIT, MAX_LIMIT))
  rows = rows.slice(0, limit)

  if (Array.isArray(spec.select) && spec.select.length && rows.length) {
    const keep = spec.select.filter(col => col in rows[0])
    if (keep.length) rows = rows.map(row => Object.fromEntries(keep.map(col => [col, row[col]])))
  }

  return { rows, headline: fillHeadline(spec.headline, rows[0]) }
}
