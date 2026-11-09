/**
 * What a footballer has done for the drafter who holds him, as at a gameweek.
 *
 * Everything here folds the tables the gameweek view already has — weekly_summary,
 * transfers, trades and the players table — so the squad-cell modal can put the
 * tile's abbreviations (D3, Tn6, 51 R) into words without a new pipeline output.
 */

const STARTERS = 11

const by = key => (a, b) => (a[key] ?? 0) - (b[key] ?? 0)

/**
 * How `short` came by `element`, as the squad tile labels it: the draft wins,
 * then a processed trade, then the latest successful transfer in — but only
 * ones made by the selected gameweek, so viewing GW3 never cites a GW8 waiver.
 *
 * Returns {kind: 'draft', round, pick} | {kind: 'trade'|'waiver'|'free', gameweek, from?}
 * | {kind: 'unknown', gameweek} (held, with no recorded way in — the CSV archives).
 */
export function acquisition({ row, transfers, trades, league, short, element, gameweek, firstOwned }) {
  if (row?.in_original_draft === 1 && row.round != null) {
    return { kind: 'draft', round: row.round, pick: row.draft_index != null ? Math.round(row.draft_index) : null }
  }
  const trade = (trades ?? [])
    .filter(t => t.state === 'p' && (!t.league || t.league === league) && t.gameweek <= gameweek)
    .filter(t => (t.offered_by === short && t.element_in === element)
              || (t.received_by === short && t.element_out === element))
    .sort(by('gameweek')).at(-1)
  if (trade) {
    return {
      kind: 'trade', gameweek: trade.gameweek,
      from: trade.offered_by === short ? trade.received_by : trade.offered_by,
    }
  }
  const transfer = (transfers ?? [])
    .filter(t => t.result === 'successful' && (!t.league || t.league === league) && t.gameweek <= gameweek)
    .filter(t => t.short_name === short && t.element_in === element)
    .sort(by('gameweek')).at(-1)
  if (transfer) return { kind: transfer.kind === 'waiver' ? 'waiver' : 'free', gameweek: transfer.gameweek }
  return { kind: 'unknown', gameweek: firstOwned ?? gameweek }
}

/**
 * The drafter's record with the player up to and including `gameweek`.
 *
 *   weeksOwned   gameweeks he sat in this squad
 *   started      of those, how many in the XI (after auto-subs)
 *   realised     points the drafter banked from him (starts only)
 *   perWeekOwned his own points per week while owned — bench weeks included,
 *                so it says how he has played, not how he was used
 *   perWeekSeason  season points per gameweek played so far, for comparison
 *   perWeekBefore  his points per week before this drafter picked him up. Only
 *                knowable when the season total is current — i.e. the selected
 *                gameweek is the latest one — and he has been held continuously
 *                since arriving, so every week not in this squad came earlier.
 *                Null otherwise. (Whether it means anything for a draft pick is
 *                the view's call — this just reports the arithmetic.)
 */
export function drafterRecord({ rows, league, short, element, gameweek, player, seasonGameweeks }) {
  const owned = (rows ?? [])
    .filter(r => r.league === league && r.short_name === short && r.element === element
              && r.gameweek <= gameweek)
    .sort(by('gameweek'))
  const weeksOwned = owned.length
  const started = owned.filter(r => (r.place ?? 99) <= STARTERS).length
  const realised = owned.reduce((s, r) => s + (Number(r.points_scored) || 0), 0)
  const scoredWhileOwned = owned.reduce((s, r) => s + (Number(r.total_points) || 0), 0)
  const perWeekOwned = weeksOwned ? scoredWhileOwned / weeksOwned : null

  const played = seasonGameweeks?.length ?? 0
  const latest = played ? seasonGameweeks[played - 1] : null
  const seasonTotal = player?.total_points != null ? Number(player.total_points) : null
  const perWeekSeason = seasonTotal != null && played ? seasonTotal / played : null

  const firstOwned = owned[0]?.gameweek ?? null
  const contiguousToNow = weeksOwned > 0 && gameweek === latest
    && owned[weeksOwned - 1].gameweek === latest
    && latest - firstOwned + 1 === weeksOwned
  const weeksBefore = contiguousToNow ? played - weeksOwned : 0
  const perWeekBefore = contiguousToNow && weeksBefore > 0 && seasonTotal != null
    ? (seasonTotal - scoredWhileOwned) / weeksBefore
    : null

  return {
    weeksOwned, started, realised, perWeekOwned, perWeekSeason, perWeekBefore, firstOwned,
    row: owned[weeksOwned - 1] ?? null,
  }
}
