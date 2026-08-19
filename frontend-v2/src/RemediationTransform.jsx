import { laneOf, isResolved } from './remediationInboxModel.js'

// The centre-pane transform strip: Issue found → Proposed fix → Verified result. Three boxes and
// two arrows that show the reviewer the SHAPE of the change at a glance — the failing value, what
// ACP proposes, and what it becomes — before they read a word of prose. It is the visual anchor of
// "show me the problem → show me the change → show me the result".
//
// HONESTY (ADR 0016): the third box tells the truth about WHEN the result is real. A deterministic
// auto-fix (the review lane) or an already-resolved finding has been applied AND re-scanned, so it
// reads "Verified · Pass". An AI-drafted proposal (the apply lane) has NOT been applied yet, so it
// reads "Passes on re-scan" — a promise the re-validation step keeps, never a fabricated pass. It
// renders only when there IS a proposed/applied value; the caller shows the text before/after
// otherwise.

const TONES = {
  found:    { border: '#e6b0a6', bg: 'var(--found-bg,#fdeeec)', label: '#a33b28', icon: '🔍' },
  proposed: { border: '#c3b6ee', bg: 'var(--proposed-bg,#f2effc)', label: '#5b3bb1', icon: '✦' },
  verified: { border: '#a9d9c2', bg: 'var(--verified-bg,#e9f6f0)', label: '#1c7a55', icon: '✓' },
}

function Box({ tone, label, value }) {
  const t = TONES[tone]
  return (
    <div style={{ flex: '1 1 0', minWidth: 0, border: `1px solid ${t.border}`, background: t.bg,
                  borderRadius: 10, padding: '10px 12px', textAlign: 'center' }}>
      <div style={{ fontSize: 15, marginBottom: 4 }} aria-hidden="true">{t.icon}</div>
      <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: t.label }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4, wordBreak: 'break-word' }}>{value}</div>
    </div>
  )
}

const Arrow = () => (
  <span aria-hidden="true" style={{ flex: '0 0 auto', alignSelf: 'center', fontSize: 16, color: 'var(--muted,#8a8f98)' }}>→</span>
)

export default function RemediationTransform({ finding, decisions = {} }) {
  const after = finding?.after
  if (after == null || after === '') return null    // no proposed value → caller falls back to text before/after

  const lane = laneOf(finding)
  // Applied + re-scanned already? A deterministic auto-fix, or any finding a decision has resolved.
  const applied = lane.key === 'review' || isResolved(finding, decisions)
  const before = finding.before != null && finding.before !== '' ? String(finding.before) : 'Flagged'

  return (
    <div className="rem-transform" role="group" aria-label="Issue found, proposed fix, and verified result"
         style={{ display: 'flex', gap: 10, alignItems: 'stretch', flexWrap: 'wrap' }}>
      <Box tone="found" label="Issue found" value={before} />
      <Arrow />
      <Box tone="proposed" label="Proposed fix" value={String(after)} />
      <Arrow />
      <Box tone="verified" label={applied ? 'Verified result' : 'Expected result'}
           value={applied ? 'Pass' : 'Passes on re-scan'} />
    </div>
  )
}
