import { useState, useRef } from 'react'
import { WCAG } from './wcagCatalog.js'
import { useDialog } from './a11y.js'

// WCAG 2.1 + 2.2 coverage matrix — all 87 success criteria, colour-coded by what
// the platform checks today vs. what's on the roadmap beyond the partner. Backs
// the "we go beyond a raw scanner" story with the real catalog + LOE estimate.
const SRC = {
  'Shipped (demo)': ['Live now', '#3B6D11', '#E7F0DC'],
  'Partner baseline': ['Partner-provided', '#3C3489', '#EEEDFE'],
  'MDK net-new': ['Roadmap', '#854F0B', '#FAEEDA'],
}
const PRINCIPLES = ['Perceivable', 'Operable', 'Understandable', 'Robust']
const FILTERS = [
  ['all', 'All 87'], ['A', 'Level A'], ['AA', 'Level AA'], ['2.2', 'New in 2.2'],
  ['Required', 'US Required'], ['docs', 'Applies to documents'],
  ['Shipped (demo)', 'Live now'], ['MDK net-new', 'Roadmap'],
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
  { id: 'P0', label: 'Foundation', when: 'Days 1–2', match: null, desc: 'Coverage audit vs. partner · lock the check contract · stand up the golden-corpus eval harness.' },
  { id: 'P1', label: 'Agentic AI checks', when: 'Days 3–5', match: (p) => p.startsWith('Phase 1'), desc: 'Semantic LLM evaluators — sensory characteristics, headings & labels. Claude authors prompt + evals.' },
  { id: 'P2', label: 'Human-in-the-loop', when: 'Weeks 2–3', match: (p) => p.startsWith('Phase 2'), milestone: 'Level AA conformance', desc: 'Pre-screen detectors + reviewer workflow for the manual Required criteria (captions, focus order, errors…).' },
  { id: 'P3', label: 'AAA / optional', when: 'Weeks 4–6', match: (p) => p.startsWith('Phase 3'), desc: 'Everything not legally required — pursued selectively.' },
]
const PHASE_SHORT = {
  'Phase 1 · Agentic (Req. A/AA)': ['Phase 1', '#3C3489', '#EEEDFE'],
  'Phase 2 · HITL (Req. A/AA)': ['Phase 2', '#854F0B', '#FAEEDA'],
  'Phase 3 · Optional / AAA': ['Phase 3', '#5F5E5A', '#EFEDEA'],
}
const PHASE_FILTER = { P1: 'Phase 1', P2: 'Phase 2', P3: 'Phase 3' }

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
        <div className="levelnote">Level {sel.level} — {LEVEL_MEANING[sel.level]}</div>
        <div className="covrows">
          <div><span className="muted">US legal requirement</span><b style={{ color: sel.legal === 'Required' ? '#A32D2D' : 'var(--ink)' }}>{sel.legal}</b></div>
          <div><span className="muted">Document applicability</span><b style={{ color: sel.docApplies ? '#3B6D11' : 'var(--muted)' }}>{sel.docApplies ? 'Applies to documents' : 'Web / interaction — N/A to static docs'}</b></div>
          <div><span className="muted">Validation approach</span><b>{sel.approach}</b></div>
          <div><span className="muted">Coverage today</span><b style={{ color: SRC[sel.source][1] }}>{SRC[sel.source][0]}</b></div>
          <div><span className="muted">Build tier</span><b>{sel.tier}</b></div>
          <div><span className="muted">Roadmap phase</span><b>{sel.phase}</b></div>
          {sel.source === 'MDK net-new' && (() => { const ph = ROADMAP_PHASES.find((x) => x.match && x.match(sel.phase)); return ph ? <div><span className="muted">Timeline · Claude-paced</span><b>{ph.when}</b></div> : null })()}
          {sel.source === 'MDK net-new' && <div><span className="muted">Effort (human team)</span><b>{sel.lo}–{sel.hi} dev-days</b></div>}
        </div>
        {sel.source !== 'MDK net-new' && <p className="muted" style={{ marginTop: 12 }}>{sel.source === 'Shipped (demo)' ? 'Already validated by the platform in this demo.' : 'Covered by the partner’s automated engine for web; net-new only for PDF/Office formats.'}</p>}
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
    : PHASE_FILTER[filter] ? r.phase.startsWith(PHASE_FILTER[filter])
    : r.source === filter

  const shown = WCAG.filter(match)
  const tally = (src) => WCAG.filter((r) => r.source === src).length
  const phaseCount = (ph) => ph.match ? WCAG.filter((r) => ph.match(r.phase)).length : null
  const net = WCAG.filter((r) => r.source === 'MDK net-new')

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
        <div className="covstatcard"><b>{tally('Shipped (demo)')}</b><span className="muted">checks live in this demo</span></div>
        <div className="covstatcard"><b>{tally('Partner baseline')}</b><span className="muted">automated A/AA from partner</span></div>
        <div className="covstatcard"><b>{net.length}</b><span className="muted">net-new beyond partner</span></div>
        <div className="covstatcard"><b>~3 wks</b><span className="muted">to Level AA · Claude-paced build</span></div>
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
            const fkey = ph.id === 'P0' ? null : ph.id
            const active = fkey && filter === fkey
            return (
              <div className="rmstep" key={ph.id}>
                <button className={`rmseg${active ? ' on' : ''}${fkey ? '' : ' static'}`} onClick={() => fkey && setFilter(active ? 'all' : fkey)} disabled={!fkey} title={ph.desc}>
                  <div className="rmtop"><span className="rmid">{ph.id}</span><span className="rmwhen">{ph.when}</span></div>
                  <div className="rmlabel">{ph.label}</div>
                  <div className="muted rmcnt">{cnt != null ? `${cnt} criteria` : 'one-time'}</div>
                </button>
                {ph.milestone && <span className="rmmilestone" title="Legal target reached">★ {ph.milestone}</span>}
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
                    <div className="covsc"><b>{r.sc}</b><span className="covlvl">{r.level}</span>{r.legal === 'Required' && <span className="covreq-flag" title="Required under US law">REQ</span>}{ph && <span className="covphase" style={{ color: ph[1], background: ph[2] }}>{ph[0]}</span>}</div>
                    <div className="covname">{r.name}</div>
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
