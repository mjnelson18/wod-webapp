/**
 * Naming conventions.
 *
 * Full names read better in prose and tables, where there's room. Charts need
 * initials — six full names on a legend or an axis at 375px is unreadable.
 */

/** short_name -> full name, from meta.drafters. */
export function nameIndex(meta) {
  return Object.fromEntries((meta?.drafters ?? []).map(d => [d.short_name, d.name || d.short_name]))
}

/** Full name where known ("Tom Shiel"), falling back to initials. */
export function fullName(meta, shortName) {
  if (!shortName) return ''
  const bare = String(shortName).replace(' (Benched)', '')
  return nameIndex(meta)[bare] ?? bare
}

/** Always the short form — use for chart axes, legends and dense grids. */
export function label(shortName) {
  return String(shortName ?? '').replace(' (Benched)', '')
}

/** "Tom Shiel (TS)" — for headings where both help. */
export function nameWithInitials(meta, shortName) {
  const full = fullName(meta, shortName)
  return full === shortName ? full : `${full} (${shortName})`
}

export const leagueName = (meta, code) =>
  meta?.leagues?.find(l => l.code === code)?.name ?? code

/** 0.1234 -> "12.3%" */
export const pct = (value, digits = 1) =>
  value == null ? '–' : `${(Number(value) * 100).toFixed(digits)}%`

/** Signed integer, for deltas: 12 -> "+12". */
export const signed = value => {
  if (value == null) return '–'
  const n = Math.round(Number(value))
  return n > 0 ? `+${n}` : String(n)
}

export const round = (value, digits = 1) =>
  value == null ? '–' : Number(Number(value).toFixed(digits))

/** Rank movement arrow, comparing this gameweek's rank with last. */
export function rankMove(rank, lastRank) {
  if (!rank || !lastRank) return null
  if (lastRank === 0) return null
  const delta = lastRank - rank
  if (delta === 0) return { text: '–', className: 'muted' }
  return delta > 0
    ? { text: `▲${delta}`, className: 'up' }
    : { text: `▼${Math.abs(delta)}`, className: 'down' }
}
