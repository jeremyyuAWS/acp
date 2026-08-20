import { useState } from 'react'
import { coverageSummary, assessmentGaps, assessmentIn, remediationIn, GAP_REASON, AT_REASON } from './assessCoverage.js'
import { CORE_SCS, DENOMINATOR, SCOPE_SIZE, SCOPE_LABEL } from './activeScope.js'

// Capability coverage scorecard for the Assess tab (ADR 0023, two axes). Answers the up-front
// question in CUSTOMER-OUTCOME language — not implementation (deterministic/OCR/vision):
//
//   ASSESSMENT — can ACP determine compliance?   🟢 A4 Fully Assessed · 🟡 A3 Potential Issue · 🔴 A2 Human Assessment Required · ⚪ N/A
//   REMEDIATION — if it fails, how is it fixed?   ⚡ R4 Automatically Fixed · 🤖 R3 AI Generated Fix · 👤 R2 Guided
//   Wording matches the WCAG matrix (docs/acp-architecture-deck.md, "A4/A3/A2/NA · R4/R3/R2")
//   so the two surfaces cannot disagree — coverageScorecard.test.jsx asserts these strings so
//   a rename here has to be a decision rather than a drift. There is no R1 lane on purpose:
//   the engine never asserts "nothing remediates this" — R_CEILING maps human->M (Guided), and
//   R1 is a matrix-only observation about a specific cell.
//
// Computed from the capability tables, never from scan data. Companion to RuleBreakdown (what
// THIS scan found). See assessCoverage.js.

// Assessment lanes.
const A = {
  auto: { emoji: '🟢', bg: '#e6f2e0', ink: '#2b6a1e', bd: '#c3ddb2', label: 'Fully Assessed' },
  review: { emoji: '🟡', bg: '#fbf3d6', ink: '#8a6a0e', bd: '#eeda9a', label: 'Potential Issue' },
  human: { emoji: '🔴', bg: '#f8e3e0', ink: '#98392b', bd: '#eec2bb', label: 'Human Assessment Required' },
  na: { emoji: '⚪', bg: '#f1eff4', ink: '#7a7386', bd: '#e0dae6', label: 'Not applicable' },
}
// Remediation paths.
const R = {
  auto: { emoji: '⚡', ink: '#2f4c78', bg: '#e6edf7', bd: '#c4d3ea', label: 'Automatically Fixed' },
  ai: { emoji: '🤖', ink: '#5a3d86', bg: '#efe7f7', bd: '#d8c6ea', label: 'AI Generated Fix' },
  human: { emoji: '👤', ink: '#5a5566', bg: '#f1eff4', bd: '#e0dae6', label: 'Guided Remediation' },
}
const fmtLabel = (f) => '.' + f

// Fold the ancillary states into the four customer-facing assessment lanes: needs-AT (keyboard,
// html) reads as human-only; a buildable gap reads as not-yet-assessed (N/A) with a footnote.
const foldLane = (lane) => (lane === 'at' ? 'human' : lane === 'gap' ? 'na' : lane)
const assessLane = (p) => foldLane(p.assessment)
const LANE_EMOJI = { auto: '🟢', review: '🟡', human: '🔴', na: '⚪' }
const REM_EMOJI = { auto: '⚡', ai: '🤖', human: '👤', na: '—' }
const GRID_FMTS = ['docx', 'xlsx', 'pptx', 'pdf']

