import { useState, useRef } from 'react'
import { WCAG } from './wcagCatalog.js'
import { WHY } from './wcagWhy.js'
import { useDialog } from './a11y.js'

// WCAG 2.1 + 2.2 coverage matrix — all 87 success criteria, colour-coded by what
// the platform checks today vs. what's on the roadmap beyond the partner. Backs
// the "we go beyond a raw scanner" story with the real catalog + LOE estimate.
const SRC = {
  'Shipped (demo)': ['Live now', '#3B6D11', '#E7F0DC'],
  'MDK HITL': ['Covered · HITL', '#1F5FA8', '#E2EDFB'],
  'Partner baseline': ['Partner-provided', '#3C3489', '#EEEDFE'],
  'MDK net-new': ['Roadmap', '#854F0B', '#FAEEDA'],
}
const PRINCIPLES = ['Perceivable', 'Operable', 'Understandable', 'Robust']
const FILTERS = [
  ['all', 'All 87'], ['A', 'Level A'], ['AA', 'Level AA'], ['2.2', 'New in 2.2'],
  ['Required', 'US Required'], ['docs', 'Applies to documents'],
  ['rem:auto', '⚡ Auto-remediated'], ['rem:assisted', '✎ AI-assisted'], ['rem:manual', '✋ Human-verified'],
  ['Shipped (demo)', 'Live now'], ['MDK HITL', 'Covered · HITL'], ['MDK net-new', 'Roadmap'],
]
// Plain-language meaning of the three conformance levels, for users new to WCAG.
const LEVELS = [
  { k: 'A', tag: 'Must have', desc: 'The basics — fail these and some users are fully blocked.', ex: 'alt text · keyboard navigation · form labels' },
  { k: 'AA', tag: 'Should have · legal target', target: true, desc: 'Fixes the most common, high-impact barriers. What most laws & organizations require.', ex: 'contrast 4.5:1 · captions · visible focus' },
  { k: 'AAA', tag: 'Nice to have', desc: 'The highest bar — aspirational, rarely met across a whole estate.', ex: 'contrast 7:1 · sign language · plain language' },
]
const LEVEL_MEANING = { A: 'must-have baseline', AA: 'should-have · the legal target', AAA: 'nice-to-have enhancement' }

// Delivery roadmap — Claude-paced (AI-built), not human dev-weeks. These compress
// the LOE because Claude writes the checks, evals and review scaffolds directly.
const ROADMAP_PHASES = [
  { id: 'P0', label: 'Foundation', when: 'Days 1–2', match: null, done: true, desc: 'Coverage audit vs. partner · lock the check contract · stand up the golden-corpus eval harness.' },
  { id: 'P1', label: 'Agentic AI checks', when: 'Days 3–5', match: (p) => p.startsWith('Phase 1'), done: true, desc: 'Semantic LLM evaluators — sensory characteristics, headings & labels. Claude authors prompt + evals.' },
  { id: 'P2', label: 'Human-in-the-loop', when: 'Weeks 2–3', match: (p) => p.startsWith('Phase 2'), done: true, milestone: 'Level AA conformance', desc: 'Pre-screen detectors + reviewer workflow for the manual Required criteria (captions, focus order, errors…).' },
  { id: 'P3', label: 'AAA / optional', when: 'Weeks 4–6', match: (p) => p.startsWith('Phase 3'), desc: 'Everything not legally required — pursued selectively.' },
]
const PHASE_SHORT = {
  'Phase 1 · Agentic (Req. A/AA)': ['Phase 1', '#3C3489', '#EEEDFE'],
  'Phase 2 · HITL (Req. A/AA)': ['Phase 2', '#854F0B', '#FAEEDA'],
  'Phase 3 · Optional / AAA': ['Phase 3', '#5F5E5A', '#EFEDEA'],
}
const PHASE_FILTER = { P1: 'Phase 1', P2: 'Phase 2', P3: 'Phase 3' }

