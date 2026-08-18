import { scopeImpact } from './scopeImpact.js'

// The live population funnel for the Assess scope builder. As the operator changes document types
// or criteria, this redraws the narrowing — Discovered → Eligible → In-scope — with each stage's bar
// scaled to the discovered total and each DROP named underneath. Below it, a short "excluded"
// breakdown accounts for the files that fell out and why. Presentation only; all math is in
// scopeImpact.js so it is unit-tested directly.

const STAGE_COLOR = { discovered: '#8a8f98', eligible: '#2f6fed', inscope: '#1f9d6b' }

export default function ScopeImpact({ elig, formats = new Set(), loading = false }) {
  const impact = scopeImpact(elig, formats)
  if (!impact || impact.discovered === 0) return null
  const { discovered, funnel, excluded, pct } = impact

  return (
    <div className="scope-impact" style={{ marginTop: 12, border: '1px solid var(--line,#e2dce4)', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700 }}>Population funnel</span>
        <span className="muted" style={{ fontSize: 12 }}>
          {pct}% of the discovered estate is queued for this run{loading ? ' · updating…' : ''}
        </span>
      </div>

      {/* The narrowing — one bar per stage, scaled to the discovered total. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {funnel.map((s) => {
          const width = discovered ? Math.max(2, Math.round((s.count / discovered) * 100)) : 0
          return (
            <div key={s.key}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5 }}>
                <span style={{ fontWeight: 600 }}>{s.label}</span>
                <span style={{ marginLeft: 'auto', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {s.count.toLocaleString()}
                </span>
                {s.drop > 0 && (
                  <span className="muted" style={{ fontSize: 11.5, fontVariantNumeric: 'tabular-nums' }}>−{s.drop.toLocaleString()}</span>
                )}
              </div>
              <div role="progressbar" aria-valuenow={s.count} aria-valuemin={0} aria-valuemax={discovered}
                   aria-label={`${s.label}: ${s.count} of ${discovered} discovered`}
                   style={{ height: 7, borderRadius: 5, background: 'var(--line,#e2dce4)', overflow: 'hidden', marginTop: 3 }}>
                <div style={{ width: `${width}%`, height: '100%', background: STAGE_COLOR[s.key] || '#2f6fed' }} />
              </div>
              {s.note && <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{s.note}</div>}
            </div>
          )
        })}
      </div>

      {/* What fell out, and why. */}
      {excluded.length > 0 && (
        <div style={{ marginTop: 12, borderTop: '1px solid var(--line,#e2dce4)', paddingTop: 10 }}>
          <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 6 }}>Excluded from this run</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {excluded.map((x) => (
              <div key={x.key} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5 }}>
                <span style={{ fontWeight: 600, flex: '0 0 auto', fontVariantNumeric: 'tabular-nums' }}>{x.count.toLocaleString()}</span>
                <span style={{ minWidth: 0 }}>{x.label} <span className="muted">— {x.why}</span></span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
