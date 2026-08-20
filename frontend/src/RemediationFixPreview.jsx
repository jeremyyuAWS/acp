import GroundedBeforeAfter from './GroundedBeforeAfter.jsx'
import { fixPreviewModel } from './fixPreview.js'

// R4 · Preview — before/after for ONE proposed fix, framed so a reviewer can decide.
//
// The picture is NOT re-implemented here. `GroundedBeforeAfter` renders it, from the finding's own
// before/after fields, and this is the presentation layer the redesign asks for around it: the four
// fixed drawer sections — Problem · Evidence · Proposed resolution · Decision — with the fix MODE
// stated explicitly rather than left to be inferred from which button is showing
// (docs/remediate-redesign-spec.md, "Target layout" §3, and change #5: no generic Approve/Reject).
//
// Three things it refuses to do, each because the shipped code says otherwise:
//   • It never shows an Approve button for a mode that has nothing to approve. A guided or
//     human-authored fix gets guidance and a "mark resolved" affordance, per spec §3.
//   • It never claims the drive is untouched. `get_drive_mirror_enabled()` defaults TRUE, so a
//     corrected COPY is written into the drive's mirror folder on a default deployment (ADR 0010);
//     with the setting unread, the destination line is simply absent (fixPreview.destinationOf).
//   • It never presents a not-yet-computed value as a proposal. `proposed.known === false` prints
//     what will happen, framed as such (ADR 0016).
//
// Presentation only: every decision control is optional and renders solely when its handler is
// passed, so this composes with the approval queue rather than competing with it.

const SECTION = { margin: '0 0 18px' }
const H = {
  margin: '0 0 8px', fontSize: 10.5, fontWeight: 700, letterSpacing: '.08em',
  textTransform: 'uppercase', color: 'var(--muted,#8a8f98)',
}
const CARD = {
  border: '1px solid var(--line,#e2dce4)', borderRadius: 10, padding: '12px 14px',
  background: 'var(--surface,#fff)',
}
const MODE_TONE = {
  auto: { bg: 'var(--ok-bg,#eafaef)', ink: 'var(--ok-ink,#217a3b)', line: 'var(--ok-line,#bfe3c9)' },
  draft: { bg: '#eef3fe', ink: '#2f6fed', line: '#c5d6fb' },
  guided: { bg: '#fdf3e3', ink: '#8a5d0f', line: '#eeddba' },
  human: { bg: '#f6f5f8', ink: '#5c5566', line: '#e2dce4' },
  blocked: { bg: '#fbeceb', ink: '#a33b28', line: '#eec5bf' },
}

function ModeBadge({ mode }) {
  const t = MODE_TONE[mode.tone] || MODE_TONE.human
  return (
    <span className={`fixmode fixmode-${mode.key}`} style={{
      display: 'inline-block', padding: '4px 11px', borderRadius: 999, fontSize: 12.5, fontWeight: 700,
      background: t.bg, color: t.ink, border: `1px solid ${t.line}`,
    }}>{mode.label}</span>
  )
}

function Row({ label, children }) {
  return (
    <p style={{ margin: '0 0 4px', fontSize: 13 }}>
      <span className="muted" style={{ color: 'var(--muted,#8a8f98)' }}>{label} </span>{children}
    </p>
  )
}

// Section 3's value. Three genuinely different states, and the third is the one that matters:
// a fix whose value is decided when it runs has no wording to review, and pretending otherwise
// is how a placeholder gets approved as if it were a proposal.
function ProposedValue({ model }) {
  const { proposed, mode } = model
  if (proposed.known) {
    return (
      <div className="fixpreview-value" style={{ ...CARD, background: 'var(--surface-2,#f6f5f8)', fontSize: 13.5 }}>
        {proposed.value}
      </div>
    )
  }
  if (mode.key === 'automatic') {
    return (
      <p className="fixpreview-novalue muted" style={{ margin: 0, fontSize: 13 }}>
        The value is computed from the document when the fix runs, so there is no wording to review here.
      </p>
    )
  }
  return (
    <p className="fixpreview-novalue muted" style={{ margin: 0, fontSize: 13 }}>
      No value has been drafted for this finding.
    </p>
  )
}

function Steps({ steps }) {
  if (!steps) return null
  return (
    <div className="fixpreview-steps" style={{ ...CARD, marginTop: 10, fontSize: 13 }}>
      {steps.where && <p style={{ margin: '0 0 8px' }}>{steps.where}</p>}
      <p style={{ margin: '0 0 6px' }}><strong>macOS</strong> — {steps.mac}</p>
      <p style={{ margin: 0 }}><strong>Windows</strong> — {steps.win}</p>
      {!steps.specific && (
        <p className="muted" style={{ margin: '8px 0 0', fontSize: 12 }}>
          These are the application’s general accessibility-checker steps — ACP has no
          criterion-specific path recorded for this one.
        </p>
      )}
    </div>
  )
}

// Only ever rendered from real applied/verified state, never from a drafted value.
function AppliedChips({ model }) {
  if (!model.applied) return null
  const chip = {
    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600,
    padding: '3px 9px', borderRadius: 999, border: '1px solid var(--ok-line,#bfe3c9)',
    background: 'var(--ok-bg,#eafaef)', color: 'var(--ok-ink,#217a3b)',
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      <span className="fixpreview-applied" style={chip}><span aria-hidden="true">✓</span> Written to the corrected copy</span>
      {model.verified && (
        <span className="fixpreview-verified" style={chip}><span aria-hidden="true">✓</span> Re-scan confirmed it cleared</span>
      )}
    </div>
  )
}

