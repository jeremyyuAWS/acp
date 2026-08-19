import { SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17 } from './ruleDetails.js'

// The criteria this grid OFFERS. SCOPE_UNIVERSE is every (criterion, format) pair the engine can reach
// a verdict on — the CI-guarded source (scripts/gen_scope_presets.py, asserted in
// tests/test_scope_presets_frontend_sync.py). Filtered to the 17 tracked criteria so an operator is not
// made to read and dismiss AAA rules and viewer behaviours before reaching a decision they can act on.
// Filtered rather than a separate list, deliberately: the pairs still come from the generated universe,
// so this can never offer a checkbox the engine has no verdict for. It only narrows.
export const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
export const FMT_LABEL = { docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', pdf: 'PDF' }
export const scopeTotalPairs = OFFERED.reduce((n, r) => n + r.formats.length, 0)

// The criterion × format checkbox grid, shared by the admin scope editor (ScanScope) and the per-user
// override editor (MyScanScope). PRESENTATIONAL: the parent owns the selection state and passes
// has/toggle/toggleRow. `lockedHas(sc, f)` marks pairs that are already required by a higher authority
// (the owner default, in the per-user case): they render checked AND disabled — a floor the user can add
// onto but never remove, which is exactly the widen-only rule made visible. Admin usage leaves lockedHas
// at its default (nothing locked), so its rendered output is unchanged.
//
// A pair the engine has no verdict for renders as "—", never a disabled checkbox — a disabled box reads
// as a deliberate "off", implying a choice was made where none was possible.
export default function ScopeGrid({
  has, toggle, toggleRow, busy, canEdit,
  lockedHas = () => false,
  caption = 'Scan scope: tick each criterion and format this engagement assesses.',
}) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
        <caption className="sronly">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Criterion</th>
            {SCOPE_FORMATS.map((f) => (
              <th key={f} scope="col" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>{FMT_LABEL[f]}</th>
            ))}
            <th scope="col" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>All</th>
          </tr>
        </thead>
        <tbody>
          {OFFERED.map((row) => (
            <tr key={row.sc}>
              <th scope="row" style={{ textAlign: 'left', fontWeight: 400, padding: '3px 8px', whiteSpace: 'nowrap' }}>
                <b>{row.sc}</b> {row.name} <span className="muted">· {row.level}</span>
              </th>
              {SCOPE_FORMATS.map((f) => {
                const locked = lockedHas(row.sc, f)
                return (
                  <td key={f} style={{ textAlign: 'center', padding: '3px 8px' }}>
                    {row.formats.includes(f) ? (
                      <input type="checkbox" checked={locked || has(row.sc, f)} disabled={busy || !canEdit || locked}
                             onChange={() => toggle(row.sc, f)}
                             title={locked ? 'Required by the organization default' : undefined}
                             aria-label={`${row.sc} ${row.name}, ${FMT_LABEL[f]}${locked ? ' (required by the organization)' : ''}`} />
                    ) : (
                      <>
                        <span aria-hidden="true" className="muted">—</span>
                        <span className="sronly">{`${FMT_LABEL[f]} not applicable to ${row.sc}`}</span>
                      </>
                    )}
                  </td>
                )
              })}
              <td style={{ textAlign: 'center', padding: '3px 8px' }}>
                <button className="ghost small" disabled={busy || !canEdit}
                        onClick={() => toggleRow(row)}
                        aria-label={`Toggle every format for ${row.sc} ${row.name}`}>
                  {row.formats.every((f) => has(row.sc, f) || lockedHas(row.sc, f)) ? 'none' : 'all'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
