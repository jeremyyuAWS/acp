import { useEffect } from 'react'

const CRIT = {
  SC_1_1_1: '1.1.1 non-text content', SC_1_3_1: '1.3.1 info & relationships',
  SC_1_3_2: '1.3.2 meaningful sequence', SC_2_1_1: '2.1.1 keyboard',
  SC_2_4_2: '2.4.2 page titled', SC_2_4_4: '2.4.4 link purpose',
  SC_3_1_1: '3.1.1 language of page', SC_1_4_3: '1.4.3 contrast',
}
const critLabel = (w) => CRIT[w] ?? (w || '').replace(/^SC_/, '').replace(/_/g, '.')
const SEV = {
  CRITICAL: ['#FCEBEB', '#A32D2D'], SERIOUS: ['#FAECE7', '#993C1D'],
  MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'],
}
const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'certifiable' : 'issues')
const STATUS_BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'],
  uncertain: ['#FAECE7', '#993C1D'], unanalysable: ['#EEEDEA', '#5F5E5A'],
}

const STEPS = ['Discover', 'Classify', 'Retain', 'Assess', 'Risk score', 'Remediate', 'Human review', 'Re-validate', 'Publish', 'Monitor']
function journeyStates(st) {
  if (st === 'unanalysable') return ['done', 'done', 'done', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked']
  const base = ['done', 'done', 'done', 'done', 'done']
  if (st === 'certifiable') return [...base, 'skip', 'skip', 'done', 'proj', 'proj']
  return [...base, 'current', 'proj', 'proj', 'proj', 'proj'] // issues / uncertain
}
const STATE = {
  done: ['✓', '#3B6D11', '#E7F0DC'], current: ['●', '#854F0B', '#FAEEDA'],
  proj: ['◯', '#8a8390', '#f1eff4'], blocked: ['✕', '#A32D2D', '#FCEBEB'],
  skip: ['–', '#8a8390', '#f1eff4'],
}
const STATE_NOTE = { proj: 'projected', skip: 'not needed', blocked: 'blocked', current: 'in progress' }

export default function FileDrawer({ file, onClose }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  if (!file) return null

  const st = statusOf(file)
  const [sbg, sfg] = STATUS_BADGE[st]
  const issues = file.issues || []
  const byCrit = {}
  issues.forEach((i) => { byCrit[i.wcag] = (byCrit[i.wcag] || 0) + 1 })
  const states = journeyStates(st)

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Details for ${file.file}`} onClick={(e) => e.stopPropagation()}>
        <div className="drawerhead">
          <div>
            <div className="fname" style={{ fontSize: 15 }}>{file.file}</div>
            <div className="muted" style={{ marginTop: 4 }}>{file.engine}</div>
          </div>
          <button className="ghost small" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        <div className="drawerstats">
          <span className="badge" style={{ background: sbg, color: sfg }}>{st}</span>
          <span className="drawerscore">{file.score === null ? 'n/a' : `${st === 'uncertain' ? '≤' : ''}${file.score}`}<span className="muted"> / 100</span></span>
          {st === 'uncertain' && <span className="muted">{file.skipped_rules} rule(s) skipped — score is an upper bound</span>}
        </div>

        <h4 className="drawerh">Findings {issues.length > 0 && <span className="muted">({issues.length})</span>}</h4>
        {issues.length === 0 ? (
          <p className="muted">{st === 'unanalysable' ? 'Could not analyse — file unreadable.' : 'No findings — clean.'}</p>
        ) : (
          <div className="findings">
            {issues.map((i, n) => {
              const [bg, fg] = SEV[i.severity] || SEV.MINOR
              return (
                <div className="finding" key={n}>
                  <span className="badge" style={{ background: bg, color: fg }}>{(i.severity || '').toLowerCase()}</span>
                  <div className="findingmain">
                    <div>{critLabel(i.wcag)}</div>
                    <div className="muted fname" style={{ fontSize: 12 }}>{i.rule_id ?? i.ruleId}</div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {Object.keys(byCrit).length > 0 && (
          <>
            <h4 className="drawerh">WCAG criteria failing</h4>
            <div className="critlist">
              {Object.entries(byCrit).sort((a, b) => b[1] - a[1]).map(([w, n]) => (
                <div className="critlistrow" key={w}><span>{critLabel(w)}</span><b>{n}</b></div>
              ))}
            </div>
          </>
        )}

        <h4 className="drawerh">Document journey</h4>
        <ol className="journeyline">
          {STEPS.map((label, i) => {
            const [glyph, color, bg] = STATE[states[i]]
            const note = STATE_NOTE[states[i]]
            return (
              <li className="jrow" key={label}>
                <span className="jdot" style={{ color, background: bg }} aria-hidden="true">{glyph}</span>
                <span className="jlabel">{label}{i === 3 && file.score !== null ? ` · ${st === 'uncertain' ? '≤' : ''}${file.score}` : ''}</span>
                {note && <span className="muted jnote">{note}</span>}
              </li>
            )
          })}
        </ol>
      </aside>
    </div>
  )
}