// How each criterion is remediated once detected. 'auto' = deterministic engine fix;
// 'assisted' = AI drafts, human approves; 'manual' = a person must re-author; 'detect'
// = flagged for review, no automated fix. Explicit for what the engine handles today;
// a conservative default covers the rest.
const REMEDIATION = {
  '1.4.3': 'auto', '1.3.1': 'auto', '2.4.1': 'auto', '2.4.2': 'auto', '3.1.1': 'auto', '2.4.3': 'auto',
  '2.1.1': 'auto', '1.4.1': 'auto', '1.4.4': 'auto', '1.4.10': 'auto', '4.1.2': 'auto',
  '2.4.6': 'auto', '2.4.7': 'auto',
  '1.1.1': 'assisted', '1.3.3': 'assisted', '1.4.5': 'assisted', '2.4.4': 'assisted', '1.4.11': 'assisted',
  '1.4.12': 'assisted', '3.1.2': 'assisted', '1.3.2': 'assisted', '1.2.1': 'assisted', '1.2.2': 'assisted',
  '1.2.3': 'assisted', '1.2.5': 'assisted', '3.3.1': 'assisted', '3.3.2': 'assisted', '3.3.3': 'assisted',
  '2.1.2': 'manual',
}
// Per-criterion remediation method — overrides the generic tier blurb where AI does
// something specific, so the "why" is explicit (esp. the AI-assisted cases).
const REM_NOTE = {
  '1.4.5': 'Vision OCR reads the text out of the image; the agent re-creates it as real, styled text. A human approves fidelity and the logo / essential-image exceptions.',
  '1.3.3': 'An LLM rewrites instructions that rely on shape, size or position so they name the control instead. A human approves the wording.',
  '3.1.2': 'Language detection finds passages in another language; the agent tags them with the right lang. A human spot-checks.',
  '1.1.1': 'A vision model drafts the alt text from the image; a human approves before publish.',
  '1.4.11': 'The agent proposes compliant colours for borders / icons; a designer signs off.',
  '2.1.2': 'The agent proposes the focus fix (Escape + focus loop), but “no trap” is confirmed by interactive keyboard testing — human-verified.',
}
const REM_META = {
  auto: ['⚡', 'Auto-remediated', '#3B6D11', '#E7F0DC', 'Deterministic fix applied by the engine, then re-validated — no human needed.'],
  assisted: ['✎', 'AI-assisted', '#854F0B', '#FAEEDA', 'AI drafts the fix; a human approves before publish.'],
  manual: ['✋', 'Human-verified', '#1F5FA8', '#E2EDFB', 'AI can propose the change, but it must be verified by a person (e.g. interactive testing).'],
  detect: ['◷', 'Detect & route', '#5F5E5A', '#EFEDEA', 'Flagged for a reviewer — no automated fix exists yet.'],
}
const remTier = (r) => (r.source === 'MDK HITL' ? 'manual' : REMEDIATION[r.sc] || (r.docApplies ? 'assisted' : 'detect'))

// Automatability under "no UI automation" (Devanathan's analysis): VALIDATE — confirm a
// pass — and REMEDIATE — apply the fix — are separate axes. Levels: green = static + LLM,
// real pass/fail; amber = LLM/vision-assisted, a human confirms; human = needs runtime /
// interaction. (The source rubric's red → blue here, per the no-threatening-red palette.)
const AUTOMATION = {
  '3.1.2': { v: 'green', r: 'green', note: 'Fully automatable — the best case. The LLM detects the foreign passage and a script writes the lang attribute. No UI ever needed.' },
  '1.3.3': { v: 'amber', r: 'amber', note: 'The LLM reads the text, flags shape/colour/position-only instructions, and drafts a fix. Pure content analysis — no UI.' },
  '1.3.2': { v: 'human', r: 'detect', note: 'Reading order is detected statically — flagged when it differs from the visual flow — but correcting it needs the PDF/Office tag tree, which is on the roadmap.' },
  '1.4.5': { v: 'amber', r: 'amber', note: 'OCR/vision on the statically-extracted image; the LLM re-creates real text. No UI.' },
  '1.4.1': { v: 'amber', r: 'amber', note: 'Static parse for colour-only coding + vision on images; the LLM adds the second cue. No UI.' },
  '1.4.11': { v: 'amber', r: 'amber', note: 'Colours read from source/SVG and the maths is deterministic (green for declared colours); vision samples raster graphics. Only hover/focus states need runtime — drop those.' },
  '2.4.3': { v: 'amber', r: 'amber', note: 'Tab order + tabindex are read from markup and the LLM judges sequence. Falls to human only when JS/CSS reorders visually. Interactive content only.' },
  '4.1.2': { v: 'amber', r: 'amber', note: 'Static parse finds name/role and the LLM drafts ARIA names (presence). True computed-name + behaviour still needs human/AT. Interactive only.' },
  '2.1.1': { v: 'human', r: 'amber', note: 'Static analysis flags the risk (click handler with no key handler, div-as-button); confirming operability needs a real keyboard — human.' },
  '1.4.4': { v: 'human', r: 'amber', note: 'Validation genuinely needs rendering at 200% — the UI automation we exclude. Static can only flag user-scalable=no / fixed units.' },
  '1.4.10': { v: 'human', r: 'amber', note: 'Needs a render at 320px / 400%. No non-UI way to confirm a pass — only flag the risk.' },
  '1.4.12': { v: 'human', r: 'amber', note: 'Needs applying the spacing override and checking for clipping — inherently rendered.' },
  '2.1.2': { v: 'human', r: 'amber', note: 'Detecting a trap is inherently interactive — no static proxy. The fix itself is AI-draftable.' },
}
const LV = {
  green: ['●', 'Automatable', '#3B6D11', '#E7F0DC'],
  amber: ['●', 'AI-assisted · human confirms', '#854F0B', '#FAEEDA'],
  human: ['●', 'Needs runtime — human', '#1F5FA8', '#E2EDFB'],
  detect: ['●', 'Detect & route', '#5F5E5A', '#EFEDEA'],
}
const TIER2LV = { auto: 'green', assisted: 'amber', manual: 'human', detect: 'detect' }
const valLevel = (r) => AUTOMATION[r.sc]?.v || (r.source === 'Shipped (demo)' || /Automated/.test(r.approach || '') ? 'green' : 'amber')
const remLevel = (r) => AUTOMATION[r.sc]?.r || TIER2LV[remTier(r)] || 'amber'

