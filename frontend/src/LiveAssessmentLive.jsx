import LiveAssessment from './LiveAssessment.jsx'
import { useLiveSnapshot } from './useLiveSnapshot.js'
import { useThroughput } from './useThroughput.js'

// Connected running-screen panel: polls /scans/{sid}/live and renders the presentational LiveAssessment.
// This exists so the App.jsx mount is a SINGLE line (<LiveAssessmentLive scanId=… active=…/>) — no state
// threading in the hottest file. Renders nothing until the endpoint returns an available snapshot, so it
// is inert on backends without /scans/{sid}/live and on a scan that isn't running.
export default function LiveAssessmentLive({ scanId, active = true, intervalMs = 2000 }) {
  const snapshot = useLiveSnapshot(scanId, { active, intervalMs })
  // Rolling throughput + calibrated ETA range, accumulated across polls from completed-vs-eligible.
  const done = snapshot && snapshot.kpis ? snapshot.kpis.completed : undefined
  const total = snapshot && snapshot.totals ? snapshot.totals.eligible : undefined
  const remaining = (typeof total === 'number' && typeof done === 'number') ? Math.max(0, total - done) : undefined
  const throughput = useThroughput(snapshot ? snapshot.run_id : undefined, done, remaining)
  return <LiveAssessment snapshot={snapshot} throughput={throughput} />
}
