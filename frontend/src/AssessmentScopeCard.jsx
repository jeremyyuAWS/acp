import { useId, useState } from 'react'
import { SCOPE_SIZE, SCOPE_SCS, OUT_OF_SCOPE_SCS } from './activeScope.js'
import { SCOPE_FORMATS } from './scopePresets.js'
import { SC_NAME } from './wcagCatalog.js'
import { DOCUMENTS_20 } from './documents20.js'
import { isNarrowScope } from './scanScope.js'
import { runScopeCriteria, runScopeIsRestricted } from './runScopeCriteria.js'

// Total ACP-tracked criteria — 17. Used for "3 of 17 criteria" phrasing.
const TOTAL_CRITERIA = 17

// WCAG level is derived from SCOPE_SCS like AssessRunner does; for the current
// engagement-14 / core-17 presets this is always AA, but the derivation is here
// so the label tracks the scope rather than being a second claim that can diverge.
const LEVEL_LABEL = 'WCAG 2.1 AA'

// Human-readable source label from run.scope.kind — mirrors the canonical labels used in
// the scan history table and ScopeChip, so different surfaces name the same scan the same way.
function sourceLabel(scope) {
  if (!scope) return null
  if (scope.kind === 'sharepoint') return 'SharePoint / OneDrive'
  if (scope.kind === 'local') return 'sample corpus'
  return 'Google Drive'
}

// Compact, read-only scope record — replaces the full editable ScanSetup on results screens.
//
// state='running': scope is locked while the scan is in progress — no change action.
// state='done':    historical record — shows "Change scope and reassess" when onReassess is passed.
//
// "View criteria" expands an inline list of the selected success criteria, their names and
// formats; it never re-opens the configuration interface.
// docScope: per-document scope sentence from documentScopeSentence() — non-null when the
// operator has marked specific documents in scope, restricting remediation to that subset.
// Displayed as a warning so the user knows their document-level filter is active.
export default function AssessmentScopeCard({ run, fileCount = 0, state = 'done', onReassess, docScope = null }) {
  const [showCriteria, setShowCriteria] = useState(false)
  const criteriaPanelId = useId()

  const formats = SCOPE_FORMATS.map((f) => f.toUpperCase()).join(', ')
  const source = sourceLabel(run?.scope)
  const narrow = isNarrowScope(run?.scope)
  // The criteria THIS run was frozen to, not today's live setting — this card's whole job is
  // "what was in scope for this assessment", so it must go on saying that even after the
  // operator changes the setting for the next one. Only overridden when the run recorded a
  // genuine narrowing: a run known to have NO restriction falls back to the live global scope
  // rather than the wider 20-item document core, because this card's own "of 17" headline is
  // sized to the Core-17 catalog SCOPE_SCS is drawn from, not to DOCUMENTS_20 — mixing the two
  // denominators here would print a criteria count larger than the total next to it.
  const runRestricted = runScopeIsRestricted(run)
  const runCriteria = runRestricted ? runScopeCriteria(run) : SCOPE_SCS
  const selectedScs = [...runCriteria].sort()
  const outOfScope = runRestricted
    ? new Set([...DOCUMENTS_20].filter((sc) => !runCriteria.has(sc)))
    : OUT_OF_SCOPE_SCS
  const docCount = Number.isFinite(fileCount) ? fileCount : 0

  return (
    <div className="scope-card" role="note"
         style={{ fontSize: 13, padding: '10px 14px', borderRadius: 10,
                  border: '1px solid var(--line, #e4e7ef)',
                  background: 'var(--surface)', marginBottom: 8 }}>

      {/* Header row — name + locked indicator */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap',
                    justifyContent: 'space-between' }}>
        <b style={{ fontSize: 13.5 }}>
          {state === 'done' ? 'Scope used for this assessment' : 'Assessment scope'}
        </b>
        {state === 'running' && (
          <span style={{ fontSize: 11.5, color: 'var(--warn-fg)', fontWeight: 500,
                         background: 'var(--warn-bg)', padding: '1px 7px', borderRadius: 4 }}>
            locked while running
          </span>
        )}
      </div>

      {/* Compact one-liner — the three axes at a glance */}
      <div style={{ marginTop: 4, color: 'var(--muted, #54636F)', fontSize: 12.5 }}>
        {LEVEL_LABEL}
        {' · '}
        <b style={{ color: 'var(--ink)' }}>{selectedScs.length}</b>{' of '}
        {TOTAL_CRITERIA} criteria
        {' · '}
        {formats}
      </div>

      {/* Source + document count */}
      {(source || docCount > 0) && (
        <div style={{ marginTop: 2, color: 'var(--muted, #54636F)', fontSize: 12.5 }}>
          {narrow && <span aria-label="narrow scope warning">⚠ </span>}
          {source && <>{source}{' · '}</>}
          {docCount.toLocaleString()} document{docCount === 1 ? '' : 's'} in scope
        </div>
      )}

      {/* Per-document scope warning — only shown when the operator has marked specific docs */}
      {docScope && (
        <div style={{ marginTop: 4, color: 'var(--warn-fg)', fontSize: 12.5 }}>
          ⚠ {docScope}
        </div>
      )}

      {/* Actions row */}
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button"
                aria-expanded={showCriteria}
                aria-controls={criteriaPanelId}
                onClick={() => setShowCriteria((v) => !v)}
                style={{ fontSize: 12, padding: '3px 10px', borderRadius: 5,
                         border: '1px solid var(--line, #e4e7ef)',
                         background: 'transparent', cursor: 'pointer', color: 'var(--ink)' }}>
          {showCriteria ? 'Hide' : 'Selected success criteria'} · {selectedScs.length}
        </button>
        {state === 'done' && onReassess && (
          <button type="button"
                  onClick={onReassess}
                  style={{ fontSize: 12, padding: '3px 10px', borderRadius: 5,
                           border: 'none', background: 'transparent', cursor: 'pointer',
                           color: 'var(--plum, #46303F)', textDecoration: 'underline' }}>
            Change scope and reassess
          </button>
        )}
      </div>

      {/* Expandable: the selected criteria with their names, and any excluded ones */}
      {showCriteria && (
        <div id={criteriaPanelId} role="region" aria-label={`Selected success criteria · ${selectedScs.length}`}
             style={{ marginTop: 10, borderTop: '1px solid var(--line, #e4e7ef)', paddingTop: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--muted, #54636F)', marginBottom: 4 }}>
            Selected success criteria · {selectedScs.length}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px',
                        fontSize: 12.5, lineHeight: 1.5 }}>
            {selectedScs.map((sc) => (
              <div key={sc} style={{ display: 'contents' }}>
                <b style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--ink)' }}>{sc}</b>
                <span style={{ color: 'var(--muted, #54636F)' }}>{SC_NAME[sc] || sc}</span>
              </div>
            ))}
          </div>
          {outOfScope.size > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted, #54636F)',
                          paddingTop: 8, borderTop: '1px solid var(--line, #e4e7ef)' }}>
              {outOfScope.size} of the {TOTAL_CRITERIA} criteria are outside this scope
              {' '}and were not assessed.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
