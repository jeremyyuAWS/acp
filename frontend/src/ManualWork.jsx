import { useState } from 'react'
import { manualWork } from './manualWork.js'
import { defaultPlatform } from './verifySteps.js'

// R6 · Manual — the lane for work ACP cannot do itself.
//
// The other lanes end in a button. This one ends in a person opening a document, so the screen's job
// is different: not "approve this" but "here is what to change, in which file, and where the control
// lives in the app you will open it with". Everything below is either a real finding from the scan or
// a real menu path from `remediationGuide.js`; nothing here is generated prose about a document.
//
// THREE THINGS THIS SCREEN REFUSES TO SAY, each because the record cannot support it:
//
//   · It never says the estate is finished when this lane is empty. `manualWork` returns null for a
//     scan it has not been given, and null renders nothing at all — an empty manual lane over an
//     absent scan is not "no manual work", and a zero would read as one.
//   · It never presents the capability table's SILENCE as a judgement. A (format, criterion) pair the
//     table does not mention defaults to `human`, and those rows are marked as defaults rather than
//     folded in with the pairs an engineer actually declared manual. The count of them is printed.
//   · It never claims a time. There is no per-finding minute figure anywhere in this component, for
//     the same reason the assessment screen dropped its own: a constant times a count is not evidence.
//
// WHERE THE DOCUMENT IS. A file in this lane is opened from the customer's own source — this lane
// involves no ACP write at all, so there is no remediated copy to talk about and this component
// deliberately says nothing about output locations. (The one screen that must get that right is the
// batch, where the platform's Drive-mirror setting decides whether a corrected copy is also written
// into a "Remediated" folder in the source drive. That is not this screen's claim to make.)

const card = { border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }
const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

const SEV_TONE = { CRITICAL: '#A32D2D', SERIOUS: '#8A4B0B', MODERATE: '#5B5B5B', MINOR: '#5B5B5B' }

// The two ways a pair reaches this lane, in the words that distinguish them. `declared` is a
// statement about the fix; `default` is a statement about the table.
const BASIS_NOTE = {
  declared: 'ACP has no fixer for this criterion on this format — it is declared manual.',
  default: 'The capability table has no entry for this criterion on this format, so it falls to the '
         + 'conservative default. That is an absence of information, not a finding that a person is required.',
}

