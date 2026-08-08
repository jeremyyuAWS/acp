import ScanSetup from './ScanSetup.jsx'

// The screen before anything has been scanned — and, until now, the one place the product
// explained itself instead of asking anything.
//
// It held three boxes describing Discover, Assess and Remediate. The nav already names those
// three stages, so the boxes restated the tabs directly above them while the decision that
// actually shapes every one of those stages — what to assess — was made two screens away, at
// the top of Discover.
//
// That is backwards for the first thing an operator sees. "Configure once, the pipeline
// inherits it" is already true architecturally: `scan_scope` is gated once inside
// `_rule_outcome`, so assess, remediate and publish all inherit it. It just was not true of the
// first screen, which asked for nothing and then scanned everything.
export default function EmptyState({ onScan, busy, hasDriveToken, hasSPToken = false, onFileTypeChange }) {
  return (
    <div className="empty">
      <ScanSetup onScan={onScan} busy={busy}
                 hasDriveToken={hasDriveToken} hasSPToken={hasSPToken}
                 onFileTypeChange={onFileTypeChange} />
    </div>
  )
}

export function Loading() {
  return <div className="loadingbox"><span className="spinner" />Loading your workspace…</div>
}
