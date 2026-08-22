import { useState } from 'react'
import { SCOPE_SIZE, SCOPE_SCS, OUT_OF_SCOPE_SCS } from './activeScope.js'
import { SCOPE_FORMATS } from './scopePresets.js'
import { WCAG } from './wcagCatalog.js'
import { isNarrowScope } from './scanScope.js'

// Total ACP-tracked criteria — 17. Used for "3 of 17 criteria" phrasing.
const TOTAL_CRITERIA = 17

// WCAG level is derived from SCOPE_SCS like AssessRunner does; for the current
// engagement-14 / core-17 presets this is always AA, but the derivation is here
// so the label tracks the scope rather than being a second claim that can diverge.
const LEVEL_LABEL = 'WCAG 2.1 AA'

// Quick name lookup for the "View criteria" expansion.
const SC_NAME = Object.fromEntries(WCAG.map((r) => [r.sc, r.name]))

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

  const formats = SCOPE_FORMATS.map((f) => f.toUpperCase()).join(', ')
  const source = sourceLabel(run?.scope)
  const narrow = isNarrowScope(run?.scope)
  const selectedScs = [...SCOPE_SCS].sort()
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
          <span style={{ fontSize: 11.5, color: '#854F0B', fontWeight: 500,
                         background: '#FAEEDA', padding: '1px 7px', borderRadius: 4 }}>
            locked while running
          </span>
        )}
      </div>

      {/* Compact one-liner — the three axes at a glance */}
      <div style={{ marginTop: 4, color: 'var(--muted, #54636F)', fontSize: 12.5 }}>
        {LEVEL_LABEL}
        {' · '}
        <b style={{ color: 'var(--ink)' }}>{SCOPE_SIZE}</b>{' of '}
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
        <div style={{ marginTop: 4, color: '#854F0B', fontSize: 12.5 }}>
          ⚠ {docScope}
        </div>
      )}

      {/* Actions row */}
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button"
                onClick={() => setShowCriteria((v) => !v)}
                style={{ fontSize: 12, padding: '3px 10px', borderRadius: 5,
                         border: '1px solid var(--line, #e4e7ef)',
                         background: 'transparent', cursor: 'pointer', color: 'var(--ink)' }}>
          {showCriteria ? 'Hide criteria' : 'View criteria'}
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
        <div style={{ marginTop: 10, borderTop: '1px solid var(--line, #e4e7ef)', paddingTop: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--muted, #54636F)', marginBottom: 4 }}>
            {selectedScs.length} selected criteria
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
          {OUT_OF_SCOPE_SCS.size > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted, #54636F)',
                          paddingTop: 8, borderTop: '1px solid var(--line, #e4e7ef)' }}>
              {OUT_OF_SCOPE_SCS.size} of the {TOTAL_CRITERIA} criteria are outside this scope
              {' '}and were not assessed.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
