import { useId, useState } from 'react'
import './matching-review-preview.css'

const PAGE_SIZE = 5
const value = input => typeof input === 'string' && input.trim() ? input : typeof input === 'number' && Number.isFinite(input) ? String(input) : null

// This is an inspection surface only: paging never selects or approves a subset.
export default function MatchingReviewPreview({ findings = [] }) {
  const id = useId()
  const identity = JSON.stringify(findings.map(item => item.id))
  const [selection, setSelection] = useState(null)
  const pages = Math.max(1, Math.ceil(findings.length / PAGE_SIZE))
  const page = selection?.identity === identity ? Math.min(selection.page, pages - 1) : 0
  const start = page * PAGE_SIZE
  const choose = next => setSelection({ identity, page: next })
  return <section className="matching-review-preview" aria-labelledby={`${id}-heading`}>
    <h4 id={`${id}-heading`}>Other matching findings · {findings.length}</h4>
    <p className="muted">Inspect each proposal before a group decision. Paging changes only this preview; the group action still covers all matching findings and the selected item.</p>
    <ol start={start + 1}>
      {findings.slice(start, start + PAGE_SIZE).map(item => <li key={item.id}>
        <strong>{value(item.file) || 'File not recorded'}</strong>
        {value(item.severity) && <span className="matching-review-priority">Priority: {item.severity}</span>}
        <dl>
          <div><dt>Proposed change</dt><dd>{value(item.after) || 'No proposed value recorded'}</dd></div>
          <div><dt>Why suggested</dt><dd>{value(item.rationale) || 'No rationale recorded for this proposal.'}</dd></div>
        </dl>
      </li>)}
    </ol>
    {findings.length === 0 && <p>No other matching findings remain.</p>}
    {pages > 1 && <nav aria-label="Matching proposal pages">
      <button type="button" disabled={page === 0} onClick={() => choose(page - 1)}>Previous proposals</button>
      <span role="status">{start + 1}–{Math.min(start + PAGE_SIZE, findings.length)} of {findings.length} matching findings</span>
      <button type="button" disabled={page === pages - 1} onClick={() => choose(page + 1)}>Next proposals</button>
    </nav>}
  </section>
}
