import { useEffect, useRef, useState } from 'react'
import { undoAppliedFix } from './api.js'

// R15 · Undo an applied deterministic fix.
//
// THERE IS NOTHING TO RESTORE ON THE DOCUMENT. Remediation never overwrites the source — it only
// ever produces a separate corrected copy (see RemediationWork's own safety statement: "Your
// original documents are never modified"). So this is not a file-undo, and the copy in front of
// this control does not un-exist. What "undo" clears is ACP's OWN claim that the finding is fixed —
// once cleared, the finding reappears in the worklist exactly as if the fix had never run, and
// applying fixes again later will fix it again, deterministically, like any other open finding.
//
// SCOPED TO ONE FINDING, NOT A BATCH. "Undo a batch" (board 10, R13-24) as a single action across
// everything one "Apply N fixes" click touched needs a batch id nothing today records — this is the
// buildable half: one fix, one undo, always available, no new schema.
//
// ONLY OFFERED FOR AN AUTO-APPLIED ROW. `sel.autoApplied` is how the shared inbox queue already
// marks these (remediationInboxModel.js) — a drafted-AI or manually-authored finding was never
// something ACP applied on its own, so there is nothing here to un-claim for those rows.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

/**
 * @param scanId  the scan the finding belongs to.
 * @param file    the document the fix was applied to.
 * @param ruleId  the criterion the fix cleared (autoFixRows' `ruleId`/`rule_id`).
 * @param onUndone  called after a successful undo, so the parent can refresh the queue —
 *                  this component does not know how to re-fetch anything itself.
 */
export default function UndoFix({ scanId, file, ruleId, onUndone }) {
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState('')
  const live = useRef(true)

  // Re-arm when the selected finding changes — this component is reused across selections, so a
  // stale "Undone" from the previous row must not paint onto the next one.
  useEffect(() => { setDone(false); setErr('') }, [scanId, file, ruleId])
  useEffect(() => () => { live.current = false }, [])

  if (!scanId || !file || !ruleId) return null

  const undo = () => {
    setBusy(true); setErr('')
    undoAppliedFix(scanId, file, ruleId)
      .then((r) => {
        if (!live.current) return
        if (r && r.undone === false) {
          setErr('Nothing to undo — ACP is not currently claiming this fix.')
        } else {
          setDone(true)
          onUndone && onUndone()
        }
      })
      .catch((e) => { if (live.current) setErr(e?.message || 'could not undo this fix') })
      .finally(() => { if (live.current) setBusy(false) })
  }

  return (
    <section className="panel undo-fix" role="region" aria-label="Undo this fix"
             style={{ marginBottom: 14 }}>
      <div style={kicker}>Applied automatically</div>
      {done ? (
        <p style={{ ...muted, marginTop: 6 }}>
          Undone — ACP no longer counts this as fixed. Running Apply fixes again will fix it the
          same way, deterministically, like any other open finding.
        </p>
      ) : (
        <>
          <p style={{ ...muted, marginTop: 6 }}>
            Your original document was never modified — ACP produced a corrected copy. Undo stops
            counting this finding as fixed; it does not touch any file.
          </p>
          <button type="button" className="ghost small" disabled={busy} onClick={undo}
                  style={{ marginTop: 8 }}>
            {busy ? 'Undoing…' : 'Undo this fix'}
          </button>
        </>
      )}
      {err && <p style={{ ...muted, marginTop: 8, color: 'var(--red, #b23b3b)' }}>{err}</p>}
    </section>
  )
}
