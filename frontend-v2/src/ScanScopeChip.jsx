import { useState } from 'react'
import { CORE_SCS, SCOPE_SCS, SCOPE_LABEL } from './activeScope.js'
import { scopeChip, scopeSentence } from './scanScope.js'
import { frozenScopeChip, frozenScopeSummary, scanDocTypes, scopeImpact } from './frozenScope.js'

// The per-scan scope chip (R6 / Phase 3b): states WHAT a completed scan actually covered, from
// the run's FROZEN `scan_scope`, plus a "change scope & re-scan" affordance with an impact
// estimate. It reads the run, never the live global setting — the operator can change the global
// scope after a scan, and this must keep describing the scope THIS scan used.
//
// Two frozen scopes are surfaced, because either can silently shrink a result and they answer
// different questions:
//   * WHICH CRITERIA — `run.scan_scope`, formatted by frozenScope.js.
//   * WHICH FILES     — `run.scope`, the source/folder boundary, formatted by scanScope.js.

// Map `run.source` to the token requestScan/onScan expects (drive | sharepoint | local). The
// re-scan opens the app-level review modal, so an off-by-a-synonym token is corrected there; the
// map only makes the modal open on the right default.
const SOURCE_ARG = {
  drive: 'drive', googledrive: 'drive', gdrive: 'drive',
  sharepoint: 'sharepoint', onedrive: 'sharepoint', sp: 'sharepoint',
  local: 'local', upload: 'local',
}

export default function ScanScopeChip({ run, fileCount, onScan, busy = false }) {
  const [open, setOpen] = useState(false)
  if (!run) return null

  const scanScope = run.scan_scope ?? null           // frozen criterion→formats map, or null
  const boundary = run.scope || null                 // file/source boundary object
  const chip = frozenScopeChip(scanScope, CORE_SCS)
  const bchip = scopeChip(boundary)
  const types = scanDocTypes(scanScope)
  const impact = scopeImpact(scanScope, SCOPE_SCS, CORE_SCS)

  // The assessable-file population the criteria change applies to — read from the scan's OWN
  // inventory, never invented. null when discovery has not inventoried the estate (e.g. a
  // folder/upload scan), in which case the population line is simply omitted.
  const inv = boundary?.inventory
  const affected = inv && Number.isFinite(inv.assessment_eligible) ? inv.assessment_eligible : null

  const rescan = () => { if (!busy) onScan?.(SOURCE_ARG[run.source] || run.source) }

  return (
    <div className="scanscopechip" role="group" aria-label="What this scan covered"
         style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, margin: '2px 0 10px' }}>
      <span className="muted" style={{ fontSize: 12.5 }}>Scanned:</span>
      <span className={`scopechip${chip.restricted ? ' narrow' : ''}`}
            title={frozenScopeSummary(scanScope, CORE_SCS)}>{chip.text}</span>
      {types && types.length > 0 && (
        <span className="muted" style={{ fontSize: 12 }}>{types.join(', ')}</span>
      )}
      {bchip && (
        <span className={`scopechip${bchip.narrow ? ' narrow' : ''}`}
              title={scopeSentence(boundary, fileCount) || undefined}>{bchip.text}</span>
      )}
      {onScan && (
        <button type="button" className="linklike" aria-expanded={open}
                style={{ fontSize: 12 }}
                onClick={() => setOpen((v) => !v)}>Change scope &amp; re-scan</button>
      )}

      {open && onScan && (
        <div className="scanscope-rescan" role="region" aria-label="Change scope and re-scan"
             style={{ flexBasis: '100%', marginTop: 6, padding: '8px 10px', borderRadius: 8,
                      background: '#F6F4F1', border: '1px solid #e7e1da' }}>
          <p className="muted" style={{ margin: '0 0 6px' }}>{frozenScopeSummary(scanScope, CORE_SCS)}</p>

          {/* IMPACT ESTIMATE — the criteria this scan used vs your CURRENT agreed scope. The
              criteria delta is exact; it is the honest answer to "what would change". */}
          {impact.changed ? (
            <p className="scopewarn" role="status" style={{ margin: '0 0 6px', fontSize: 12.5 }}>
              Re-scanning with your current {SCOPE_LABEL} would assess <b>{impact.nextCount}</b> criteria
              {' '}vs the <b>{impact.prevCount}</b> this scan used
              {impact.added.length > 0 && <> — adding {impact.added.length} ({impact.added.join(', ')})</>}
              {impact.dropped.length > 0 && (
                <>{impact.added.length ? ', and ' : ' — '}dropping {impact.dropped.length} ({impact.dropped.join(', ')})</>
              )}
              {affected != null && <>, across the {affected.toLocaleString()} assessable file{affected === 1 ? '' : 's'} in this scan</>}.
            </p>
          ) : (
            <p className="muted" style={{ margin: '0 0 6px', fontSize: 12.5 }}>
              Your current {SCOPE_LABEL} matches this scan — re-scanning would cover the same{' '}
              <b>{impact.prevCount}</b> criteria.
            </p>
          )}

          <p className="muted" style={{ margin: '0 0 8px', fontSize: 11.5 }}>
            Criteria impact is exact. Exact per-file added/dropped counts need a re-scan — there is
            no dry-run preview endpoint yet. Adjust criteria and file types in <b>Scan scope</b> above,
            then re-scan to apply them.
          </p>

          <button type="button" className="exportbtn alt" disabled={busy} onClick={rescan}>
            {busy ? 'Scanning…' : '↻ Re-scan with current scope'}
          </button>
        </div>
      )}
    </div>
  )
}
