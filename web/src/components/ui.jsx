/** Small shared pieces: league toggle, capability notice, loading, section wrapper. */

import { useEffect, useRef, useState } from 'react'

/**
 * Collapsible detail section.
 *
 * Every tab is "headline numbers first, detail on demand" — on a phone the old
 * report's wall of stacked charts meant scrolling past things you didn't want.
 * Uses native <details> so it works without JS and is keyboard/screen-reader
 * accessible for free.
 */
export function Collapsible({ title, summary, children, open = false, count }) {
  return (
    <details className="collapsible" open={open}>
      <summary>
        <span className="collapsible-title">{title}</span>
        {count != null && <span className="collapsible-count">{count}</span>}
        {summary && <span className="collapsible-summary">{summary}</span>}
      </summary>
      <div className="collapsible-body">{children}</div>
    </details>
  )
}

/** Headline figures that sit above the collapsibles on every tab. */
export function StatRow({ children }) {
  return <div className="stat-grid">{children}</div>
}

/** Sub-heading inside a collapsible, for when one section holds several charts. */
export function SubHead({ children, note }) {
  return (
    <div className="subhead">
      <h3>{children}</h3>
      {note && <p className="small muted">{note}</p>}
    </div>
  )
}

/** Segmented control, for picking a metric or breakdown within a section. */
export function Segmented({ options, value, onChange, ariaLabel }) {
  return (
    <div className="toggle wrap" role="group" aria-label={ariaLabel}>
      {options.map(o => (
        <button
          key={o.value}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          title={o.title}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function LeagueToggle({ meta, league, setLeague }) {
  // A site with a single league has nothing to toggle between — showing one
  // permanently-pressed button would just be furniture.
  if ((meta?.leagues?.length ?? 0) < 2) return null
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

/**
 * Modal, on native <dialog> — the same "let the platform do the a11y" choice as
 * Collapsible's <details>: showModal() brings focus trapping, Esc-to-close and
 * focus restore for free. Renders as a bottom sheet on a phone, a centred card
 * from 640px (see styles.css). Clicking the backdrop closes it: the backdrop is
 * the only click whose target is the <dialog> element itself.
 */
export function Modal({ title, onClose, children }) {
  const ref = useRef(null)
  // The latest onClose, read through a ref so the dialog effect can run exactly
  // once: re-running it on every parent render would close and re-open the
  // dialog, and the native close event can fire into the unlistened gap.
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return undefined
    if (!dialog.open) dialog.showModal()
    const requestClose = () => closeRef.current?.()
    // The native close event arrives a task late. In development, StrictMode
    // runs this effect's cleanup and then the effect again on mount, so the
    // cleanup's close() delivers its event to the re-shown dialog and shut the
    // modal a moment after it opened. A close event for a dialog that is open
    // again is that stale one, and is ignored.
    const onClosed = () => { if (!dialog.open) requestClose() }
    // Esc fires cancel-then-close per spec, but not every embedder delivers
    // either event, so every close path below also calls onClose directly and
    // the keydown fallback keeps Esc working everywhere. onClose unmounts the
    // modal, so a double delivery is harmless.
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); requestClose() } }
    dialog.addEventListener('close', onClosed)
    dialog.addEventListener('keydown', onKey)
    return () => {
      dialog.removeEventListener('close', onClosed)
      dialog.removeEventListener('keydown', onKey)
      if (dialog.open) dialog.close()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      className="modal"
      onClick={e => { if (e.target === ref.current) closeRef.current?.() }}
    >
      <div className="modal-head">
        <strong>{title}</strong>
        <button type="button" className="modal-close" aria-label="Close"
                onClick={() => closeRef.current?.()}>
          ×
        </button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
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