const mid = (r) => (r.lo + r.hi) / 2
const wks = (d) => `${(d / 5).toFixed(0)}–${Math.round(d / 5)}`

// Success-criterion detail dialog — its own component so focus management runs on open.
function ScDetail({ sel, onClose }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  return (
    <div className="covdrawer" role="dialog" aria-modal="true" aria-label={`${sel.sc} detail`} onClick={onClose}>
      <div className="covpanel" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <button className="covclose" aria-label="Close" onClick={onClose}>✕</button>
        <div className="covsc" style={{ fontSize: 18 }}><b>{sel.sc}</b> {sel.name}</div>
        <div className="muted" style={{ margin: '4px 0 8px' }}>Level {sel.level} · {sel.principle} · added in WCAG {sel.added}</div>
        {sel.req && <p className="covreq">{sel.req}</p>}
        {WHY[sel.sc] && <div className="covwhybox"><span className="covwhylbl">Why it matters</span> {WHY[sel.sc]}</div>}
        <div className="levelnote">Level {sel.level} — {LEVEL_MEANING[sel.level]}</div>
        {(() => {
          const vv = LV[valLevel(sel)], rv = LV[remLevel(sel)]
          const note = AUTOMATION[sel.sc]?.note || REM_NOTE[sel.sc] || REM_META[remTier(sel)][4]
          return (
            <div className="autobox">
              <div className="autorow">
                <span className="autotag" style={{ color: vv[2], background: vv[3] }}><b>Validate</b> · {vv[1]}</span>
                <span className="autotag" style={{ color: rv[2], background: rv[3] }}><b>Remediate</b> · {rv[1]}</span>
              </div>
              <div className="autoverdict">{note}</div>
            </div>
          )
        })()}
        <div className="covrows">
          <div><span className="muted">US legal requirement</span><b style={{ color: sel.legal === 'Required' ? '#1F5FA8' : 'var(--ink)' }}>{sel.legal}</b></div>
          <div><span className="muted">Document applicability</span><b style={{ color: sel.docApplies ? '#3B6D11' : 'var(--muted)' }}>{sel.docApplies ? 'Applies to documents' : 'Web / interaction — N/A to static docs'}</b></div>
          {(() => {
            // Coverage splits along Devanathan's two axes: do we apply the fix today
            // (remediation), and do we confirm a pass today (validation)? Criteria that
            // need a render/interaction can be remediated + statically flagged, but a true
            // pass is only partial without UI automation.
            const vlv = valLevel(sel)
            const valCov = vlv === 'human'
              ? ['Partial · static flag', '#854F0B', 'Detected/flagged statically; a true pass needs rendering or interaction.']
              : sel.source === 'Shipped (demo)' ? ['Live now', '#3B6D11', 'Validated by the engine in this demo.']
              : sel.source === 'MDK HITL' ? ['Detect & route · HITL', '#1F5FA8', 'Flagged statically by the pre-screen; a human reviewer verifies and signs off.']
              : sel.source === 'Partner baseline' ? ['Partner scanner', '#3C3489', 'Validated by the partner’s automated engine.']
              : ['Roadmap', '#854F0B', 'Validation is on the roadmap.']
            return <>
              <div><span className="muted">Validation coverage</span><b style={{ color: valCov[1] }} title={valCov[2]}>{valCov[0]}</b></div>
              <div><span className="muted">Remediation coverage</span><b style={{ color: SRC[sel.source][1] }} title="Whether the platform applies the fix today.">{SRC[sel.source][0]}</b></div>
            </>
          })()}
          <div><span className="muted">Build tier</span><b>{sel.tier}</b></div>
          <div><span className="muted">Roadmap phase</span><b>{sel.phase}</b></div>
          {sel.source === 'MDK net-new' && (() => { const ph = ROADMAP_PHASES.find((x) => x.match && x.match(sel.phase)); return ph ? <div><span className="muted">Timeline · Claude-paced</span><b>{ph.when}</b></div> : null })()}
          {sel.source === 'MDK net-new' && <div><span className="muted">Effort (human team)</span><b>{sel.lo}–{sel.hi} dev-days</b></div>}
        </div>
        {sel.source !== 'MDK net-new' && <p className="muted" style={{ marginTop: 12 }}>{sel.source === 'Shipped (demo)' ? 'Already validated by the platform in this demo.' : sel.source === 'MDK HITL' ? 'Phase 2 — the pre-screen flags this risk statically and routes it to a human reviewer, who verifies and signs off.' : 'Covered by the partner’s automated engine for web; net-new only for PDF/Office formats.'}</p>}
      </div>
    </div>
  )
}

