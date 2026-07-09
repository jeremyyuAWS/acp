import { useState, useEffect, useRef } from 'react'
import { updateHitlItem, getFileRemediationDiffs } from './api.js'
import { confClass } from './confidence.js'
import Thumbnail from './Thumbnail.jsx'
import { buildEvidenceCard } from './reviewCard.js'

// Evidence Card (PRD v2) — a PR-style review of ONE accessibility issue. The human APPROVES
// ACP's recommendation; ACP applies it. Assembles only shipped primitives (confidence basis,
// remediationTrack, remediation_diff, thumbnail) and records review telemetry (edited flag +
// review time) so the workspace can report reviewer time saved and calibrate confidence.
//
// onResolved(id, status) — parent refreshes the queue (drain stays wired via acp:hitl-changed).
export default function EvidenceCard({ item, onResolved }) {
  const [diffs, setDiffs] = useState([])
  const [value, setValue] = useState(item?.approved_value ?? '')
  const [busy, setBusy] = useState(false)
  const shownAt = useRef(Date.now())               // reviewer-time metric starts when the card mounts
  const aiDraft = useRef(item?.approved_value ?? null)

  useEffect(() => {
    let live = true
    if (item?.scan_id && item?.file) {
      getFileRemediationDiffs(item.scan_id, item.file).then((r) => { if (live) setDiffs(r || []) }).catch(() => {})
    }
    return () => { live = false }
  }, [item?.scan_id, item?.file])

  const card = buildEvidenceCard(item, diffs)
  const editable = card.track.track !== 'auto' && aiDraft.current != null   // a value the reviewer can edit
  const primaryLabel = card.track.action                                    // "Approve & Apply" | "Review & edit"

  const decide = async (status) => {
    if (busy) return
    setBusy(true)
    const finalVal = editable && status === 'approved' ? (value || null) : null
    const edited = editable && status === 'approved' && (value || '') !== (aiDraft.current || '')
    try {
      await updateHitlItem(card.id, status, null, finalVal, {
        edited, reviewMs: Date.now() - shownAt.current, aiValue: aiDraft.current,
      })
      onResolved && onResolved(card.id, status)
    } finally {
      setBusy(false)
    }
  }

  const b = card.confidence
  return (
    <section className="evcard" aria-label={`Review ${card.wcag}`}
             style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 12, background: 'var(--card, #fff)' }}>
      <header className="evcard-hd" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span className="fmtchip">{card.fmt}</span>
        <b className="evcard-wcag">{card.wcag}</b>
        <span className="muted">{card.name}</span>
        <span className={`conf conf-${card.track.badge.tone}`} style={{ marginLeft: 'auto' }}>{card.track.badge.label}</span>
      </header>

      <div className="evcard-body" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {card.scanId && card.file && <Thumbnail scanId={card.scanId} file={card.file} className="evcard-thumb" />}
        <div className="evcard-main" style={{ flex: 1, minWidth: 0 }}>
          <p className="evcard-problem">{card.problem}</p>

          {editable ? (
            <label className="evcard-rec">
              <span className="muted" style={{ fontSize: 12 }}>AI recommendation {aiDraft.current ? '(edit before approving if needed)' : ''}</span>
              <textarea className="evcard-rec-input" rows={2} value={value} onChange={(e) => setValue(e.target.value)} />
            </label>
          ) : card.recommendation ? (
            <p className="evcard-rec-static"><b>AI recommendation:</b> {card.recommendation}</p>
          ) : null}

          {b && (
            <p className="evcard-why">
              <span className={confClass(b.level)}>{b.level.label} confidence</span>
              <span className="muted"> · why: {b.basis}</span>
            </p>
          )}

          {card.diffs.length > 0 && (
            <div className="evcard-ba">
              {card.diffs.slice(0, 1).map((d, i) => (
                <div key={i}>
                  <div className="diffbox before"><span className="difftag">before</span>{d.before}</div>
                  <div className="diffbox after"><span className="difftag">after</span>{d.after}</div>
                </div>
              ))}
            </div>
          )}

          <p className="evcard-impact muted" style={{ fontSize: 12 }}>
            Compliance: <span className="conf conf-low">{card.impact.before}</span> → <span className="conf conf-high">{card.impact.after}</span> after approval
          </p>

          <div className="evcard-actions">
            <button className="qbtn approve" disabled={busy} onClick={() => decide('approved')}>✓ {primaryLabel}</button>
            <button className="qbtn reject" disabled={busy} onClick={() => decide('rejected')}>✕ Reject</button>
            <button className="ghost small" disabled={busy} onClick={() => decide('skipped')}>Skip</button>
          </div>
        </div>
      </div>
    </section>
  )
}
