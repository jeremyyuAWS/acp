// The sticky footer under the three-pane remediation workspace. Two jobs, matching the mockup:
//   1. Spell out the governing interaction — Show the problem → Review the proposed change → Verify
//      the result — so a first-time reviewer always sees the loop they are in. When `activeStep` is
//      given (0/1/2, or 3 for fully done) the guide stops being decorative: it lights the live step
//      for the current finding and checks off the ones behind it, so the loop reflects real state.
//   2. Give explicit Previous / N of M / Next navigation through the visible queue, complementing
//      click-to-select and the act()-driven auto-advance. This is pure NAVIGATION — it moves the
//      selection without acting on any finding — so a reviewer can walk the list to look before
//      they decide, and always knows where they are in it.

const STEPS = [
  { icon: '🔍', text: 'Show the problem', color: '#a33b28' },
  { icon: '✦', text: 'Review the proposed change', color: '#5b3bb1' },
  { icon: '✓', text: 'Verify the result', color: '#1c7a55' },
]

const MUTED = 'var(--muted,#8a8f98)'

export default function WorkspaceFooter({ position = 0, total = 0, onPrev, onNext, activeStep = null }) {
  const atStart = position <= 1
  const atEnd = total === 0 || position >= total

  return (
    <div className="rem-wsfoot" style={{
      display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginTop: 10,
      padding: '10px 14px', border: '1px solid var(--line,#e2dce4)', borderRadius: 12, background: 'var(--surface-2,#f6f5f8)',
    }}>
      <button type="button" className="ghost" onClick={onPrev} disabled={atStart} aria-label="Previous finding"
              style={{ opacity: atStart ? 0.5 : 1 }}>← Previous</button>

      {/* The workflow guide — the loop, spelled out; lit to the current finding's live step. */}
      <div role="list" aria-label="Remediation workflow" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', margin: '0 auto', fontSize: 12.5 }}>
        {STEPS.map((s, i) => {
          const state = activeStep == null ? 'plain' : i < activeStep ? 'done' : i === activeStep ? 'active' : 'pending'
          const active = state === 'active'
          const dim = state === 'done' || state === 'pending'
          return (
            <span key={s.text} role="listitem" aria-current={active ? 'step' : undefined}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 5,
                color: dim ? MUTED : s.color, fontWeight: active ? 700 : 600, opacity: state === 'pending' ? 0.7 : 1,
                padding: active ? '2px 8px' : undefined, borderRadius: active ? 999 : undefined,
                background: active ? 'var(--surface,#fff)' : undefined,
                boxShadow: active ? `inset 0 0 0 1px ${s.color}` : undefined,
              }}>
                <span aria-hidden="true">{state === 'done' ? '✓' : s.icon}</span>{s.text}
              </span>
              {i < STEPS.length - 1 && <span aria-hidden="true" style={{ color: MUTED }}>→</span>}
            </span>
          )
        })}
      </div>

      <span className="muted" style={{ fontSize: 12.5, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
        {total ? `${position} of ${total}` : '—'}
      </span>
      <button type="button" className="ghost" onClick={onNext} disabled={atEnd} aria-label="Next finding"
              style={{ opacity: atEnd ? 0.5 : 1 }}>Next →</button>
    </div>
  )
}
