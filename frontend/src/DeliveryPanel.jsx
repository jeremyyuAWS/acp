import { useState, useEffect } from 'react'
import { getSettings } from './api.js'
import {
  MIRROR, mirrorState, fileDelivery, destinationLine, destinationLabel,
  deliverySummary, summaryLine, replaceNote, COPY_GUARANTEE,
} from './deliveryPolicy.js'

// R11 · Delivery — "what happens to the fixed files", for the operator's ACTUAL configuration.
//
// Standalone by design: Remediate.jsx is being rewritten in #551, so this mounts nothing and is
// wired in by a follow-up once that lands. All of the wording lives in deliveryPolicy.js — see the
// header there for the code each claim was checked against.
//
// The one thing to preserve if this component is ever edited: the mirror setting has THREE states,
// and `settings === null` is the third. Seeding it to `{ drive_mirror_enabled: false }` — which is
// what Publish.jsx does — turns "we have not looked" into "your files are not going to Drive", and
// under the shipped default (store.py:4020, defaults TRUE) that is the wrong answer, delivered
// confidently, about the customer's own storage.
export default function DeliveryPanel({ files = [], settings: settingsProp, onDownload }) {
  // `undefined` prop → fetch it ourselves. An explicit `null` prop means "not read", and is
  // honoured as such: a caller can render the unread state deliberately.
  const [fetched, setFetched] = useState(null)
  const selfFetch = settingsProp === undefined
  useEffect(() => {
    if (!selfFetch) return undefined
    let live = true
    getSettings()
      .then((s) => { if (live && s && typeof s === 'object') setFetched(s) })
      // A failed read stays null. There is no half-answer to fall back to: the durable copy is
      // stated regardless, and the Drive half is simply not claimed.
      .catch(() => {})
    return () => { live = false }
  }, [selfFetch])

  const settings = selfFetch ? fetched : settingsProp
  const state = mirrorState(settings)
  const summary = deliverySummary(files, settings)
  const note = replaceNote(summary.deliveries)

  return (
    <section className="panel" data-testid="delivery-panel" aria-label="Delivery — where the corrected copies go">
      <div className="proghd">
        <h2 style={{ margin: 0 }}>📦 Delivery <span className="muted" style={{ fontSize: 12 }}>· where each fixed file ends up</span></h2>
      </div>

      {/* THE CLAIM. One element, one destination sentence, scoped so a vocabulary test can assert
          on what the screen actually promises without also reading the explanatory copy below. */}
      <p data-testid="delivery-destination" style={{ fontSize: 13.5, lineHeight: 1.6, margin: '12px 0 0', maxWidth: 660 }}>
        {summaryLine(summary)}
      </p>

      {/* The guarantee, held apart from the destination because it does not move with the setting. */}
      <p data-testid="delivery-guarantee" className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 8, maxWidth: 660 }}>
        {COPY_GUARANTEE}
      </p>

      {/* An unread setting is rendered as an absence, with the reason — not as an off switch. */}
      {state === MIRROR.UNREAD && summary.driveSourced > 0 && (
        <p data-testid="delivery-mirror-unknown" className="muted"
           style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 8, maxWidth: 660, padding: '8px 12px', borderRadius: 8, background: '#FBF1DF', border: '1px solid #EAD9BF', color: '#7A5A12' }}>
          ⚑ The Drive mirror setting has not been read, so this screen cannot tell you yet whether a
          copy also lands in your Drive. It is a platform setting, under Settings → Integrations.
        </p>
      )}

      {summary.total > 0 && (
        <div data-testid="delivery-files" style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
            Per document · {summary.total} {summary.total === 1 ? 'file' : 'files'}
          </div>
          {summary.deliveries.map((d) => (
            <div key={d.file} data-testid="delivery-row"
                 style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', fontSize: 12.5, padding: '5px 0', borderBottom: '1px solid var(--line)' }}>
              <b style={{ flex: '1 1 220px' }}>{d.file}</b>
              <span className="muted" data-testid="delivery-row-destination" title={destinationLine(d)}>→ {destinationLabel(d)}</span>
              {onDownload && (
                <button className="linklike" style={{ fontSize: 12 }} onClick={() => onDownload(d.file)}>
                  ⤓ Download
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Options. Explanatory, and deliberately NOT inside the claim element above: an operator
          reading "you can replace the original" must not be able to read it as something
          remediation did on their behalf. */}
      <details style={{ marginTop: 12 }}>
        <summary className="linklike" style={{ cursor: 'pointer', fontSize: 12.5 }}>What are my options for these copies?</summary>
        <ul data-testid="delivery-options" className="muted" style={{ fontSize: 12.5, lineHeight: 1.65, marginTop: 8, paddingLeft: 18, maxWidth: 660 }}>
          <li>Download the corrected copy from ACP. This is always available — the durable copy is the write that has to succeed for a remediation to count.</li>
          {state === MIRROR.ON && summary.driveSourced > 0 && (
            <li>Open it in Drive: it is in the “{summary.folder}” folder, next to the original. Re-running a remediation updates that copy rather than adding a second one.</li>
          )}
          {state === MIRROR.OFF && summary.driveSourced > 0 && (
            <li>Turn the Drive mirror on (Settings → Integrations) if you want future remediations to place a copy in the “{summary.folder}” folder automatically.</li>
          )}
          {note && <li>{note}</li>}
        </ul>
      </details>
    </section>
  )
}
