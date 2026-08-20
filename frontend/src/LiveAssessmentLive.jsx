import LiveAssessment from './LiveAssessment.jsx'
import { useLiveSnapshot } from './useLiveSnapshot.js'

// Connected running-screen panel: polls /scans/{sid}/live and renders the presentational LiveAssessment.
// This exists so the App.jsx mount is a SINGLE line (<LiveAssessmentLive scanId=… active=…/>) — no state
// threading in the hottest file. Renders nothing until the endpoint returns an available snapshot, so it
// is inert on backends without /scans/{sid}/live and on a scan that isn't running.
export default function LiveAssessmentLive({ scanId, active = true, intervalMs = 2000 }) {
  const snapshot = useLiveSnapshot(scanId, { active, intervalMs })
  return <LiveAssessment snapshot={snapshot} />
}
