import { useState } from 'react'
import { coverageSummary, isAssessable, GAP_REASON, AT_REASON } from './assessCoverage.js'

// Capability coverage scorecard for the Assess tab. Answers the up-front question — "of the
// criteria that matter, which can we assess in the file types this estate actually has, which
// are buildable gaps, which don't apply" — from the capability tables, never from scan data.
// Companion to RuleBreakdown (which shows what THIS scan found). See assessCoverage.js.

const C = {
  assessable: { bg: '#e6f2e0', ink: '#2b6a1e', bd: '#c3ddb2', label: 'Assessable' },
  gap: { bg: '#fbecd4', ink: '#8a520e', bd: '#f0cd8b', label: 'Roadmap gap' },
  at: { bg: '#e6edf7', ink: '#2f4c78', bd: '#c4d3ea', label: 'Needs AT test' },
  na: { bg: '#f1eff4', ink: '#7a7386', bd: '#e0dae6', label: 'Not applicable' },
}
const MODE = { auto: 'deterministic', ai: 'AI-assisted', human: 'human-remediated' }
const fmtLabel = (f) => '.' + f

function Bar({ s }) {
  const seg = (n, key) => n > 0 && (
    <i key={key} title={`${n} ${C[key].label.toLowerCase()}`}
       style={{ width: `${(n / s.total) * 100}%`, background: C[key].ink, display: 'block' }} />
  )
  return (
    <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: '#eee', margin: '2px 0 0' }}>
      {seg(s.assessable, 'assessable')}{seg(s.gap, 'gap')}{seg(s.at, 'at')}{seg(s.na, 'na')}
    </div>
  )
}

function Chip({ kind, children, title }) {
  const c = C[kind]
  return <span title={title} style={{ display: 'inline-block', fontSize: 11, fontWeight: 600, color: c.ink,
    background: c.bg, border: `1px solid ${c.bd}`, borderRadius: 6, padding: '2px 7px', whiteSpace: 'nowrap' }}>{children}</span>
}

function Stat({ n, total, kind, sub }) {
  const c = C[kind]
  return (
    <div style={{ flex: '1 1 120px', minWidth: 108 }}>
      <div style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1, color: c.ink }}>{n}<span style={{ fontSize: 14, color: '#9a94a3', fontWeight: 600 }}>/{total}</span></div>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: c.ink, marginTop: 1 }}>{c.label}</div>
      {sub && <div className="muted" style={{ fontSize: 11, marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

export default function CoverageScorecard({ files = [] }) {
  const [documents, setDocuments] = useState(true)
  const [open, setOpen] = useState(false)
  const s = coverageSummary(files, { documents })
  const fmts = s.fmts.map(fmtLabel).join(', ')
  const groups = [
    ['assessable', s.per.filter((p) => isAssessable(p.status))],
    ['gap', s.per.filter((p) => p.status === 'gap')],
    ['at', s.per.filter((p) => p.status === 'at')],
    ['na', s.per.filter((p) => p.status === 'na')],
  ]
  const modeSub = `${s.auto} deterministic · ${s.ai} AI-assisted${s.human ? ` · ${s.human} human` : ''}`

  return (
    <section className="panel">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Coverage — what we can assess
          <span className="muted" style={{ fontWeight: 400 }}> · for your file types: {fmts}</span>
        </h2>
        <button className={`ghost small${documents ? ' on' : ''}`} style={{ fontSize: 11 }}
                onClick={() => setDocuments((v) => !v)}
                title="Toggle between the 20-check document core and all document-applicable criteria">
          {documents ? '✓ 20-core' : 'All document criteria'}
        </button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <Stat n={s.assessable} total={s.total} kind="assessable" sub={modeSub} />
        <Stat n={s.gap} total={s.total} kind="gap" sub={s.gap ? 'buildable with more dev' : 'none for this file mix'} />
        {s.at > 0 && <Stat n={s.at} total={s.total} kind="at" sub="needs manual / AT testing" />}
        <Stat n={s.na} total={s.total} kind="na" sub="barrier can't exist here" />
      </div>
      <div style={{ marginTop: 12 }}><Bar s={s} /></div>

      <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', lineHeight: 1.5 }}>
        <b style={{ color: 'inherit' }}>Assessable</b> = ACP detects it (then fixes it deterministically, with a 1-click AI draft, or routes to a human).
        <b style={{ color: 'inherit' }}> Roadmap gap</b> = applies &amp; detectable, not built yet.
        <b style={{ color: 'inherit' }}> Not applicable</b> = the barrier can't exist in this file type. Capability view — independent of any single scan.
      </p>

      <button className="ghost small" style={{ marginTop: 10 }} onClick={() => setOpen((v) => !v)}>
        {open ? 'Hide the breakdown' : `Show all ${s.total} criteria`}
      </button>

      {open && (
        <div style={{ marginTop: 12, display: 'grid', gap: 14 }}>
          {groups.map(([kind, items]) => items.length > 0 && (
            <div key={kind}>
              <div style={{ fontSize: 12, fontWeight: 700, color: C[kind].ink, marginBottom: 6 }}>
                {C[kind].label} <span className="muted" style={{ fontWeight: 400 }}>· {items.length}</span>
              </div>
              <div style={{ display: 'grid', gap: 5 }}>
                {items.map((p) => (
                  <div key={p.sc} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, flexWrap: 'wrap' }}>
                    <b style={{ fontVariantNumeric: 'tabular-nums', minWidth: 42 }}>{p.sc}</b>
                    <span className="lvlpill">{p.level}</span>
                    <span style={{ flex: '1 1 160px' }}>{p.name}</span>
                    {kind === 'assessable'
                      ? <Chip kind="assessable" title={`Assessed · ${MODE[p.status]} remediation`}>{MODE[p.status]}</Chip>
                      : kind === 'gap'
                        ? <Chip kind="gap" title={GAP_REASON[p.sc] || 'On the roadmap'}>{GAP_REASON[p.sc] || 'roadmap'}</Chip>
                        : kind === 'at'
                          ? <Chip kind="at" title={AT_REASON}>needs AT testing</Chip>
                          : <Chip kind="na" title="This barrier cannot exist in these file types">n/a for {fmts}</Chip>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