export default function WcagCoverage() {
  const [filter, setFilter] = useState('all')
  const [sel, setSel] = useState(null)

  const match = (r) => filter === 'all' ? true
    : filter === '2.2' ? r.added === '2.2'
    : filter === 'A' || filter === 'AA' ? r.level === filter
    : filter === 'Required' ? r.legal === 'Required'
    : filter === 'docs' ? r.docApplies
    : filter.startsWith('rem:') ? remTier(r) === filter.slice(4)
    : PHASE_FILTER[filter] ? r.phase.startsWith(PHASE_FILTER[filter])
    : r.source === filter

  const shown = WCAG.filter(match)
  const tally = (src) => WCAG.filter((r) => r.source === src).length
  const phaseCount = (ph) => ph.match ? WCAG.filter((r) => ph.match(r.phase)).length : null

  return (
    <>
      <div className="estatebar" style={{ marginTop: 6 }}>
        <div>
          <b>WCAG 2.1 + 2.2 conformance · US market</b> · all 87 success criteria
          <div className="muted" style={{ marginTop: 2 }}>each criterion with its level, US legal requirement, document applicability, plain-language requirement, and coverage today vs. the roadmap — click any cell for the full detail</div>
        </div>
        <div className="covlegend">
          {Object.entries(SRC).map(([k, [label, fg, bg]]) => (
            <span key={k} className="covkey"><i style={{ background: bg, borderColor: fg }} />{label} · {tally(k)}</span>
          ))}
        </div>
      </div>

      <div className="covstat">
        <div className="covstatcard"><b>{tally('Shipped (demo)')}</b><span className="muted">auto / AI-remediated live</span></div>
        <div className="covstatcard"><b style={{ color: '#1F5FA8' }}>{tally('MDK HITL')}</b><span className="muted">covered via human review · Phase 2</span></div>
        <div className="covstatcard"><b>{tally('Partner baseline')}</b><span className="muted">automated A/AA from partner</span></div>
        <div className="covstatcard"><b style={{ color: '#3B6D11' }}>✓ AA</b><span className="muted">every Required A/AA now covered</span></div>
      </div>

      <div className="levelramp">
        {LEVELS.map((lv, i) => (
          <div className="levelstep" key={lv.k}>
            <div className={lv.target ? 'levelcard target' : 'levelcard'}>
              <div className="leveltop"><span className="levelk">Level {lv.k}</span><span className="leveltag">{lv.tag}</span></div>
              <div className="leveldesc">{lv.desc}</div>
              <div className="muted levelex">e.g. {lv.ex}</div>
              {lv.target && <div className="leveltarget">★ This platform reports Level AA by default</div>}
            </div>
            {i < LEVELS.length - 1 && <span className="levelarrow" aria-hidden="true">→</span>}
          </div>
        ))}
      </div>

      <div className="roadmap">
        <div className="roadmaphd">
          <b>Delivery roadmap</b> <span className="muted">· Claude-paced — AI builds the checks, evals &amp; review scaffolds directly</span>
          <span className="roadmapnote">≈ 5× faster than a human dev team</span>
        </div>
        <div className="rmtrack">
          {ROADMAP_PHASES.map((ph, i) => {
            const cnt = phaseCount(ph)
            // P0/P1 are delivered with no useful filter; P2 (now covered) + P3 stay clickable
            const fkey = (ph.id === 'P0' || ph.id === 'P1') ? null : ph.id
            const active = fkey && filter === fkey
            const cntText = ph.done ? (cnt ? `✓ ${cnt} delivered` : '✓ delivered') : cnt != null ? `${cnt} criteria` : 'one-time'
            return (
              <div className="rmstep" key={ph.id}>
                <button className={`rmseg${active ? ' on' : ''}${fkey ? '' : ' static'}${ph.done ? ' done' : ''}`} onClick={() => fkey && setFilter(active ? 'all' : fkey)} disabled={!fkey} title={ph.desc}>
                  <div className="rmtop"><span className="rmid">{ph.id}{ph.done && ' ✓'}</span><span className="rmwhen">{ph.when}</span></div>
                  <div className="rmlabel">{ph.label}</div>
                  <div className="muted rmcnt">{cntText}</div>
                </button>
                {ph.milestone && <span className={`rmmilestone${ph.done ? ' reached' : ''}`} title={ph.done ? 'Legal target reached' : 'Legal target'}>{ph.done ? '✓' : '★'} {ph.milestone}{ph.done ? ' reached' : ''}</span>}
                {i < ROADMAP_PHASES.length - 1 && <span className="rmarrow" aria-hidden="true">→</span>}
              </div>
            )
          })}
        </div>
        <div className="muted rmfoot">Click a phase to filter the criteria below. These are AI-accelerated estimates — the human-team equivalent (~10–19 weeks) is in the LOE report.</div>
      </div>

      <div className="chiprow" style={{ margin: '4px 0 14px' }}>
        {FILTERS.map(([k, label]) => (
          <button key={k} className={filter === k ? 'fchip on' : 'fchip'} onClick={() => setFilter(k)}>{label}</button>
        ))}
      </div>

      <div className="autolegend">
        <b>Automatability</b> <span className="muted">· under no-UI automation — <b>Validate</b> (confirm a pass) vs <b>Remediate</b> (apply the fix). The dot on each tile is its remediate level:</span>
        {['green', 'amber', 'human'].map((k) => <span key={k} className="autokey"><i style={{ background: LV[k][2] }} />{LV[k][1]}</span>)}
      </div>

      {PRINCIPLES.map((p) => {
        const items = shown.filter((r) => r.principle === p)
        if (!items.length) return null
        return (
          <div className="covgroup" key={p}>
            <div className="covgrouphd">{p} <span className="muted">· {items.length}</span></div>
            <div className="covgrid">
              {items.map((r) => {
                const [, fg, bg] = SRC[r.source]
                const ph = PHASE_SHORT[r.phase]
                return (
                  <button key={r.sc} className="covcell" style={{ background: bg, borderColor: fg + '55' }} onClick={() => setSel(r)} title={`${r.sc} ${r.name} — ${r.req}`}>
                    <div className="covsc"><b>{r.sc}</b><span className="covlvl">{r.level}</span>{r.legal === 'Required' && <span className="covreq-flag" title="Required under US law">REQ</span>}{ph && <span className="covphase" style={{ color: ph[1], background: ph[2] }}>{ph[0]}</span>}{(() => { const lv = LV[remLevel(r)], vv = LV[valLevel(r)]; return <span className="covrem" style={{ color: lv[2], background: lv[3] }} title={`Validate: ${vv[1]} · Remediate: ${lv[1]}`}>{lv[0]}</span> })()}</div>
                    <div className="covname">{r.name}</div>
                    {WHY[r.sc] && <div className="covwhy"><span className="covwhylbl">Why</span> {WHY[r.sc]}</div>}
                    <div className="covtag" style={{ color: fg }}>{SRC[r.source][0]}{!r.docApplies && <span className="muted" style={{ fontWeight: 400 }}> · N/A docs</span>}</div>
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}

      {sel && <ScDetail sel={sel} onClose={() => setSel(null)} />}
    </>
  )
}
