import Drawer from './Drawer.jsx'
import Tag from './Tag.jsx'

// Prescriptive-action styling, shared with the Discover inventory.
// Distinct hue per action so a long list scans at a glance. The human-touch
// actions form an intuitive escalation — blue (light approve) → amber (evaluate)
// → red (rebuild) — while no-human actions sit in the green/teal/slate family.
export const REC_STYLE = {
  auto: ['Auto-remediate', '#E3F1D8', '#2E6B0E', '⚡'],
  assisted: ['Remediate + review', '#E2EDFB', '#1F5FA8', '✎'],
  review: ['Human review', '#FBEBCB', '#8A5A00', '◐'],
  archive: ['Archive', '#ECEEF1', '#475569', '📦'],
  keep: ['Keep · monitor', '#D8F0EA', '#176B5B', '✓'],
  manual: ['Manual rebuild', '#E2EDFB', '#1F5FA8', '⚠'],
}
export const fmtEffort = (m) => m == null ? '—' : m === 0 ? 'no work' : m >= 90 ? `~${(m / 60).toFixed(1)} hrs` : `~${Math.round(m)} min`
const MODE_LABEL = { auto: 'fully automatic', assisted: 'AI + human review', manual: 'manual', monitor: 'monitor only' }

// Where the document actually lives — so a reviewer can open it to remediate manually,
// or open a superseded doc to compare/replace. In the demo the link opens the source
// system; in production it deep-links straight to the file.
export const SOURCE_URL = {
  'SharePoint': 'https://www.office.com/launch/sharepoint', 'Google Drive': 'https://drive.google.com/drive/my-drive',
  'Box': 'https://app.box.com/folder/0', 'Confluence': 'https://www.atlassian.com/wiki', 'Website / CMS': null,
}
export function FileLocation({ file }) {
  const url = SOURCE_URL[file.sourceName]
  return (
    <div className="floc">
      <div className="flocpath"><span className="muted">location · </span>{file.sourceName || 'Source'} <span className="muted">›</span> {file.dept || 'Unfiled'} <span className="muted">›</span> <b>{file.file}</b></div>
      {url
        ? <a className="ghost small flocbtn" href={url} target="_blank" rel="noopener noreferrer">↗ Open in {file.sourceName}</a>
        : <span className="flocbtn muted" style={{ fontSize: 12 }}>public web page · open in your CMS</span>}
      {file.superseded && <div className="flocsuper">⚠ A <b>newer version</b> of this document exists — open the source to compare or replace the superseded copy.</div>}
    </div>
  )
}

const CRIT = {
  SC_1_1_1: '1.1.1 non-text content', SC_1_3_1: '1.3.1 info & relationships',
  SC_1_3_2: '1.3.2 meaningful sequence', SC_2_1_1: '2.1.1 keyboard',
  SC_2_4_2: '2.4.2 page titled', SC_2_4_4: '2.4.4 link purpose',
  SC_3_1_1: '3.1.1 language of page', SC_1_4_3: '1.4.3 contrast',
  SC_1_2_1: '1.2.1 audio/video transcript', SC_1_2_2: '1.2.2 captions',
  SC_1_2_3: '1.2.3 audio description / alt', SC_1_2_5: '1.2.5 audio description',
}
export const critLabel = (w) => CRIT[w] ?? (w || '').replace(/^SC_/, '').replace(/_/g, '.')
const SEV = {
  CRITICAL: ['#E2EDFB', '#1F5FA8'], SERIOUS: ['#E6EFFB', '#2A5E9E'],
  MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'],
}
const SEV_LEGEND = [
  ['critical', '#1F5FA8', '#E2EDFB', 'Completely blocks a group of users — e.g. an unlabelled image or a keyboard trap. Almost always WCAG Level A.'],
  ['serious', '#2A5E9E', '#E6EFFB', 'A major barrier that’s hard to work around — e.g. missing table headers or an empty document title.'],
  ['moderate', '#854F0B', '#FAEEDA', 'Noticeable difficulty, but the content is still reachable — e.g. wrong reading order or undeclared language.'],
  ['minor', '#5F5E5A', '#F1EFE8', 'A minor annoyance or best-practice gap — e.g. unclear worksheet names.'],
]
export const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'certifiable' : 'issues')
export const STATUS_BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'],
  uncertain: ['#E6EFFB', '#2A5E9E'], unanalysable: ['#EEEDEA', '#5F5E5A'],
}

