import { estateModel } from './estateFunnel.js'

// Estate coverage from a scan report's `scope.inventory` — the funnel, format composition, and
// capability-status split, rendered from REAL discovery data (the illustrative dashboard artifact
// made concrete). Three denominators, never one percentage; unsupported never reads as passed.

const STATUS_COLOR = {
  assessable: 'var(--auto, #1f9d6b)',
  metadata_only: 'var(--muted-fg, #8a8f98)',
  unsupported: 'var(--muted-fg, #8a8f98)',
  excluded: 'var(--line-strong, #c6ccc2)',
}
const nf = new Intl.NumberFormat('en-US')

function Bar({ value, of, color, pending }) {
  const pct = of > 0 && value != null ? Math.max(2, Math.round((value / of) * 100)) : 0
  return (
    <div style={{ height: 24, borderRadius: 6, background: 'var(--surface-2, #f0f0f3)', overflow: 'hidden' }}>
      {!pending && <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 6 }} />}
    </div>
  )
}

export default function EstateCoverage({ report, inventory, progress }) {
  const inv = inventory || report?.scope?.inventory
  if (!inv || !inv.discovered) {
    return (
      <div className="muted" style={{ padding: 20, fontSize: 13.5 }}>
        No estate inventory yet. Run a whole-drive scan; discovery reports every file, and this shows
        the coverage split.
      </div>
    )
  }
  const m = estateModel(inv, progress || report?.scope?.inventory_progress || {})

  return (
    <section className="estate-coverage" aria-label="Content estate coverage">
      {/* Headline */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 4 }}>
        <h3 style={{ margin: 0, fontSize: 18 }}>
          {m.truncated ? '≥ ' : ''}{nf.format(m.discovered)} files discovered
        </h3>
        <span className="muted" style={{ fontSize: 13.5 }}>
          {Math.round(m.assessablePct * 100)}% assessment-eligible ({nf.format(m.assessmentEligible)} files)
        </span>
        {m.truncated && (
          <span title="The listing hit its cap — this count is a floor, not the whole estate."
                style={{ fontSize: 11, fontWeight: 700, color: 'var(--warn-fg, #9a6a12)',
                         background: 'var(--warn-bg, #f6ecd6)', padding: '2px 8px', borderRadius: 6 }}>
            TRUNCATED — floor, not complete
          </span>
        )}
      </div>
      <p className="muted" style={{ fontSize: 12.5, margin: '0 0 18px' }}>
        Discovery, assessment, and remediation are three different denominators. Unsupported means
        not evaluated — never passed.
      </p>

      {/* Funnel */}
      <h4 style={{ margin: '0 0 8px', fontSize: 13, letterSpacing: '.04em', textTransform: 'uppercase', color: 'var(--muted-fg,#8a8f98)' }}>Coverage funnel</h4>
      <div style={{ display: 'grid', gap: 6, marginBottom: 22 }}>
        {m.funnel.map((s, i) => (
          <div key={s.key} style={{ display: 'grid', gridTemplateColumns: '22px 1fr 90px', gap: 10, alignItems: 'center' }}>
            <span className="muted" style={{ fontSize: 11, textAlign: 'right' }}>{i + 1}</span>
            <div>
              <div style={{ fontSize: 12.5, marginBottom: 2 }}>{s.label}</div>
              <Bar value={s.value} of={s.of} color={i < 3 ? 'var(--accent, #0e7c86)' : 'var(--auto, #1f9d6b)'} pending={s.value == null} />
            </div>
            <span style={{ fontSize: 13, fontWeight: 650, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
              {s.value == null ? <span className="muted" title="Awaiting scan data">pending</span> : nf.format(s.value)}
            </span>
          </div>
        ))}
      </div>

      {/* Composition */}
      <h4 style={{ margin: '0 0 8px', fontSize: 13, letterSpacing: '.04em', textTransform: 'uppercase', color: 'var(--muted-fg,#8a8f98)' }}>By format</h4>
      <div style={{ display: 'grid', gap: 6, marginBottom: 22 }}>
        {m.composition.map((r) => {
          const max = m.composition[0]?.count || 1
          return (
            <div key={r.format} style={{ display: 'grid', gridTemplateColumns: '110px 1fr 70px', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: 3, background: r.assessable ? 'var(--accent,#0e7c86)' : 'var(--muted-fg,#8a8f98)' }} />
                {r.label}
              </span>
              <Bar value={r.count} of={max} color={r.assessable ? 'var(--accent,#0e7c86)' : 'var(--muted-fg,#8a8f98)'} />
              <span style={{ fontSize: 12.5, fontWeight: 600, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{nf.format(r.count)}</span>
            </div>
          )
        })}
      </div>

      {/* Capability status */}
      <h4 style={{ margin: '0 0 8px', fontSize: 13, letterSpacing: '.04em', textTransform: 'uppercase', color: 'var(--muted-fg,#8a8f98)' }}>Capability status</h4>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {m.status.map((r) => (
          <span key={r.status} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12.5,
                                        border: '1px solid var(--line, #e2dce4)', borderRadius: 999, padding: '4px 11px' }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: STATUS_COLOR[r.status] }} />
            {r.label} <b style={{ fontVariantNumeric: 'tabular-nums' }}>{nf.format(r.count)}</b>
          </span>
        ))}
      </div>
    </section>
  )
}