// Spec change #5: the action names the thing it does. There is no generic Approve/Reject, and a
// control appears only when the parent actually wired a handler for it.
function Decision({ model, onApply, onApprove, onMarkResolved, onDefer, onNotApplicable, busy }) {
  const primary = model.mode.key === 'automatic' && onApply ? { label: 'Apply fix', fn: onApply }
    : model.mode.key === 'ai-draft' && onApprove ? { label: 'Approve this wording', fn: onApprove }
      : (model.mode.key === 'guided' || model.mode.key === 'human') && onMarkResolved
        ? { label: 'Mark resolved manually', fn: onMarkResolved } : null
  const secondary = [
    onDefer && { label: 'Defer', fn: onDefer },
    onNotApplicable && { label: 'Not applicable', fn: onNotApplicable },
  ].filter(Boolean)
  if (!primary && secondary.length === 0) return null
  return (
    <section style={SECTION}>
      <h4 style={H}>Decision</h4>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {primary && (
          <button className="btn primary fixpreview-primary" disabled={!!busy} onClick={primary.fn}>{primary.label}</button>
        )}
        {secondary.map((a) => (
          <button key={a.label} className="btn fixpreview-secondary" disabled={!!busy} onClick={a.fn}>{a.label}</button>
        ))}
      </div>
    </section>
  )
}

export default function RemediationFixPreview({
  finding, scanId = null, cap = null, fmt = null, driveMirror = null,
  onApply = null, onApprove = null, onMarkResolved = null, onDefer = null, onNotApplicable = null,
  busy = false,
}) {
  const model = fixPreviewModel(finding, { cap, fmt, driveMirror })
  if (!model) {
    return (
      <div className="fixpreview fixpreview-empty">
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>Select a finding to see what its fix would change.</p>
      </div>
    )
  }
  const { criterion } = model
  return (
    <div className="fixpreview">
      {/* 1 · Problem — plain language first, the rule identifier below it (spec change #9). */}
      <section style={SECTION}>
        <h4 style={H}>Problem</h4>
        <p style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 600 }}>{model.issue}</p>
        {criterion.requirement && (
          <p className="muted" style={{ margin: '0 0 8px', fontSize: 13 }}>{criterion.requirement}</p>
        )}
        {criterion.sc && (
          <Row label="Criterion">
            {criterion.sc}{criterion.name ? ` · ${criterion.name}` : ''}
          </Row>
        )}
        {model.severity && <Row label="Severity">{model.severity}</Row>}
        {model.file && <Row label="Document">{model.file}</Row>}
        {model.location && <Row label="Location">{model.location}</Row>}
      </section>

      {/* 2 · Evidence — the existing grounded renderer, unchanged. */}
      <section style={SECTION}>
        <h4 style={H}>Evidence</h4>
        <GroundedBeforeAfter finding={finding} scanId={scanId} />
      </section>

      {/* 3 · Proposed resolution — the mode said out loud, then what it would write. */}
      <section style={SECTION}>
        <h4 style={H}>Proposed resolution</h4>
        <div style={{ marginBottom: 8 }}><ModeBadge mode={model.mode} /></div>
        <p style={{ margin: '0 0 4px', fontSize: 13 }}>{model.mode.help}</p>
        <p className="fixpreview-basis muted" style={{ margin: '0 0 10px', fontSize: 12 }}>
          Because {model.mode.basis}.
        </p>
        {model.mode.key !== 'blocked' && <ProposedValue model={model} />}
        {model.change && (
          <p className="fixpreview-change" style={{ margin: '10px 0 0', fontSize: 13 }}>{model.change}</p>
        )}
        <Steps steps={model.steps} />
        <AppliedChips model={model} />
      </section>

      {/* What applying it does. ADR 0010 — the destination is read from the real setting, and when
          the setting has not been read this block says nothing about the drive rather than guessing
          the reassuring answer. */}
      {model.mode.key !== 'blocked' && (
        <section style={SECTION}>
          <h4 style={H}>What applying it does</h4>
          <p className="fixpreview-dest" style={{ margin: 0, fontSize: 13 }}>{model.destination.always}</p>
          {model.destination.drive && (
            <p className="fixpreview-dest-drive" style={{ margin: '4px 0 0', fontSize: 13 }}>{model.destination.drive}</p>
          )}
          {!model.destination.known && (
            <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>
              Where the copy is stored depends on a platform setting that has not been read yet.
            </p>
          )}
        </section>
      )}

      <Decision model={model} onApply={onApply} onApprove={onApprove} onMarkResolved={onMarkResolved}
                onDefer={onDefer} onNotApplicable={onNotApplicable} busy={busy} />

      {/* Spec change #9: the rule data sits one level below the human-readable problem. */}
      <details className="fixpreview-technical">
        <summary style={{ cursor: 'pointer', fontSize: 12.5, color: 'var(--muted,#8a8f98)' }}>Technical evidence</summary>
        <dl style={{ margin: '8px 0 0', fontSize: 12.5, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px' }}>
          <dt className="muted">Rule</dt><dd style={{ margin: 0 }}>{finding?.rule_id || finding?.ruleId || finding?.rule || '—'}</dd>
          <dt className="muted">Criterion</dt><dd style={{ margin: 0 }}>{model.sc || '—'}</dd>
          <dt className="muted">Format</dt><dd style={{ margin: 0 }}>{model.format ? model.format.toUpperCase() : '—'}</dd>
          <dt className="muted">Status</dt><dd style={{ margin: 0 }}>{finding?.status || '—'}</dd>
        </dl>
      </details>
    </div>
  )
}
