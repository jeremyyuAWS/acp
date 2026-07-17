import { useEffect, useState } from 'react'
import { getFileStatus, getScanStatus } from './api.js'

// ADR 0026 — the authoritative Accessibility Status hero. The FIRST thing a reviewer reads on a file:
// the decision (not the numbers), the coverage behind it, an honest account of what needs a human, a
// grounded estimate, and one CTA that launches the next step. Backend-driven (getFileStatus →
// derive_file_status) so it can never disagree with the coverage matrix. Never invents a % (ADR 0016);
// an automated pass reads "Automatically Verified", never "Certified".
//
// Vocabulary (ADR 0026): internal rigor, plain UI labels — the reviewer never sees "measured pass".

const STATE = {
  ready_for_certification: { glyph: '🟢', tone: 'ok', head: () => 'Ready for certification' },
  certified:               { glyph: '🟢', tone: 'ok', head: () => 'Certified' },
  ready_after_review:      { glyph: '🟡', tone: 'review', head: (n) => `Ready after ${n} review${n !== 1 ? 's' : ''}` },
  apply_approved_fixes:    { glyph: '🟡', tone: 'review', head: (n) => `${n} approval${n !== 1 ? 's' : ''} not yet applied` },
  needs_remediation:       { glyph: '🔴', tone: 'fail', head: (n) => `${n} issue${n !== 1 ? 's' : ''} need${n === 1 ? 's' : ''} remediation` },
  re_validating:           { glyph: '⟳', tone: 'busy', head: () => 'Re-validating…' },
  assessing:               { glyph: '⟳', tone: 'busy', head: () => 'Assessing…' },
}

// The five buckets → the segmented bar (semantic colour, separate from any brand accent).
const SEGMENTS = [
  { key: 'automatically_verified', label: 'Automatically Verified', cls: 'seg-auto' },
  { key: 'human_verified', label: 'Human Verified', cls: 'seg-human' },
  { key: 'needs_review', label: 'Needs Review', cls: 'seg-review' },
  { key: 'needs_remediation', label: 'Needs Remediation', cls: 'seg-fail' },
  { key: 'not_automatically_assessable', label: 'Not Automatically Assessable', cls: 'seg-na' },
]

function headCount(m) {
  if (m.state === 'ready_after_review') return m.needs_review
  if (m.state === 'apply_approved_fixes') return m.unapplied_approved
  if (m.state === 'needs_remediation') return m.needs_remediation
  return 0
}

function trustSentence(m) {
  const gaps = m.not_automatically_assessable
  switch (m.state) {
    case 'ready_for_certification':
    case 'certified':
      return gaps > 0
        ? `Every criterion ACP could check is accounted for; ${gaps} require manual verification.`
        : 'Every applicable WCAG criterion has been accounted for. No unresolved assessment gaps.'
    case 'ready_after_review':
      return `${m.needs_review} criterion${m.needs_review !== 1 ? 'a' : ''} still require human verification before certification.`
    case 'apply_approved_fixes':
      return 'Approved fixes haven’t been written to the document yet.'
    case 'needs_remediation':
      return `${m.needs_remediation} criterion${m.needs_remediation !== 1 ? 'a' : ''} ${m.needs_remediation === 1 ? 'is' : 'are'} failing and need a fix.`
    default:
      return 'ACP is still assessing this document.'
  }
}

function estimateLabel(secs) {
  if (!secs) return null
  if (secs < 90) return `~${Math.max(1, Math.round(secs / 60)) === 1 ? '1 min' : Math.round(secs / 60) + ' min'}`
  return `~${Math.round(secs / 60)} min`
}

// One component, every scope (ADR 0026 PR 3): pass `file` for the per-file card, omit it for the
// scan roll-up (per-file models summed server-side — the levels reconcile by construction).
export default function AccessibilityStatus({ scanId, file, onAction }) {
  const [m, setM] = useState(null)
  const [why, setWhy] = useState(false)

  useEffect(() => {
    let live = true
    setM(null)
    const fetchStatus = file ? getFileStatus(scanId, file) : getScanStatus(scanId)
    fetchStatus.then((r) => { if (live) setM(r || { available: false }) })
    return () => { live = false }
  }, [scanId, file])

  if (m && m.available === false) return null            // no scan/file → degrade silently
  const loading = !m
  const s = (m && STATE[m.state]) || STATE.assessing
  const busy = !m || s.tone === 'busy'
  const inScope = m ? m.in_scope : 0
  const est = m ? estimateLabel(m.est_review_secs) : null

  return (
    <div className={`acstatus acstatus-${s.tone}`} role="status"
      aria-label={file ? 'Accessibility status for this document' : 'Accessibility status for this scan'}>
      {/* Coverage — "did ACP look?" — distinct from status ("is it ready?") */}
      <div className="acstatus-coverage">
        <span className="acstatus-coverage-lbl">Assessment Coverage</span>
        <span className="acstatus-coverage-val">
          {loading ? '—' : `${m.coverage.evaluable} / ${m.coverage.total}`}
        </span>
      </div>

      {/* Decision first */}
      <div className="acstatus-head">
        <span className={`acstatus-glyph${busy ? ' spin' : ''}`} aria-hidden="true">{s.glyph}</span>
        <div className="acstatus-decision">
          <b>{loading ? 'Assessing…' : s.head(headCount(m))}</b>
          {!loading && !busy && (
            <span className="acstatus-resolved">
              {m.resolved} of {inScope} criteria resolved
              {m.documents > 1 ? ` across ${m.documents} documents` : ''}
            </span>
          )}
        </div>
        {est && !busy && <span className="acstatus-est" title="Based on the number of items awaiting review">Est. review {est}</span>}
      </div>

      {!loading && (
        <p className="acstatus-trust">
          {trustSentence(m)}
          {' '}
          <button type="button" className="acstatus-why-btn" aria-expanded={why}
            onClick={() => setWhy((v) => !v)}>ⓘ Why?</button>
        </p>
      )}

      {why && !loading && (
        <p className="acstatus-why muted" role="note">
          {m.automatically_verified} verified automatically.
          {m.needs_review > 0 && ` ${m.needs_review} require human judgement because WCAG defines no objective pass/fail test for them.`}
          {m.not_automatically_assessable > 0 && ` ${m.not_automatically_assessable} aren’t automatically assessable and need manual verification.`}
          {' '}Nothing has been skipped.
        </p>
      )}

      {/* Segmented progress bar — processed in under a second */}
      {!loading && inScope > 0 && (
        <>
          <div className="acstatus-bar" role="img"
            aria-label={SEGMENTS.filter((g) => m[g.key] > 0).map((g) => `${m[g.key]} ${g.label}`).join(', ')}>
            {SEGMENTS.map((g) => (m[g.key] > 0 &&
              <span key={g.key} className={`acstatus-seg ${g.cls}`}
                style={{ flexGrow: m[g.key] }} />
            ))}
          </div>
          <div className="acstatus-legend">
            {SEGMENTS.map((g) => (m[g.key] > 0 &&
              <span key={g.key} className="acstatus-legitem">
                <i className={g.cls} /> <b>{m[g.key]}</b> {g.label.replace('Automatically ', 'Auto ')}
              </span>
            ))}
          </div>
        </>
      )}

      {/* One dynamic, state-matched CTA — the workflow launcher */}
      {!loading && m.cta && (
        <button type="button" className="acstatus-cta" onClick={() => onAction && onAction(m.state)}>
          {m.cta}
        </button>
      )}
    </div>
  )
}