// Retention/lifecycle recommendation (step 3 · Retain / Archive / Delete) — based
// purely on metadata + risk flags, NOT on accessibility findings (that's Assess).
export function retentionOf(f) {
  if (f.locked) return { label: 'Could not open', bg: '#EEEDEA', fg: '#5F5E5A', why: `${f.openIssue || 'could not open'} — provide credentials or an accessible export so this document can be classified and assessed.` }
  if ((f.tags || []).includes('legal-hold')) return { label: 'Retain · legal hold', bg: '#FAEEDA', fg: '#854F0B', why: 'Under legal hold — must be retained regardless of age or usage.' }
  if (f.superseded) return { label: 'Archive', bg: '#EEEDFE', fg: '#3C3489', why: 'A newer version exists — archive to shrink the audited estate.' }
  if (f.ageDays >= 540 && f.views90d < 60) return { label: 'Archive candidate', bg: '#EEEDFE', fg: '#3C3489', why: `Last edited ${f.modifiedAge} with ${f.views90d} views/90d — low value to keep live.` }
  return { label: 'Keep', bg: '#E7F0DC', fg: '#3B6D11', why: 'Active and in use — keep in the live estate.' }
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
  proj: ['◯', '#8a8390', '#f1eff4'], blocked: ['✕', '#1F5FA8', '#E2EDFB'],
  skip: ['–', '#8a8390', '#f1eff4'],
}
const STATE_NOTE = { proj: 'projected', skip: 'not needed', blocked: 'blocked', current: 'in progress' }

