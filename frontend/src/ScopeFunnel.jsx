import { statusRows } from './estateFunnel.js'

// Answers the question every operator asks mid-scan: "why did 250 selected files become fewer assessed?"
// A compact eligibility breakdown, shown live in the progress panel and kept in the completed summary.
//
// It REUSES the three-denominator inventory (statusRows over inventory.by_status), so these numbers are
// the SAME ones EstateCoverage shows on Discover/Overview — never a second count that could disagree.
// `blocked` (password-protected / couldn't-open) is surfaced separately when the scan reported one,
// since those files are discovered-and-eligible but could not actually be opened.
//
// Assessable reads green (what ACP can act on); the rest are muted (excluded from assessment, honestly
// shown rather than hidden — the user's point that fewer-assessed must be explained, not glossed over).
const KIND_COLOR = { assessable: '#2F7D51' }

export default function ScopeFunnel({ inventory, blocked = 0 }) {
  const discovered = (inventory && inventory.discovered) || 0
  const rows = statusRows(inventory)
  if (!discovered || rows.length === 0) return null
  return (
    <div className="scopefunnel" role="group" aria-label="Scope eligibility"
         style={{ marginTop: 8, fontSize: 12.5, color: '#54636F', display: 'flex', flexWrap: 'wrap', gap: '2px 4px', alignItems: 'baseline' }}>
      <span><b>{discovered.toLocaleString()}</b> discovered</span>
      {rows.map((r) => (
        <span key={r.status} style={{ marginLeft: 8 }}>
          · <b style={{ color: KIND_COLOR[r.status] || 'inherit' }}>{r.count.toLocaleString()}</b> {r.label.toLowerCase()}
        </span>
      ))}
      {blocked > 0 && (
        <span style={{ marginLeft: 8 }}>· <b>{blocked.toLocaleString()}</b> couldn’t open</span>
      )}
    </div>
  )
}
