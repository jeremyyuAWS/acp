import {
  VERIFY, NEXT, docCloseout, verifyLine, closeoutSummary, complianceRecord, nextStep,
  ASSESS_HANDOFF_NOTE,
} from './closeout.js'

// R12 · Close the loop — the three things an operator needs after delivery: did the fixes actually
// take, what got written down, and what happens next.
//
// Standalone, like DeliveryPanel: #551 rewrites Remediate.jsx, so a follow-up wires this in.
//
// The distinction this panel exists to hold: VERIFIED and UNVERIFIED are different, and neither is
// "failed". api/handlers.py credits an un-re-scannable fix so an infra hiccup does not penalise
// remediation — a sound storage decision that becomes an untrue UI the moment it is rendered as a
// green tick. So an unverified document is shown as unverified, in its own row, with its own
// count, and it is the FIRST thing the handoff sends you back to.

const TONE = {
  [VERIFY.CLEARED]: { mark: '✓', color: 'var(--success-fg)' },
  [VERIFY.STILL_FAILING]: { mark: '✕', color: '#8A1F1F' },
  [VERIFY.UNVERIFIED]: { mark: '?', color: 'var(--warn-fg)' },
  [VERIFY.NOT_REMEDIATED]: { mark: '·', color: 'var(--muted)' },
}

export default function CloseoutPanel({ docs = [], onReverify, onReview, onRemediate, onPublish }) {
  const summary = closeoutSummary(docs)
  const record = complianceRecord(summary)
  const next = nextStep(summary)
  const handler = { [NEXT.REVERIFY]: onReverify, [NEXT.REMEDIATE]: onRemediate, [NEXT.REVIEW]: onReview, [NEXT.PUBLISH]: onPublish }[next.key]

  return (
    <details className="panel rem-sec" data-testid="closeout-panel" aria-label="After delivery — verification, record and handoff">
      <summary className="rem-sec-sum">
        <h2 className="rem-sec-title">🔁 After delivery <span className="muted" style={{ fontSize: 12 }}>· what was verified, what was recorded, what is next</span></h2>
      </summary>
      <div className="rem-sec-body">

      {/* 1 · Re-verification. Counted separately because "cleared", "still failing" and "no
          evidence" answer different questions, and collapsing the third into either of the other
          two is how a fix nobody checked reaches a compliance report. */}
      <div data-testid="closeout-verification" style={{ marginTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Re-verification · the corrected copy was scanned again</div>
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13.5 }}>
          <span data-testid="count-cleared"><b style={{ color: 'var(--success-fg)', fontSize: 17 }}>{summary.cleared}</b> verified cleared</span>
          <span data-testid="count-still-failing"><b style={{ color: summary.stillFailing ? '#8A1F1F' : 'var(--muted)', fontSize: 17 }}>{summary.stillFailing}</b> still failing</span>
          <span data-testid="count-unverified"><b style={{ color: summary.unverified ? 'var(--warn-fg)' : 'var(--muted)', fontSize: 17 }}>{summary.unverified}</b> not verified</span>
          <span data-testid="count-pending-review" className="muted">
            {/* null is rendered as an absence. A queue nobody read is not an empty queue. */}
            {summary.pendingReview === null
              ? 'review queue not read'
              : <><b style={{ fontSize: 17 }}>{summary.pendingReview}</b> awaiting review</>}
          </span>
        </div>
        {summary.unverified > 0 && (
          <p data-testid="closeout-unverified-note" className="muted"
             style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 10, maxWidth: 680, padding: '8px 12px', borderRadius: 8, background: '#FBF1DF', border: '1px solid #EAD9BF', color: '#7A5A12' }}>
            ⚑ <b>{summary.unverified}</b> corrected {summary.unverified === 1 ? 'copy' : 'copies'} could not be re-scanned. The fixes were applied; nothing has confirmed they took. That is not a failure and it is not a pass — it is an absence of evidence, and it is the one state that must not be released.
          </p>
        )}
      </div>

      {summary.total > 0 && (
        <div data-testid="closeout-docs" style={{ marginTop: 14 }}>
          {summary.docs.map((d) => (
            <div key={d.file} data-testid="closeout-doc-row"
                 style={{ fontSize: 12.5, padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              <span style={{ color: TONE[d.state].color, fontWeight: 700, marginRight: 6 }} aria-hidden="true">{TONE[d.state].mark}</span>
              <b>{d.file}</b>
              <span className="muted"> · {verifyLine(d)}</span>
            </div>
          ))}
        </div>
      )}

      {/* 2 · The compliance record — what a later reader will find, named so they can find it. */}
      {record.length > 0 && (
        <div data-testid="closeout-record" style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Compliance record · what this run wrote down</div>
          <ul className="muted" style={{ fontSize: 12.5, lineHeight: 1.65, margin: 0, paddingLeft: 18, maxWidth: 700 }}>
            {record.map((r) => (
              <li key={r.key} data-testid={`record-${r.key}`}><b>{r.label}</b> — {r.detail}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 3 · The handoff. One step, the most blocking one. */}
      <div data-testid="closeout-next" style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Next</div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <b data-testid="closeout-next-label" style={{ fontSize: 13.5 }}>{next.label}</b>
          {handler && next.key !== NEXT.NOTHING && (
            <button className="qbtn approve" onClick={() => handler(summary)}>{next.label}</button>
          )}
        </div>
        <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 6, maxWidth: 700 }}>{next.detail}</p>
        {(next.key === NEXT.REVERIFY || next.key === NEXT.REMEDIATE) && (
          <p data-testid="closeout-assess-note" className="muted" style={{ fontSize: 12, lineHeight: 1.6, marginTop: 6, maxWidth: 700 }}>
            {ASSESS_HANDOFF_NOTE}
          </p>
        )}
      </div>
      </div>
    </details>
  )
}

export { docCloseout, closeoutSummary, nextStep }
