import { useMemo, useState } from 'react'
import {
  useReactTable, getCoreRowModel, getSortedRowModel,
  getFilteredRowModel, getPaginationRowModel, flexRender,
} from '@tanstack/react-table'
import { loadTable, useAsync } from '../lib/data.js'
import { Section, Loading } from '../components/ui.jsx'

/**
 * Raw data explorer — sortable, filterable, paginated tables over the canonical
 * JSON, for the ad-hoc questions the curated views don't answer.
 *
 * Tables are loaded one at a time on demand: weekly_summary is ~3 MB and
 * weekly_points ~1.6 MB, so eagerly loading everything would be wasteful.
 */
const TABLES = [
  { name: 'weekly_summary', label: 'Weekly summary', note: 'one row per drafter per squad slot per gameweek' },
  { name: 'weekly_points', label: 'Player points', note: 'one row per player per gameweek' },
  { name: 'draft_picks', label: 'Draft picks', note: 'one row per pick' },
  { name: 'transfers', label: 'Transfers', note: 'waivers and free agents, including failed attempts' },
  { name: 'trades', label: 'Trades', note: 'drafter-to-drafter swaps' },
  { name: 'players', label: 'Players', note: 'one row per footballer' },
  { name: 'league_table', label: 'League table', note: 'one row per drafter' },
]

const PAGE_SIZE = 50

export default function Explorer({ season }) {
  const [which, setWhich] = useState(TABLES[0].name)
  const [query, setQuery] = useState('')
  const [sorting, setSorting] = useState([])

  const { data, loading, error } = useAsync(() => loadTable(season, which), [season, which])

  const columns = useMemo(() => {
    if (!data?.length) return []
    // Union of the first rows' keys — rows are uniform, but nulls can hide keys.
    const keys = [...new Set(data.slice(0, 50).flatMap(r => Object.keys(r)))]
    return keys.map(key => ({
      accessorKey: key,
      header: key.replace(/_/g, ' '),
      cell: info => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span className="muted">–</span>
        return typeof v === 'number' ? Math.round(v * 1000) / 1000 : String(v)
      },
    }))
  }, [data])

  const rows = useMemo(() => {
    if (!data) return []
    if (!query.trim()) return data
    const q = query.toLowerCase()
    return data.filter(r => Object.values(r).some(v => v != null && String(v).toLowerCase().includes(q)))
  }, [data, query])

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: PAGE_SIZE } },
  })

  const active = TABLES.find(t => t.name === which)

  return (
    <Section title="Data explorer" note={active?.note}>
      <div className="chips" style={{ marginBottom: 8 }}>
        {TABLES.map(t => (
          <button
            key={t.name}
            className="chip"
            aria-pressed={which === t.name}
            onClick={() => { setWhich(t.name); setSorting([]); setQuery('') }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <input
        type="search"
        placeholder="Filter across all columns…"
        value={query}
        onChange={e => setQuery(e.target.value)}
        style={{ marginBottom: 8 }}
      />

      {error && <div className="notice">Couldn&apos;t load {which}: {String(error.message)}</div>}
      {loading && <Loading what={active?.label ?? which} />}

      {!loading && data && (
        <>
          <p className="small muted" style={{ margin: '0 0 8px' }}>
            {rows.length.toLocaleString()} row{rows.length === 1 ? '' : 's'}
            {rows.length !== data.length && ` of ${data.length.toLocaleString()}`}
            {' · tap a column to sort'}
          </p>

          <div className="table-wrap">
            <table className="data">
              <thead>
                {table.getHeaderGroups().map(hg => (
                  <tr key={hg.id}>
                    {hg.headers.map(h => (
                      <th key={h.id} onClick={h.column.getToggleSortingHandler()}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {{ asc: ' ▲', desc: ' ▼' }[h.column.getIsSorted()] ?? ''}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map(r => (
                  <tr key={r.id}>
                    {r.getVisibleCells().map(c => (
                      <td key={c.id} className={typeof c.getValue() === 'number' ? 'num' : ''}>
                        {flexRender(c.column.columnDef.cell, c.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pager">
            <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>Previous</button>
            <span className="muted">
              Page {table.getState().pagination.pageIndex + 1} of {Math.max(1, table.getPageCount())}
            </span>
            <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>Next</button>
          </div>
        </>
      )}
    </Section>
  )
}