function CriterionBlock({ c, app }) {
  const [platform, setPlatform] = useState(defaultPlatform())
  const [open, setOpen] = useState(false)
  const steps = c.steps || {}
  const path = platform === 'mac' ? steps.mac : steps.win

  const seg = (p, label) => (
    <button type="button" className={platform === p ? 'seg on' : 'seg'} aria-pressed={platform === p}
            onClick={(e) => { e.preventDefault(); setPlatform(p) }}
            style={{ fontSize: 11.5, padding: '1px 9px' }}>{label}</button>
  )

  return (
    <div className="manual-criterion" style={{ borderTop: '1px solid var(--line)', padding: '10px 0' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)' }}>{c.label || `WCAG ${c.sc}`}</span>
        <span className="muted" style={{ fontSize: 11.5, fontVariantNumeric: 'tabular-nums' }}>WCAG {c.sc}</span>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: SEV_TONE[c.severity] || 'var(--muted)' }}>
          {String(c.severity || '').toLowerCase()}
        </span>
        <span className="muted" style={{ fontSize: 11.5 }}>
          · {c.findings.length} {c.findings.length === 1 ? 'place' : 'places'} in this document
        </span>
        {/* The default-basis rows are marked where they are, not only in the summary — a reader
            scanning one document must be able to see that this row rests on an absent table entry. */}
        {c.basis === 'default' && (
          <span className="manual-defaulted" style={{
            fontSize: 10.5, fontWeight: 700, letterSpacing: '.03em', textTransform: 'uppercase',
            color: '#6B5A1E', background: '#FBF1D4', borderRadius: 5, padding: '1px 6px',
          }}>no table entry</span>
        )}
      </div>

      {steps.where && <div style={{ ...muted, marginTop: 3 }}>{steps.where}</div>}
      <div style={{ ...muted, marginTop: 3 }}>{BASIS_NOTE[c.basis] || BASIS_NOTE.declared}</div>

      <button type="button" className="ghost small" style={{ marginTop: 6, fontSize: 12 }}
              aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? '▾' : '▸'} How to fix this in {app}
      </button>
      {open && (
        <div style={{ marginTop: 6 }}>
          <div role="group" aria-label="Platform" style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            {seg('mac', 'macOS')}
            {seg('win', 'Windows')}
          </div>
          <p style={{ fontSize: 12.5, lineHeight: 1.55, margin: 0 }}>{path}</p>
          {/* `fixSteps` always answers, falling back to the app's own Accessibility Checker. Saying
              which of the two this is keeps the generic answer from reading as bespoke guidance. */}
          {!c.specific && (
            <p className="muted" style={{ fontSize: 11.5, marginTop: 5, marginBottom: 0 }}>
              This is {app}&apos;s built-in checker rather than a path specific to WCAG {c.sc} — ACP has no
              criterion-specific instruction recorded for this one.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * @param files       the scan's file rows — the same array the assessment screen was given. Absent or
 *                    non-array renders NOTHING, which is the honest rendering of "not loaded yet".
 * @param cap         remediation-capability map {fmt: {sc: 'auto'|'assisted'|'human'}} from
 *                    GET /capability, or capability.js's bundled fallback.
 * @param assessment  assessment-lane map (ADR 0023), passed straight through to documentRows.
 * @param criteria    the agreed criteria; defaults to the active scope inside assessMetrics.
 * @param level       conformance target.
 */
export default function ManualWork({ files, cap, assessment, criteria, level = 'AA' }) {
  const w = manualWork(files, { cap, assessment, criteria, level })
  if (!w) return null

  const defaulted = w.defaultedPairs.length

  return (
    <section className="panel manualwork" aria-label="Manual remediation" role="region"
             style={{ marginBottom: 14 }}>
      <div style={kicker}>Manual remediation</div>
      <h2 style={{ margin: '4px 0 0', fontSize: 18 }}>Work a person has to do</h2>

      {w.documentCount === 0 ? (
        <p style={{ ...muted, marginTop: 8 }}>
          No finding in this scan falls to the manual lane. Every finding ACP recorded is either applied
          deterministically or drafted for someone to approve.
        </p>
      ) : (
        <p style={{ fontSize: 13.5, lineHeight: 1.55, marginTop: 8, marginBottom: 0 }}>
          <b style={{ fontVariantNumeric: 'tabular-nums' }}>{w.findingCount}</b>{' '}
          {w.findingCount === 1 ? 'finding' : 'findings'} across{' '}
          <b style={{ fontVariantNumeric: 'tabular-nums' }}>{w.documentCount}</b>{' '}
          {w.documentCount === 1 ? 'document' : 'documents'} cannot be fixed by ACP — no automatic fix
          and no draft to approve. Someone opens the document and writes the change.
        </p>
      )}

      {defaulted > 0 && (
        <p className="manual-defaults-note" style={{ ...muted, marginTop: 6 }}>
          {defaulted} of these {defaulted === 1 ? 'rows rests' : 'rows rest'} on an absent capability-table
          entry rather than a declared manual lane — marked <i>no table entry</i> below. ACP has not stated
          that a person is required for those; it has not stated anything.
        </p>
      )}

      {w.documents.map((d) => (
        <div key={d.file} className="manual-doc" style={{ ...card, marginTop: 12, padding: '11px 13px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13.5, fontWeight: 700, wordBreak: 'break-word' }}>{d.name}</span>
            <span className="muted" style={{ fontSize: 11.5 }}>
              {d.fmt ? `${d.fmt} · open in ${d.app}` : `open in ${d.app}`}
            </span>
          </div>
          <div style={{ ...muted, marginTop: 2 }}>
            {d.findingCount} manual {d.findingCount === 1 ? 'finding' : 'findings'}
            {/* Finishing this list does not finish the document, and saying so here is cheaper than
                a reader discovering it at Verify. */}
            {d.otherLaneFindings > 0 &&
              ` · ${d.otherLaneFindings} further ${d.otherLaneFindings === 1 ? 'finding' : 'findings'} on this document are handled by a remediation run, not by you`}
          </div>
          {d.criteria.map((c) => <CriterionBlock key={c.sc} c={c} app={d.app} />)}
        </div>
      ))}

      {w.unopened.length > 0 && (
        <p className="manual-unopened" style={{ ...muted, marginTop: 12 }}>
          {w.unopened.length} {w.unopened.length === 1 ? 'document was' : 'documents were'} never opened by
          the scanner, so {w.unopened.length === 1 ? 'it holds' : 'they hold'} no findings of any lane — not
          zero manual findings. {w.unopened.length === 1 ? 'It is' : 'They are'} not counted above.
        </p>
      )}
    </section>
  )
}
