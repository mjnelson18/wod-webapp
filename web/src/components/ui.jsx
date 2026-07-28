/** Small shared pieces: league toggle, capability notice, loading, section wrapper. */

export function LeagueToggle({ meta, league, setLeague }) {
  if (!meta?.leagues?.length) return null
  return (
    <div className="toggle" role="group" aria-label="League">
      {meta.leagues.map(l => (
        <button
          key={l.code}
          aria-pressed={league === l.code}
          onClick={() => setLeague(l.code)}
        >
          {l.name}
        </button>
      ))}
    </div>
  )
}

/**
 * Graceful degradation. Older seasons lack columns the current season has, so a
 * view renders this instead of erroring or showing an empty chart.
 */
export function Unavailable({ what, season, reason }) {
  return (
    <div className="notice">
      <strong>{what}</strong> isn&apos;t available for {season}.
      {reason ? ` ${reason}` : ' That season\'s source data doesn\'t include the required columns.'}
    </div>
  )
}

export function Section({ title, note, children, aside }) {
  return (
    <section className="section">
      {(title || aside) && (
        <div className="section-head">
          {title && <h2>{title}</h2>}
          {note && <p>{note}</p>}
          {aside && <div style={{ marginLeft: 'auto' }}>{aside}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Loading({ what = 'data' }) {
  return <div className="spinner">Loading {what}…</div>
}

export function Stat({ label, value, sub }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

/** Shared Recharts tooltip so every chart reads the same. */
export function ChartTip({ active, payload, label, labelPrefix = 'GW', unit = '' }) {
  if (!active || !payload?.length) return null
  const rows = [...payload].sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  return (
    <div className="chart-tip">
      <div style={{ fontWeight: 650, marginBottom: 4 }}>{labelPrefix}{label}</div>
      {rows.map(p => (
        <div className="tip-row" key={p.dataKey}>
          <span>
            <span className="swatch" style={{ background: p.color ?? p.stroke }} />
            {p.name}
          </span>
          <b className="mono">{typeof p.value === 'number' ? Math.round(p.value * 10) / 10 : p.value}{unit}</b>
        </div>
      ))}
    </div>
  )
}
