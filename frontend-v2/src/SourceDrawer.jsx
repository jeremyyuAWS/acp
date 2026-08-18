import { useState, useEffect } from 'react'
import Drawer from './Drawer.jsx'
import { retentionOf } from './FileDrawer.jsx'
import { listDispositionPolicies } from './api.js'
import {
  filesForSource, runsForSource, inventoryFacts, dispositionRows, dispositionOf,
  runOutcome, runDurationMs, needsAttention, scopeFacts, folderOf,
  fmtSize, fmtDuration, fmtWhen, fmtCount, orAbsent, NOT_AVAILABLE, NOT_CONFIGURED,
} from './sourceOps.js'

// "Manage <source>" — a SOURCE OPERATIONS panel, not a miniature compliance dashboard.
//
// What this replaced, and why: the drawer used to open on a compliance donut, a top-flagged-
// documents list and a paragraph about an "agent", under the subtitle
// `undefined · 0 docs · agent: undefined`. Every one of those is an Assess fact rendered on a
// Sources surface, and the subtitle was actively false — the card beside it said **Healthy**
// while the drawer said the connection had no department, no documents and no agent. (It had
// all three: the OneDrive card is a hard-coded CONNECTABLE row with no `dept`/`agent`, and its
// file rows are keyed `sharepoint`, not `sp-root`. See sourceOps.sourceKeys.)
//
// The four tabs answer the four questions an operator actually opens this for: is the
// connection working (Overview), what can ACP see (Scope), what happened to the files (Rules),
// and what has this source been doing (Activity). Compliance stays in Assess; the only bridge
// is a stated handoff count on Overview.
//
// Colour discipline: red means access failed. Archive/delete candidates are amber — they are
// awaiting a human, not broken.

const TONE = {
  ok:     ['#3B6D11', '#E7F0DC'],
  review: ['#854F0B', '#FAEEDA'],
  fail:   ['#A32D2D', '#FCEBEB'],
  muted:  ['#5F5E5A', '#EEEDEA'],
}
const TABS = ['Overview', 'Scope', 'Rules', 'Activity']

const Pill = ({ tone = 'muted', children }) => {
  const [fg, bg] = TONE[tone] || TONE.muted
  return <span className="badge" style={{ background: bg, color: fg }}>{children}</span>
}

// A label/value row. `value` of null prints the stated absence rather than the field vanishing —
// a dropped row and a configured-but-empty row are indistinguishable once one of them is gone.
const Fact = ({ label, value, absent = NOT_CONFIGURED }) => (
  <div style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
    <span className="muted" style={{ flex: '0 0 118px' }}>{label}</span>
    <span style={{ flex: 1, minWidth: 0, wordBreak: 'break-word' }}>{orAbsent(value, absent)}</span>
  </div>
)

const Kpi = ({ label, value }) => (
  <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px', background: 'var(--surface)' }}>
    <div style={{ fontSize: 19, fontWeight: 600, lineHeight: 1.2 }}>{value}</div>
    <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{label}</div>
  </div>
)