export default function FileDrawer({ file, onClose, context = 'full' }) {
  if (!file) return null
  const st = statusOf(file)
  const [sbg, sfg] = STATUS_BADGE[st]
  const issues = file.issues || []
  const byCrit = {}
  issues.forEach((i) => { byCrit[i.wcag] = (byCrit[i.wcag] || 0) + 1 })
  const states = journeyStates(st)

  const metaBlock = (
    <>
      <h4 className="drawerh">Document metadata</h4>
      <div className="metagrid">
        <div><span className="muted">Last modified</span><b>{file.modifiedAge || '—'}</b></div>
        <div><span className="muted">Last accessed</span><b>{file.lastAccessed || '—'}</b></div>
        <div><span className="muted">Views · 90d</span><b>{file.views90d != null ? file.views90d.toLocaleString() : '—'}</b></div>
        <div><span className="muted">Size</span><b>{file.sizeKB ? (file.sizeKB >= 1024 ? `${(file.sizeKB / 1024).toFixed(1)} MB` : `${file.sizeKB} KB`) : '—'}</b></div>
        <div><span className="muted">{file.duration ? 'Duration' : file.sheets ? 'Sheets' : 'Pages'}</span><b>{file.duration || file.pages || file.sheets || '—'}</b></div>
        <div><span className="muted">Owner</span><b>{file.owner || '—'}</b></div>
      </div>
    </>
  )
  const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
  const shownTags = context === 'discover' ? (file.tags || []).filter((t) => !STATUS_TAGS.has(t)) : (file.tags || [])
  const tagBlock = shownTags.length > 0 && (
    <>
      <h4 className="drawerh">{context === 'discover' ? 'Classification · auto-assigned by agent' : 'Tags · auto-assigned by agent'}</h4>
      <div className="taglist">{shownTags.map((t) => <Tag key={t} t={t} />)}</div>
    </>
  )

  // Discover (steps 1–3): inventory · classify · retain — NO accessibility assessment.
  if (context === 'discover') {
    const ret = retentionOf(file)
    return (
      <Drawer title={file.file} subtitle={`${file.sourceName ? `${file.sourceName} · ${file.dept} · ` : ''}${(file.type || '').toUpperCase()}`} onClose={onClose}>
        {file.locked && <div className="lockbanner">🔒 Could not open — <b>{file.openIssue}</b>. Discovered from its metadata, but the content couldn’t be read.</div>}
        {tagBlock}
        {metaBlock}
        <FileLocation file={file} />
        <h4 className="drawerh">Retention recommendation</h4>
        <div className="reccard" style={{ borderColor: ret.fg + '55' }}>
          <span className="recbadge" style={{ background: ret.bg, color: ret.fg }}>{ret.label}</span>
          <p className="recwhy" style={{ marginBottom: 0, marginTop: 9 }}>{ret.why}</p>
        </div>
        <p className="muted" style={{ marginTop: 14, fontSize: 12 }}>Accessibility findings &amp; score are evaluated in the Assess step.</p>
      </Drawer>
    )
  }

  return (
    <Drawer title={file.file} subtitle={`${file.sourceName ? `${file.sourceName} · ${file.dept} · ` : ''}${file.engine}`} onClose={onClose}>
      <div className="drawerstats">
        <span className="badge" style={{ background: sbg, color: sfg }}>{st}</span>
        <span className="drawerscore">{file.score === null ? 'n/a' : `${st === 'uncertain' ? '≤' : ''}${file.score}`}<span className="muted"> / 100</span></span>
        {st === 'uncertain' && <span className="muted">{file.skipped_rules} rule(s) skipped — score is an upper bound</span>}
      </div>

      {file.rec && (() => {
        const r = file.rec; const [label, bg, fg, icon] = REC_STYLE[r.action] || REC_STYLE.review
        return (
          <div className="reccard" style={{ borderColor: fg + '55' }}>
            <div className="recheadrow">
              <span className="recbadge" style={{ background: bg, color: fg }}>{icon} {label}</span>
              <span className="receta">{fmtEffort(r.etaMin)}</span>
            </div>
            <p className="recwhy">{r.rationale}</p>
            <div className="recmeta">
              <span><b>{MODE_LABEL[r.mode] || r.mode}</b><span className="muted"> mode</span></span>
              {r.confidence != null && <span><b>{r.confidence}%</b><span className="muted"> confidence</span></span>}
              {r.savingsPct != null && r.savingsPct > 0 && <span style={{ color: '#3B6D11' }}><b>{r.savingsPct}%</b><span className="muted"> faster than manual</span></span>}
            </div>
          </div>
        )
      })()}

      {metaBlock}
      <FileLocation file={file} />

      {tagBlock}

      <h4 className="drawerh">Findings {issues.length > 0 && <span className="muted">({issues.length})</span>}</h4>
      {issues.length === 0 ? (
        <p className="muted">{st === 'unanalysable' ? 'Could not analyse — file unreadable.' : 'No findings — clean.'}</p>
      ) : (
        <>
          <div className="findings">
            {issues.map((i, n) => {
              const [bg, fg] = SEV[i.severity] || SEV.MINOR
              return (
                <div className="finding" key={n}>
                  <span className="badge" style={{ background: bg, color: fg }}>{(i.severity || '').toLowerCase()}</span>
                  <div className="findingmain">
                    <div className="findingtop">{critLabel(i.wcag)}{i.level && <span className="lvlchip">Level {i.level}</span>}</div>
                    {i.detail && <div className="findingdetail">{i.detail}</div>}
                    {i.impact && <div className="muted findingimpact">{i.impact}</div>}
                    {i.fix && <div className="findingfix"><span className={i.auto ? 'fixauto' : 'fixreview'}>{i.auto ? '⚡ auto-fixable' : '✎ needs review'}</span> · {i.fix}<span className="muted"> · {i.rule_id ?? i.ruleId}</span></div>}
                  </div>
                </div>
              )
            })}
          </div>
          <details className="sevhelp">
            <summary>How is severity classified?</summary>
            <p className="muted" style={{ margin: '8px 0' }}>Severity reflects <b>user impact × how many users are affected × the WCAG level</b> (A is the most fundamental). It follows the axe-core / engine impact model — independent of which rule fired.</p>
            {SEV_LEGEND.map(([name, fg, bg, desc]) => (
              <div className="sevrow" key={name}>
                <span className="badge" style={{ background: bg, color: fg, flex: '0 0 auto' }}>{name}</span>
                <span className="muted">{desc}</span>
              </div>
            ))}
          </details>
        </>
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
    </Drawer>
  )
}
