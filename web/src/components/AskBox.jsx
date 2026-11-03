import { useState } from 'react'
import { loadTable, loadTableIfPresent, loadSeasons, useAsync } from '../lib/data.js'
import { askAvailable, askContext, fetchSpec } from '../lib/ask.js'
import { runSpec, personaliseHeadline, QueryError } from '../lib/queryExec.js'
import { Collapsible } from './ui.jsx'

/**
 * Natural-language questions over the Explorer tables.
 *
 * The question goes to the trigger worker's /ask endpoint, which has Claude
 * turn it into a structured query spec; the spec is executed HERE, over the
 * season JSON this page already loads (lib/queryExec.js). The model never sees
 * the data and never writes the numbers — every figure in the answer is a real
 * row, and "Show the query" proves it.
 *
 * Renders nothing at all when VITE_ASK_ENDPOINT is unset: the feature is
 * optional and the static site must not error over it.
 */

const EXAMPLES = [
  'who has left the most points on the bench?',
  'which waiver requests got rejected?',
  'top scorers in gameweek 1',
]

const CROSS_SEASON_EXAMPLE = 'which players get drafted season after season?'

const ERROR_TEXT = {
  busy: 'The question service is busy right now — give it a minute and try again.',
  budget: 'This month’s question budget is used up. The tables below still work.',
  bad_question: 'That question couldn’t be sent — try rephrasing it, in under 300 characters.',
  unavailable: 'The question service isn’t reachable right now. The tables below still work.',
}

export default function AskBox({ season, meta }) {
  const [question, setQuestion] = useState('')
  const [state, setState] = useState({ status: 'idle' })
  // The seasons index is one tiny fetch (already cached for the selector); it
  // lets questions span seasons. null just means single-season answers.
  const index = useAsync(() => loadSeasons().catch(() => null), [])

  if (!askAvailable()) return null

  const publishedSeasons = (index.data?.seasons ?? []).map(s => ({ id: s.season, label: s.label }))

  async function submit(text) {
    const asked = (text ?? question).trim()
    if (!asked || state.status === 'loading') return
    if (text) setQuestion(text)
    setState({ status: 'loading' })
    try {
      const spec = await fetchSpec(asked, askContext(meta, season, index.data))
      const { rows, headline } = await runSpec(
        spec,
        // Cross-season loads tolerate a season missing the table (2425 has no
        // trades); the selected season still fails loudly so a real outage
        // isn't mistaken for "no data".
        (name, s) => (s == null ? loadTable(season, name) : loadTableIfPresent(s, name)),
        { seasons: publishedSeasons },
      )
      setState({ status: 'done', rows, headline: personaliseHeadline(headline, meta?.drafters), spec })
    } catch (err) {
      if (err instanceof QueryError) {
        // The model said no (answerable: false) or produced a spec the
        // executor refused — either way, a sentence, never a broken table.
        setState({ status: 'unanswerable', reason: err.message })
      } else {
        setState({ status: 'error', code: err?.code ?? 'unavailable' })
      }
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      <form
        onSubmit={e => { e.preventDefault(); submit() }}
        style={{ display: 'flex', gap: 6 }}
      >
        <input
          type="search"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="Ask the data a question…"
          maxLength={300}
          aria-label="Ask a question about the season"
          style={{ flex: 1 }}
        />
        <button type="submit" className="chip" disabled={state.status === 'loading'}>
          {state.status === 'loading' ? 'Asking…' : 'Ask'}
        </button>
      </form>

      {state.status === 'idle' && (
        <div className="chips" style={{ marginTop: 6 }}>
          {[...EXAMPLES,
            // Only tempt people across seasons where there is more than one.
            ...(publishedSeasons.length > 1 ? [CROSS_SEASON_EXAMPLE] : []),
          ].map(example => (
            <button key={example} type="button" className="chip" onClick={() => submit(example)}>
              {example}
            </button>
          ))}
        </div>
      )}

      {state.status === 'loading' && <div className="spinner">Working out the query…</div>}

      {state.status === 'error' && (
        <div className="notice" style={{ marginTop: 8 }}>
          {ERROR_TEXT[state.code] ?? ERROR_TEXT.unavailable}
        </div>
      )}

      {state.status === 'unanswerable' && (
        <div className="notice" style={{ marginTop: 8 }}>
          <strong>Can&apos;t answer that one.</strong> {state.reason}{' '}
          <span className="muted">Try the tables below instead.</span>
        </div>
      )}

      {state.status === 'done' && (
        <div style={{ marginTop: 8 }}>
          {state.headline && <p style={{ margin: '0 0 8px', fontWeight: 650 }}>{state.headline}</p>}
          {state.rows.length === 0 ? (
            <p className="small muted">No matching rows — the question may be too specific for this season.</p>
          ) : (
            <ResultTable rows={state.rows} />
          )}
          <Collapsible title="Show the query" summary={`${state.spec.table} · ${state.rows.length} row${state.rows.length === 1 ? '' : 's'}`}>
            <p className="small muted">
              The question was translated into this query and run over the local{' '}
              <code>{state.spec.table}</code> table — every number above is a real row.
            </p>
            <pre className="small" style={{ overflowX: 'auto' }}>
              {JSON.stringify({
                table: state.spec.table,
                seasons: state.spec.seasons ?? undefined,
                where: state.spec.where,
                group_by: state.spec.group_by,
                aggregate: state.spec.aggregate,
                sort: state.spec.sort,
                limit: state.spec.limit,
              }, null, 2)}
            </pre>
          </Collapsible>
        </div>
      )}
    </div>
  )
}

function ResultTable({ rows }) {
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))]
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>{keys.map(key => <th key={key}>{key.replace(/_/g, ' ')}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {keys.map(key => {
                const value = row[key]
                return (
                  <td key={key} className={typeof value === 'number' ? 'num' : ''}>
                    {value == null ? <span className="muted">–</span>
                      : typeof value === 'number' ? Math.round(value * 100) / 100
                      : String(value)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