export default function SourceDrawer({ source, files = [], scans = [], onClose, onPickFile, onScan, onOpenAssess, busy = false }) {
  const [tab, setTab] = useState('Overview')
  const [policies, setPolicies] = useState(null)   // null = still loading / unavailable
  const [policyErr, setPolicyErr] = useState('')

  // Discovery rules are a real backend resource (disposition policies), so they are fetched, not
  // described. A failed fetch says so; it does not fall back to an encouraging empty list, which
  // would read as "no rules configured" — the one answer that stops an operator looking.
  useEffect(() => {
    if (!source) return
    let live = true
    listDispositionPolicies()
      .then((p) => { if (live) setPolicies(Array.isArray(p) ? p : []) })
      .catch((e) => { if (live) { setPolicies([]); setPolicyErr(e?.message || 'could not load discovery rules') } })
    return () => { live = false }
  }, [source])

  if (!source) return null

  const labelOf = (f) => retentionOf(f).label
  const mine = filesForSource(files, source)
  const runs = runsForSource(scans, source)
  const latest = runs[0] || null
  const outcome = runOutcome(latest)
  const inv = inventoryFacts(mine)
  const rows = dispositionRows(mine, labelOf)
  const attention = needsAttention({ files: mine, runs, labelOf })
  const assessable = rows.find((r) => r.key === 'assessable')?.count || 0
  const title = `Manage ${source.name || source.type || 'source'}`

  // The header states the connection first, because that is the question the drawer is opened
  // with. "Connected" is a fact about the token; the run outcome is a separate fact and is never
  // folded into it — a connected source whose last run could not read 18 files is both.
  const subtitle = latest
    ? `Connected · Last discovery ${fmtWhen(latest.completed_at)} · ${outcome.label}`
    : 'Connected · No discovery completed yet'

  return (
    <Drawer title={title} subtitle={subtitle} onClose={onClose}>
      <div className="subtabs" role="tablist" aria-label="Source operations">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab${tab === t ? ' on' : ''}`}
                  style={{ display: 'inline-block', padding: '5px 12px', fontSize: 13 }}
                  onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {attention.length > 0 ? (
        <>
          <h4 className="drawerh">Needs attention <span style={{ float: 'right' }}>{attention.length}</span></h4>
          <div style={{ display: 'grid', gap: 8 }}>
            {attention.map((a) => {
              const [fg, bg] = TONE[a.tone] || TONE.muted
              return (
                <div key={a.key} style={{ background: bg, borderRadius: 9, padding: '9px 11px' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: fg }}>{a.title}</div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{a.detail}</div>
                </div>
              )
            })}
          </div>
        </>
      ) : (
        <p style={{ marginTop: 16, fontSize: 13, color: TONE.ok[0] }}>✓ No discovery issues</p>
      )}

      {tab === 'Overview' && (
        <>
          <h4 className="drawerh">Discovery summary</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            <Kpi label="documents discovered" value={fmtCount(inv.documents)} />
            <Kpi label="total size" value={fmtSize(inv.bytesKb)} />
            <Kpi label="owners" value={fmtCount(inv.owners)} />
            <Kpi label="departments" value={fmtCount(inv.departments)} />
          </div>

          <h4 className="drawerh">Latest discovery</h4>
          {!latest ? (
            <p className="muted" style={{ fontSize: 13 }}>
              No discovery has completed. ACP has access, but the source has not yet been inventoried.
            </p>
          ) : (
            <div style={{ fontSize: 13 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <Pill tone={outcome.key === 'ok' ? 'ok' : outcome.key === 'warn' ? 'review' : 'muted'}>{outcome.label}</Pill>
                <span className="muted">{fmtWhen(latest.completed_at)}</span>
              </div>
              <Fact label="Files examined" value={latest.files != null ? Number(latest.files).toLocaleString() : null} absent={NOT_AVAILABLE} />
              <Fact label="Could not read" value={latest.error != null ? Number(latest.error).toLocaleString() : null} absent={NOT_AVAILABLE} />
              <Fact label="Duration" value={runDurationMs(latest) == null ? null : fmtDuration(runDurationMs(latest))} absent={NOT_AVAILABLE} />
              <Fact label="Run ID" value={latest.id} absent={NOT_AVAILABLE} />
            </div>
          )}

          <h4 className="drawerh">Discovery outcome</h4>
          {/* A partition: every discovered file is in exactly one row and the rows sum to the
              total, so the table can be added up. Overlapping tallies cannot. */}
          <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                    <Pill tone={r.tone}>{r.label}</Pill>
                  </td>
                  <td style={{ padding: '6px 0', borderBottom: '1px solid var(--line)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {r.count.toLocaleString()}
                  </td>
                </tr>
              ))}
              <tr>
                <td className="muted" style={{ padding: '6px 0' }}>Total discovered</td>
                <td className="muted" style={{ padding: '6px 0', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {inv.documents.toLocaleString()}
                </td>
              </tr>
            </tbody>
          </table>

          <h4 className="drawerh">Next step</h4>
          <p className="muted" style={{ fontSize: 13 }}>
            {assessable.toLocaleString()} discovered file{assessable === 1 ? ' is' : 's are'} eligible for assessment.
            Archive and deletion candidates are held back until they are reviewed.
          </p>
          {onOpenAssess && <button className="ghost small" onClick={onOpenAssess}>Open Assess</button>}
        </>
      )}

      {tab === 'Scope' && (
        <>
          <h4 className="drawerh">Discovery scope</h4>
          <Fact label="Source" value={source.name || source.type} absent={NOT_AVAILABLE} />
          {scopeFacts(source).map((f) => <Fact key={f.label} label={f.label} value={f.value} />)}

          <h4 className="drawerh">Locations</h4>
          <LocationList files={mine} />

          <h4 className="drawerh">Not covered</h4>
          {/* Three operationally different things, never merged into one "excluded" number:
              a rule we configured, a permission Microsoft/Google refused, and a read that
              failed. Only the middle one is a connection problem. */}
          <UncoveredList files={mine} labelOf={labelOf} latest={latest} />
        </>
      )}

      {tab === 'Rules' && (
        <>
          <h4 className="drawerh">
            Active discovery rules
            {policies && <span style={{ float: 'right' }}>{policies.filter((p) => p.enabled !== false).length}</span>}
          </h4>
          {policies == null ? <p className="muted" style={{ fontSize: 13 }}>Loading…</p>
            : policyErr ? <p style={{ fontSize: 13, color: TONE.fail[0] }}>Could not load discovery rules — {policyErr}</p>
              : policies.length === 0 ? (
                <p className="muted" style={{ fontSize: 13 }}>
                  No discovery rules are configured. Rules tag, archive or flag files for deletion review
                  as they are discovered; without any, every discovered file is inventoried and left in place.
                </p>
              ) : (
                <div className="findings">
                  {policies.map((p) => (
                    <div key={p.policy_id || p.name} style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>{orAbsent(p.name)}</span>
                        <Pill tone={p.action === 'delete' ? 'review' : p.action === 'archive' ? 'review' : 'muted'}>
                          {p.action === 'delete' ? 'deletion review' : orAbsent(p.action)}
                        </Pill>
                        <Pill tone={p.enabled === false ? 'muted' : 'ok'}>{p.enabled === false ? 'disabled' : 'enabled'}</Pill>
                      </div>
                      <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
                        {(p.match || []).map((m) => `${m.field} ${m.op} ${m.value}`).join(' · ') || NOT_AVAILABLE}
                      </div>
                    </div>
                  ))}
                </div>
              )}
          <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            A delete rule tags files for <b>deletion review</b>. ACP never deletes on a rule alone —
            an approval is recorded first, and the action is a recoverable trash move.
          </p>
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            These are <b>lifecycle rules</b> — they tag, archive or flag files as they are discovered.
            <i> Which WCAG criteria</i> get assessed where is set separately, under
            <b> Assess → WCAG scope rules</b>.
          </p>
        </>
      )}

      {tab === 'Activity' && (
        <>
          <h4 className="drawerh">Recent activity</h4>
          {runs.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>No discovery runs recorded for this source.</p>
          ) : (
            <div className="findings">
              {runs.slice(0, 12).map((r) => {
                const o = runOutcome(r)
                return (
                  <details key={r.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                    <summary style={{ cursor: 'pointer', fontSize: 13, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span className="muted">{fmtWhen(r.completed_at || r.started_at)}</span>
                      <Pill tone={o.key === 'ok' ? 'ok' : o.key === 'warn' ? 'review' : 'muted'}>{o.label}</Pill>
                      <span className="muted">
                        {r.files != null ? `${Number(r.files).toLocaleString()} examined` : NOT_AVAILABLE}
                        {(r.error || 0) > 0 && ` · ${Number(r.error).toLocaleString()} could not be read`}
                      </span>
                    </summary>
                    <div style={{ marginTop: 6 }}>
                      <Fact label="Started" value={r.started_at ? fmtWhen(r.started_at) : null} absent={NOT_AVAILABLE} />
                      <Fact label="Completed" value={r.completed_at ? fmtWhen(r.completed_at) : null} absent={NOT_AVAILABLE} />
                      <Fact label="Duration" value={runDurationMs(r) == null ? null : fmtDuration(runDurationMs(r))} absent={NOT_AVAILABLE} />
                      <Fact label="Files examined" value={r.files != null ? Number(r.files).toLocaleString() : null} absent={NOT_AVAILABLE} />
                      <Fact label="Could not read" value={r.error != null ? Number(r.error).toLocaleString() : null} absent={NOT_AVAILABLE} />
                      <Fact label="Started by" value={r.owner_email} absent={NOT_AVAILABLE} />
                      <Fact label="Run ID" value={r.id} absent={NOT_AVAILABLE} />
                    </div>
                  </details>
                )
              })}
            </div>
          )}
          {onPickFile && mine.length > 0 && (
            <>
              <h4 className="drawerh">Files that could not be read</h4>
              <UnreadableFiles files={mine} labelOf={labelOf} onPickFile={onPickFile} />
            </>
          )}
        </>
      )}

      {/* Persistent footer — configuration actions stay reachable from every tab. */}
      <div style={{ position: 'sticky', bottom: 0, marginTop: 22, paddingTop: 12,
                    borderTop: '1px solid var(--line)', background: 'var(--card)',
                    display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {onScan && <button disabled={busy} onClick={() => onScan(source)}>{busy ? 'Discovering…' : 'Run discovery'}</button>}
        <button className="ghost small" onClick={onClose}>Close</button>
      </div>
    </Drawer>
  )
}

// Folders ACP actually saw. A source that reports bare filenames has no folder structure to
// show — that is stated, not rendered as "0 locations", which reads as a scope problem.
function LocationList({ files }) {
  const folders = [...new Set(files.map(folderOf).filter(Boolean))].sort()
  if (!folders.length) {
    return (
      <p className="muted" style={{ fontSize: 13 }}>
        {NOT_AVAILABLE} — this source reports flat file names, so ACP has no folder structure to list.
        The discovery boundary above is what limits what it reads.
      </p>
    )
  }
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: 13 }}>
      {folders.slice(0, 40).map((f) => (
        <li key={f} style={{ padding: '4px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ color: TONE.ok[0] }}>✓</span> /{f}
        </li>
      ))}
      {folders.length > 40 && <li className="muted" style={{ padding: '4px 0' }}>+{folders.length - 40} more</li>}
    </ul>
  )
}

// The three reasons a file is not in the assessable set, kept apart on purpose.
function UncoveredList({ files, labelOf, latest }) {
  const excluded = files.filter((f) => dispositionOf(f, labelOf) === 'excluded').length
  const unreadable = files.filter((f) => dispositionOf(f, labelOf) === 'unreadable').length
  const runErr = latest && (latest.error || 0) > 0 ? latest.error : 0
  const items = [
    ['Excluded by a configured rule', excluded, 'muted',
      'ACP was told not to inventory these.'],
    ['Inaccessible — permission denied', unreadable, 'fail',
      'The source refused access, or the file could not be opened with the credentials ACP holds.'],
    ['Failed during the last discovery run', runErr, 'fail',
      'Read errors reported by the most recent run.'],
  ].filter(([, n]) => n > 0)
  if (!items.length) return <p className="muted" style={{ fontSize: 13 }}>Everything in scope was read.</p>
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {items.map(([label, n, tone, why]) => (
        <div key={label} style={{ fontSize: 13 }}>
          <Pill tone={tone}>{Number(n).toLocaleString()}</Pill>{' '}
          <b style={{ fontWeight: 600 }}>{label}</b>
          <div className="muted" style={{ fontSize: 12 }}>{why}</div>
        </div>
      ))}
    </div>
  )
}

function UnreadableFiles({ files, labelOf, onPickFile }) {
  const stuck = files.filter((f) => dispositionOf(f, labelOf) === 'unreadable').slice(0, 12)
  if (!stuck.length) return <p className="muted" style={{ fontSize: 13 }}>Every discovered file was readable.</p>
  return (
    <div className="findings">
      {stuck.map((f) => (
        <button className="filelistrow" key={f.file} onClick={() => onPickFile(f)}>
          <span className="fname" style={{ fontSize: 13, flex: 1, minWidth: 0 }}>{f.file}</span>
          <span className="muted" style={{ fontSize: 12 }}>{orAbsent(f.openIssue, 'could not open')}</span>
        </button>
      ))}
    </div>
  )
}
