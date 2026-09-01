import { useState } from 'react'
import { estateModel, statusFiles, formatBytes, STATUS_SORTS } from './estateFunnel.js'
import { Bars } from './charts.jsx'

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
const sectionHeadingStyle = {
  margin: '0 0 8px', fontSize: 13, letterSpacing: '.04em', textTransform: 'uppercase',
  // FastPass: #8a8f98 was only 3.08:1 on the estate surface. This token is text, not decoration.
  color: 'var(--muted-text, #6f727a)',
}

function Bar({ value, of, color, pending }) {
  const pct = of > 0 && value != null ? Math.max(2, Math.round((value / of) * 100)) : 0
  return (
    <div style={{ height: 24, borderRadius: 6, background: 'var(--surface-2, #f0f0f3)', overflow: 'hidden' }}>
      {!pending && <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 6 }} />}
    </div>
  )
}

export default function EstateCoverage({ report, inventory, progress }) {
  const [openStatus, setOpenStatus] = useState(null)
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
      {/* How long since anything touched these files.
          Rendered only when the scan carries `by_age` — a report written before that aggregation
          existed has no age data, and zeros would assert an estate with nothing old in it.
          This is the RETENTION question rather than the accessibility one, which is why it spans
          the whole estate (an untouched .mov is a delete candidate too) and why the numbers feed
          the disposition rules rather than the funnel. */}
      {m.age && (
        <>
          <h4 style={sectionHeadingStyle}>
            Last modified
          </h4>
          <Bars items={m.age} cols="130px 1fr 60px" />
          <p className="muted" style={{ fontSize: 11.5, margin: '6px 0 18px', lineHeight: 1.5 }}>
            Across every discovered file, not only the assessable ones — age is a retention
            question.{' '}
            {m.truncated && 'The listing hit its cap, so each band is a floor. '}
            {!m.ageReconciles && (
              // Built to sum to `discovered`, so a mismatch means the two numbers came from
              // different places. Said out loud rather than leaving a reader to add up bars that
              // do not reach the headline.
              <strong>These bands do not add up to the discovered total — treat them as indicative.</strong>
            )}
          </p>
        </>
      )}

      <h4 style={sectionHeadingStyle}>Coverage funnel</h4>
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
      <h4 style={sectionHeadingStyle}>By format</h4>
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

      {/* Capability status — each chip drills into the files behind the count */}
      <h4 style={sectionHeadingStyle}>Capability status</h4>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {m.status.map((r) => {
          const open = openStatus === r.status
          return (
            <button key={r.status} type="button" aria-expanded={open}
                    onClick={() => setOpenStatus(open ? null : r.status)}
                    title={`Show the files counted as ${r.label}`}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12.5, cursor: 'pointer',
                             border: '1px solid var(--line, #e2dce4)', borderRadius: 999, padding: '4px 11px',
                             background: open ? 'var(--surface-2, #f0f0f3)' : 'transparent',
                             color: 'inherit', font: 'inherit' }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: STATUS_COLOR[r.status] }} />
              {r.label} <b style={{ fontVariantNumeric: 'tabular-nums' }}>{nf.format(r.count)}</b>
              <span aria-hidden="true" className="muted" style={{ fontSize: 10 }}>{open ? '▾' : '▸'}</span>
            </button>
          )
        })}
      </div>
      {openStatus && <StatusDrilldown inv={inv} status={openStatus} />}
    </section>
  )
}

const SORT_LABEL = { size: 'Largest', shared: 'Shared first', name: 'Name' }

/** The files behind one capability-status count — a capped, scrollable, sortable sample with triage
 *  metadata (size, owner, shared). Honest about the cap ("showing N of <total>") so an unsupported
 *  bucket of thousands is never mistaken for the handful shown. */
function StatusDrilldown({ inv, status }) {
  const [sort, setSort] = useState('size')
  const d = statusFiles(inv, status, sort)
  return (
    <div style={{ marginTop: 12, border: '1px solid var(--line, #e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap',
                    fontSize: 12, padding: '8px 12px', background: 'var(--surface-2, #f0f0f3)' }}>
        <span className="muted">
          {d.capped
            ? <>Showing <b>{nf.format(d.shown)}</b> of <b>{nf.format(d.total)}</b> files — sample capped for size</>
            : <>All <b>{nf.format(d.total)}</b> file{d.total === 1 ? '' : 's'}</>}
        </span>
        <span style={{ display: 'inline-flex', gap: 4 }} role="group" aria-label="Sort files">
          {STATUS_SORTS.map((k) => (
            <button key={k} type="button" onClick={() => setSort(k)} aria-pressed={sort === k}
                    style={{ fontSize: 11, padding: '2px 9px', borderRadius: 999, cursor: 'pointer', font: 'inherit',
                             border: '1px solid var(--line, #e2dce4)',
                             background: sort === k ? 'var(--accent, #0e7c86)' : 'transparent',
                             color: sort === k ? '#fff' : 'inherit' }}>
              {SORT_LABEL[k]}
            </button>
          ))}
        </span>
      </div>
      {d.files.length === 0 ? (
        <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>No files in this bucket.</div>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', maxHeight: 300, overflowY: 'auto' }}>
          {d.files.map((f, i) => (
            <li key={f.id || i} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, alignItems: 'center',
                                         fontSize: 12.5, padding: '6px 12px', borderTop: i ? '1px solid var(--line, #e2dce4)' : 'none' }}>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>{f.name || '(unnamed)'}</span>
                  {f.shared && (
                    <span title="Shared / externally visible"
                          style={{ flexShrink: 0, fontSize: 10, fontWeight: 700, color: 'var(--warn-fg, #9a6a12)',
                                   background: 'var(--warn-bg, #f6ecd6)', padding: '1px 5px', borderRadius: 4 }}>SHARED</span>
                  )}
                </span>
                {f.owner && <span className="muted" style={{ fontSize: 11, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.owner}</span>}
              </span>
              <span style={{ textAlign: 'right', flexShrink: 0 }}>
                <span style={{ display: 'block', fontVariantNumeric: 'tabular-nums' }}>{formatBytes(f.size)}</span>
                <span className="muted" style={{ fontSize: 11 }}>{f.label}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
