import { activityBuckets } from './remediationLivePanel.js'
// The pulse's own styles travel with it. It used to live inside RemediationOpsPanel.jsx, which
// imports this stylesheet — so the card below would have rendered an unstyled strip the moment
// anything made that panel lazy, silently and only on the tabs where the panel is not mounted.
// A component that carries its own CSS cannot acquire that dependency by accident.
import './remediation-live-detail.css'

// TWELVE FIVE-SECOND BUCKETS OF DURABLE EVENTS — the last sixty seconds of what the run actually
// recorded, not an animation. Every bar is `scan_events` rows the server sent; an idle minute is
// a flat strip, and that is the honest picture rather than a spinner implying motion.
//
// SHARED BY THE PANEL AND THE PERSISTENT CARD. One implementation on purpose: two copies of a
// liveness indicator drift, and the failure is invisible — a card and a panel disagreeing about
// how busy the same run is looks like a data problem, not a duplication problem.
//
// `compact` is the card's variant: no strip padding or divider rule, because the card supplies
// its own. It changes presentation only; both variants read the same buckets from the same
// events, so they cannot disagree about the run.
export default function ActivityPulse({ events, generatedAt, compact = false }) {
  const buckets = activityBuckets(events, generatedAt)
  const max = Math.max(0, ...buckets)
  // NOTHING RECORDED MEANS NOTHING DRAWN. A zero-height strip would be a claim that the last
  // minute was quiet; an absent one makes no claim at all, which is right when the run may
  // simply have started, been resumed from a cursor, or had its events pruned.
  if (!max) return null
  const total = buckets.reduce((sum, value) => sum + value, 0)
  return (
    <div className={`remops-pulse-strip${compact ? ' remops-pulse-compact' : ''}`}
         aria-label={`Last 60 seconds: ${total} recorded events`}>
      <span>Last 60 seconds</span>
      {/* The bars are decoration for a value the label already states — a screen reader gets the
          count from aria-label above rather than twelve unlabelled list items. */}
      <span className="remops-pulse-bars" aria-hidden="true">
        {buckets.map((value, index) => (
          <i key={index} style={{ height: `${Math.max(2, value / max * 12)}px` }} />
        ))}
      </span>
    </div>
  )
}