// The Rule × Document-type grid — one glance at what ACP does for every criterion × format.
// Each cell is the assessment lane emoji (🟢/🟡/🔴/⚪); hover shows assessment + remediation.
function RuleFormatMatrix({ rows }) {
  return (
    <div style={{ overflowX: 'auto', marginTop: 12 }}>
      <table className="covtable" style={{ minWidth: 460 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left' }}>Criterion</th>
            {GRID_FMTS.map((f) => <th key={f} style={{ textAlign: 'center' }}>.{f}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.sc} className="covrow">
              <td style={{ whiteSpace: 'nowrap' }}>
                <b style={{ fontVariantNumeric: 'tabular-nums' }}>{p.sc}</b>
                <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{p.name}</span>
              </td>
              {GRID_FMTS.map((f) => {
                const a = foldLane(assessmentIn(p.sc, f))
                const rem = remediationIn(p.sc, f)
                const remTxt = rem === 'na' ? 'no ACP fix' : `${REM_EMOJI[rem]} ${rem === 'ai' ? 'AI Generated Fix' : rem} remediation`
                const label = a === 'auto' ? 'Fully Assessed' : a === 'review' ? 'Potential Issue' : a === 'human' ? 'Human Assessment Required' : 'N/A for this format'
                return (
                  <td key={f} style={{ textAlign: 'center', fontSize: 16 }} title={`${p.sc} · .${f} — ${label} · ${remTxt}`}>
                    {LANE_EMOJI[a] || '⚪'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Tile({ emoji, n, total, kind, palette, sub }) {
  const c = palette[kind]
  return (
    <div style={{ flex: '1 1 132px', minWidth: 120 }}>
      <div style={{ fontSize: 25, fontWeight: 700, lineHeight: 1.1, color: c.ink }}>
        <span style={{ fontSize: 16 }}>{emoji}</span> {n}
        {total != null && <span style={{ fontSize: 13, color: '#9a94a3', fontWeight: 600 }}>/{total}</span>}
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: c.ink, marginTop: 2 }}>{c.label}</div>
      {sub && <div className="muted" style={{ fontSize: 11, marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

function Chip({ palette, kind, children, title }) {
  const c = palette[kind]
  if (!c) return null
  return <span title={title} style={{ display: 'inline-block', fontSize: 11, fontWeight: 600, color: c.ink,
    background: c.bg, border: `1px solid ${c.bd}`, borderRadius: 6, padding: '2px 7px', whiteSpace: 'nowrap' }}>
    <span style={{ fontSize: 10 }}>{c.emoji}</span> {children}</span>
}

function Bar({ counts, total }) {
  const seg = (n, kind) => n > 0 && (
    <i key={kind} title={`${n} ${A[kind].label.toLowerCase()}`}
       style={{ width: `${(n / total) * 100}%`, background: A[kind].ink, display: 'block' }} />
  )
  return (
    <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: '#eee', margin: '2px 0 0' }}>
      {seg(counts.auto, 'auto')}{seg(counts.review, 'review')}{seg(counts.human, 'human')}{seg(counts.na, 'na')}
    </div>
  )
}

// Coverage-gap warning — the (criterion × format) cells where the barrier applies but ACP has NO
// assessment method (buildable 'gap' or AT-only 'at'), derived by assessmentGaps from the same
// capability tables. This is the piece the folded lanes hid: gap→⚪ and at→🔴 fold a "not-yet-
// assessed" hole into N/A / human, so the operator could not tell a genuine hole from an
// inapplicable cell. Here it is stated per format, in plain "N criteria have no assessment method
// for .fmt" language, using GAP_REASON/AT_REASON for the why. When there is no hole (a document-
// only estate today), we SAY SO rather than staying silent — the absence of a warning should be a
// positive statement, not an ambiguous blank. Never fabricates a gap: the list is exactly what the
// model derives, so an all-covered estate reads "full assessment coverage".
function GapSummary({ files, documents }) {
  const g = assessmentGaps(files, { documents })
  const fmts = g.fmts.map(fmtLabel).join(', ')
  if (g.total === 0) {
    return (
      <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', lineHeight: 1.5 }}>
        <b style={{ color: '#2b6a1e' }}>✓ No coverage gaps</b> — ACP has an assessment method for every
        applicable criterion in {fmts}. Cells shown as ⚪ are barriers that can’t exist in these file
        types, not methods ACP is missing.
      </p>
    )
  }
  const label = g.total === 1 ? '1 criterion has' : `${g.total} criteria have`
  return (
    <div role="note" style={{ marginTop: 10, padding: '9px 11px', borderRadius: 8,
      background: '#fbf3d6', border: '1px solid #eeda9a' }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#8a6a0e' }}>
        ⚠️ Coverage gaps — {label} no assessment method for your file types
      </div>
      <div style={{ display: 'grid', gap: 6, marginTop: 7 }}>
        {g.byFormat.map((row) => (
          <div key={row.fmt} style={{ fontSize: 12 }}>
            <span style={{ fontWeight: 700, color: '#8a6a0e' }}>
              {row.count} {row.count === 1 ? 'criterion has' : 'criteria have'} no method for {fmtLabel(row.fmt)}
            </span>
            <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, marginLeft: 8, verticalAlign: 'middle' }}>
              {row.criteria.map((c) => (
                <span key={c.sc} title={c.reason} style={{ display: 'inline-block', fontSize: 11, fontWeight: 600,
                  color: '#8a6a0e', background: '#fdf8e6', border: '1px solid #eeda9a', borderRadius: 6,
                  padding: '1px 7px', whiteSpace: 'nowrap' }}>
                  <b style={{ fontVariantNumeric: 'tabular-nums' }}>{c.sc}</b> {c.name}
                  <span style={{ marginLeft: 5, opacity: 0.75, fontWeight: 400 }}>
                    {c.lane === 'at' ? 'needs AT testing' : 'buildable'}
                  </span>
                </span>
              ))}
            </span>
          </div>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 7, lineHeight: 1.45 }}>
        {g.cells.some((c) => c.lane === 'at') && <>{AT_REASON}. </>}
        {g.cells.some((c) => c.lane === 'gap') && <>Buildable gaps are statically detectable criteria ACP does not check yet. </>}
        These fold into ⚪/🔴 above; listed here so a missing method is not mistaken for an inapplicable cell.
      </div>
    </div>
  )
}

export default function CoverageScorecard({ files = [] }) {
  const [documents, setDocuments] = useState(true)
  const [open, setOpen] = useState(false)
  const [grid, setGrid] = useState(false)
  const s = coverageSummary(files, { documents })
  const fmts = s.fmts.map(fmtLabel).join(', ')

  // Assessment axis, folded to the four customer lanes.
  const assess = {
    auto: s.certifiable,
    review: s.review,
    human: s.human + s.at,
    na: s.na + s.gap,
  }
  // Rows of the expandable breakdown, grouped by assessment lane.
  const groups = ['auto', 'review', 'human', 'na'].map((k) => [k, s.per.filter((p) => assessLane(p) === k)])

  return (
    <section className="panel">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Coverage — what we can assess
          <span className="muted" style={{ fontWeight: 400 }}> · for your file types: {fmts}</span>
        </h2>
        {/* This panel's denominator is deliberately the 20-check document core, NOT the agreed
            scope the "By WCAG criterion" panel below defaults to — it answers a different
            question (what ACP can assess for these file types, independent of any scan or
            engagement), and narrowing a capability claim to a customer's checklist would make it
            unreadable as a capability claim. That is exactly why it now says which denominator it
            is: two totals on one screen that do not say what they count read as a contradiction. */}
        <button className={`ghost small${documents ? ' on' : ''}`} style={{ fontSize: 11 }}
                onClick={() => setDocuments((v) => !v)}
                title={`Toggle between the ${DENOMINATOR.core.noun} and all document-applicable criteria. This is a capability view — ${DENOMINATOR.core.question}. The "By WCAG criterion" panel below answers a narrower question: ${DENOMINATOR.scope.question}.`}>
          {documents ? `✓ ${CORE_SCS.size}-check document core` : 'All document criteria'}
        </button>
      </div>

      {/* Layer 1 — Assessment: can ACP determine compliance? */}
      <div className="muted" style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.03em', textTransform: 'uppercase', marginBottom: 4 }}>Assessment — can we determine compliance?</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <Tile emoji="🟢" n={assess.auto} total={s.total} kind="auto" palette={A} sub="assessed &amp; certifiable" />
        <Tile emoji="🟡" n={assess.review} total={s.total} kind="review" palette={A} sub="evidence flagged · human confirms" />
        {assess.human > 0 && <Tile emoji="🔴" n={assess.human} total={s.total} kind="human" palette={A} sub="a person must assess" />}
        <Tile emoji="⚪" n={assess.na} total={s.total} kind="na" palette={A} sub="barrier can't exist here" />
      </div>
      <div style={{ marginTop: 10 }}><Bar counts={assess} total={s.total} /></div>

      {/* Coverage-gap warning — where ACP has no assessment method (buildable / needs-AT), stated
          per format so the folded ⚪/🔴 lanes don't hide a genuine hole. */}
      <GapSummary files={files} documents={documents} />

      {/* Layer 2 — Remediation: if it fails, how is it fixed? */}
      <div className="muted" style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.03em', textTransform: 'uppercase', margin: '16px 0 4px' }}>Remediation — if it fails, how is it fixed?</div>
      {/* Denominator, not a bare count. These enumerate CRITERIA over the same core as the
          assessment tiles above (remAuto + remAi + remHuman + the unshown "no ACP fix" = s.total),
          so "6" alone read as findings/files/methods — unit unknown. `/{s.total}` makes it
          "6 of 20 criteria", matching the assessment row and the section's stated denominator. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <Tile emoji="⚡" n={s.remAuto} total={s.total} kind="auto" palette={R} sub="deterministic fix" />
        <Tile emoji="🤖" n={s.remAi} total={s.total} kind="ai" palette={R} sub="AI drafts · 1-click approve" />
        <Tile emoji="👤" n={s.remHuman} total={s.total} kind="human" palette={R} sub="re-authored by a person" />
      </div>

      <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
        <b style={{ color: 'inherit' }}>🟢 Fully Assessed</b> = ACP certifies pass &amp; fail.
        <b style={{ color: 'inherit' }}> 🟡 Potential Issue</b> = ACP flags evidence of a likely issue; a reviewer confirms.
        <b style={{ color: 'inherit' }}> 🔴 Human Assessment Required</b> = ACP can't assess it.
        <b style={{ color: 'inherit' }}> ⚪ N/A</b> = the barrier can't exist in these file types.
        Assessment and remediation are independent — e.g. a 🟡 finding can still carry a 🤖 one-click fix. Capability view — independent of any single scan.
      </p>
      {/* Say out loud why this total and the panel below differ. An unexplained 20 here beside a
          14 there reads as one of them being wrong. */}
      {documents && (
        <p className="muted" style={{ fontSize: 11, margin: '6px 0 0', lineHeight: 1.5 }}>
          Counted over the <b style={{ color: 'inherit' }}>{CORE_SCS.size}-check document core</b> — what ACP can assess for these file types.
          The “By WCAG criterion” panel below counts over a narrower list: the <b style={{ color: 'inherit' }}>{SCOPE_SIZE} criteria in your {SCOPE_LABEL}</b> for this engagement. Different questions, so the two totals are not meant to match.
        </p>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
        <button className="ghost small" onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide the breakdown' : `Show all ${s.total} criteria`}
        </button>
        <button className={`ghost small${grid ? ' on' : ''}`} onClick={() => setGrid((v) => !v)}
                title="A one-glance grid: every criterion × document type, coloured by assessment lane">
          {grid ? 'Hide the rule × format grid' : 'Rule × format grid'}
        </button>
      </div>

      {grid && (
        <>
          <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            🟢 Fully Assessed · 🟡 Potential Issue · 🔴 Human Assessment Required · ⚪ N/A — hover a cell for the remediation lane.
          </div>
          <RuleFormatMatrix rows={s.per} />
        </>
      )}

      {open && (
        <div style={{ marginTop: 12, display: 'grid', gap: 14 }}>
          {groups.map(([kind, items]) => items.length > 0 && (
            <div key={kind}>
              <div style={{ fontSize: 12, fontWeight: 700, color: A[kind].ink, marginBottom: 6 }}>
                {A[kind].emoji} {A[kind].label} <span className="muted" style={{ fontWeight: 400 }}>· {items.length}</span>
              </div>
              <div style={{ display: 'grid', gap: 5 }}>
                {items.map((p) => (
                  <div key={p.sc} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, flexWrap: 'wrap' }}>
                    <b style={{ fontVariantNumeric: 'tabular-nums', minWidth: 42 }}>{p.sc}</b>
                    <span className="lvlpill">{p.level}</span>
                    <span style={{ flex: '1 1 150px' }}>{p.name}</span>
                    {/* remediation chip — only where ACP has a fix lane */}
                    {p.remediation !== 'na'
                      ? <Chip palette={R} kind={p.remediation} title={`Remediation: ${R[p.remediation]?.label}`}>{R[p.remediation]?.label}</Chip>
                      : p.assessment === 'gap'
                        ? <span className="muted" style={{ fontSize: 11 }} title={GAP_REASON[p.sc] || 'On the roadmap'}>buildable</span>
                        : p.assessment === 'at'
                          ? <span className="muted" style={{ fontSize: 11 }} title={AT_REASON}>needs AT testing</span>
                          : <span className="muted" style={{ fontSize: 11 }} title="No ACP fix — this barrier can't exist here">—</span>}
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
