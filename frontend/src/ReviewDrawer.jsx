import { useEffect, useState } from 'react'
import Drawer from './Drawer.jsx'
import ProposalEditors, { seedValues } from './ProposalEditors.jsx'
import { proposalsOf } from './reviewCard.js'
import { scOf } from './fixSummary.js'

export default function ReviewDrawer({ item, onClose, onAct, onDraft }) {
  const [afterText, setAfterText] = useState(item?.after || '')
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState(null)
  // One editor per image. Approving now writes each value into the document at its own
  // locator, so the reviewer must see every picture they are describing — the single
  // `afterText` box below can only ever speak for the first one.
  const proposals = proposalsOf(item)
  const multi = proposals.length > 0
  const [values, setValues] = useState(() => seedValues(proposals))
  const setValueAt = (i, v) => setValues((prev) => prev.map((x, j) => (j === i ? v : x)))

  useEffect(() => {
    setAfterText(item?.after || '')
    setValues(seedValues(proposalsOf(item)))
    setDraftError(null)
  }, [item?.id])

  if (!item) return null
  const subtitle = item.file ? item.file + (item.rule ? ' · ' + item.rule : '') : item.meta

  const requestDraft = () => {
    if (!onDraft) return
    setDrafting(true); setDraftError(null)
    onDraft(item)
      .then((suggestion) => { if (suggestion) setAfterText(suggestion) })
      .catch((e) => setDraftError(e?.message || 'AI draft unavailable — is Ollama running?'))
      .finally(() => setDrafting(false))
  }

  return (
    <Drawer title={item.title} subtitle={subtitle} onClose={onClose}>
      {/* Honest escalation line — no fabricated confidence %. The AI exhausted its
          automated options; this item genuinely needs a person. */}
      <div className="muted" style={{ margin: '10px 0 6px', fontSize: 12.5 }}>
        ⚑ Escalated to you: {item.meta || 'this finding type needs human judgement'} — deterministic fixes ran first; this one needs your approval.
      </div>

      {multi ? (
        <>
          <h4 className="drawerh">Proposed fix &middot; one description per image</h4>
          <ProposalEditors proposals={proposals} values={values} sc={scOf(item.ruleId || item.rule)}
                           onChange={setValueAt} file={item.file} />
        </>
      ) : item.before && (
        <>
          <h4 className="drawerh">Proposed fix &middot; before &rarr; after</h4>
          <div className="diffbox before"><span className="difftag">before</span><code>{item.before}</code></div>
          {item.aiDraftable ? (
            <div className="diffbox after">
              <span className="difftag">after</span>
              <textarea
                className="draftedit"
                value={afterText}
                onChange={(e) => setAfterText(e.target.value)}
                rows={3}
                style={{ width: '100%', font: 'inherit', resize: 'vertical' }}
                placeholder="Edit the AI draft, or write the fix yourself"
              />
              {onDraft && (
                <button className="ghost" style={{ marginTop: 6, fontSize: 12 }} disabled={drafting} onClick={requestDraft}>
                  {drafting ? '✨ drafting…' : '✨ draft with AI'}
                </button>
              )}
              {draftError && <p className="muted" style={{ color: '#B23B3B', fontSize: 12, marginTop: 4 }}>{draftError}</p>}
            </div>
          ) : (
            <div className="diffbox after"><span className="difftag">after</span><code>{item.after}</code></div>
          )}
        </>
      )}

      <p className="muted" style={{ marginTop: 12 }}>{item.note || 'The agent proposes this fix; a human confirms because confidence is below the auto-apply threshold. Approving re-validates the file against all engines.'}</p>

      <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 16, flexWrap: 'wrap' }}>
        {/* With per-image editors the array is what gets written; the headline value stays the
            first image's text so the audit log and telemetry keep recording what was approved. */}
        <button onClick={() => (multi
          ? onAct(item.id, 'approved', values[0], values)
          : onAct(item.id, 'approved', item.aiDraftable ? afterText : undefined))}>&#10003; approve fix</button>
        <button className="ghost" onClick={() => onAct(item.id, 'self')}>&#9995; I&apos;ll fix it myself</button>
        <button className="ghost" style={{ color: '#1F5FA8' }} onClick={() => onAct(item.id, 'deferred')}>&#9208; defer to next cycle</button>
        <button className="ghost" onClick={() => onAct(item.id, 'rejected')}>&#10005; reject</button>
      </div>
      <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Defer if the fix needs more information or belongs in a later remediation batch &mdash; it resurfaces on the next scheduled scan.</p>
    </Drawer>
  )
}
