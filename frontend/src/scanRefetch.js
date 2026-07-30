import { useEffect } from 'react'
import { getScan } from './api.js'

// Re-read the scan when something announces that the server's file_records changed under us.
// Two announcements, one refetch:
//
//   acp:file-remediated — a FileDrawer's remediate-now (#86). One refetch updates `files` for
//     EVERY tab, so the triage worklist, write-back banner, Publish queue and Discover counts
//     all reflect a manual remediation immediately instead of waiting for a reload.
//   acp:scan-assessed   — a DEFERRED assessment finalized (ADR 0020). With
//     ACP_DEFER_ANALYSIS_TO_ASSESS=1 Discover writes only scan_inventory, so until the worker
//     finishes, get_scan serves the inventory fallback (status 'discovered', score null,
//     issues []) and the file inventory reads "not assessed" for every row. That is honest
//     before Assess and merely stale after it — the findings exist and the drawer shows them,
//     and the rows kept claiming nothing was measured because nobody re-read the scan.
//
// A hook rather than an inline effect so this wiring can be tested against the real inventory:
// App.jsx is not mountable in this suite (sign-in gate, ~40 pieces of state), and a listener
// re-implemented inside a test proves only that the copy works.
export function useScanRefetch(currentScanId, setScan) {
  useEffect(() => {
    const onScanChanged = (e) => {
      // Prefer the announced scan id, so the refetch targets the scan that actually changed
      // rather than whichever one this tab happens to be holding.
      const sid = e?.detail?.scanId || currentScanId
      if (sid) getScan(sid).then(setScan).catch(() => {})
    }
    window.addEventListener('acp:file-remediated', onScanChanged)
    window.addEventListener('acp:scan-assessed', onScanChanged)
    return () => {
      window.removeEventListener('acp:file-remediated', onScanChanged)
      window.removeEventListener('acp:scan-assessed', onScanChanged)
    }
  }, [currentScanId, setScan])
}
