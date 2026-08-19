import { scopeImpact, coverageGaps } from './scopeImpact.js'

// The live population funnel for the Assess scope builder. As the operator changes document types
// or criteria, this redraws the narrowing — Discovered → Eligible → In-scope — with each stage's bar
// scaled to the discovered total and each DROP named underneath. Below it, a short "excluded"
// breakdown accounts for the files that fell out and why. Beneath THAT, coverage-gap warnings call
// out the blind spots in the current selection — a criterion the operator ticked that has no
// assessment method for a document type they also ticked, so nothing there will ever be scored
// against it. Presentation only; all math is in scopeImpact.js so it is unit-tested directly.

const STAGE_COLOR = { discovered: '#8a8f98', eligible: '#2f6fed', inscope: '#1f9d6b', assessed: '#0f766e' }
const FORMAT_LABEL = { docx: 'Word', pdf: 'PDF', pptx: 'PowerPoint', xlsx: 'Excel' }
const fmtLabel = (f) => FORMAT_LABEL[f] || f.toUpperCase()
const setSize = (s) => (s instanceof Set ? s.size : Array.isArray(s) ? s.length : 0)

export default function ScopeImpact({ elig, formats = new Set(), codeset = [], codes = new Set(), loading = false }) {
  const impact = scopeImpact(elig, formats)
  const gaps = coverageGaps(codeset, codes, formats)
  const hasFunnel = !!impact && impact.discovered > 0
  // A reassurance line only makes sense once the operator has actually made a selection to reassure
  // about — otherwise "every selected criterion has a method" is vacuously (and misleadingly) true.
  const hasSelection = setSize(codes) > 0 && setSize(formats) > 0
  if (!hasFunnel && gaps.length === 0) return null

  return (
    <div className="scope-impact" style={{ marginTop: 12, border: '1px solid var(--line,#e2dce4)', borderRadius: 10, padding: '12px 14px' }}>
      {hasFunnel && (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12.5, fontWeight: 700 }}>Population funnel</span>
            <span className="muted" style={{ fontSize: 12 }}>
              {impact.pct}% of the discovered estate is queued for this run{loading ? ' · updating…' : ''}
            </span>
          </div>

          {/* The narrowing — one bar per stage, scaled to the discovered total. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {impact.funnel.map((s) => {
              const width = impact.discovered ? Math.max(2, Math.round((s.count / impact.discovered) * 100)) : 0
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
                  <div role="progressbar" aria-valuenow={s.count} aria-valuemin={0} aria-valuemax={impact.discovered}
                       aria-label={`${s.label}: ${s.count} of ${impact.discovered} discovered`}
                       style={{ height: 7, borderRadius: 5, background: 'var(--line,#e2dce4)', overflow: 'hidden', marginTop: 3 }}>
                    <div style={{ width: `${width}%`, height: '100%', background: STAGE_COLOR[s.key] || '#2f6fed' }} />
                  </div>
                  {s.note && <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{s.note}</div>}
                </div>
              )
            })}
          </div>

          {/* What fell out, and why. */}
          {impact.excluded.length > 0 && (
            <div style={{ marginTop: 12, borderTop: '1px solid var(--line,#e2dce4)', paddingTop: 10 }}>
              <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 6 }}>Excluded from this run</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {impact.excluded.map((x) => (
                  <div key={x.key} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5 }}>
                    <span style={{ fontWeight: 600, flex: '0 0 auto', fontVariantNumeric: 'tabular-nums' }}>{x.count.toLocaleString()}</span>
                    <span style={{ minWidth: 0 }}>{x.label} <span className="muted">— {x.why}</span></span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Coverage gaps — blind spots in the selection: a ticked criterion with no lane for a ticked
          document type. Only shown when a real (code × format) has no method; never invented. */}
      {gaps.length > 0 ? (
        <div className="scope-gaps" style={{ marginTop: hasFunnel ? 12 : 0, borderTop: hasFunnel ? '1px solid var(--line,#e2dce4)' : 'none', paddingTop: hasFunnel ? 10 : 0 }}
             role="status" aria-live="polite">
          <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 6 }}>Coverage gaps</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {gaps.map((g) => (
              <div key={g.format} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5 }}>
                <span aria-hidden="true" style={{ flex: '0 0 auto' }}>⚠</span>
                <span style={{ minWidth: 0 }}>
                  <b>{g.count}</b> selected {g.count === 1 ? 'criterion has' : 'criteria have'} no assessment method for {fmtLabel(g.format)}
                  <span className="muted"> — {g.codes.map((c) => c.code).join(', ')}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : (hasFunnel && hasSelection && (
        <div className="muted scope-gaps-ok" style={{ marginTop: 10, fontSize: 11.5 }}>
          ✓ Every selected criterion has an assessment method for your selected document types.
        </div>
      ))}
    </div>
  )
}
