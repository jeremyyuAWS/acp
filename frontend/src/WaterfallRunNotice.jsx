import { MOTION_FRESH_MS } from './waterfallMotion.js'
const positive = value => Number.isSafeInteger(value) && value > 0
const old = (value, now) => {
  const stamp = Date.parse(value || '')
  return !Number.isFinite(stamp) || now - stamp >= MOTION_FRESH_MS || stamp - now > 5_000
}
// Labels describe recorded work, never inferred finding outcomes.
export function waterfallRunNotice({ snapshot = {}, view, error = false, paused = false, now = Date.now() } = {}) {
  if (error) return { code: 'unavailable', title: 'Live updates delayed', detail: view ? 'Showing the last recorded activity; motion will resume with fresh updates.' : 'Activity could not be loaded. No AI outcome is inferred.' }
  if (paused) return { code: 'paused', title: 'Animation paused', detail: 'This does not stop remediation. Recorded counts and details remain available.' }
  const runStates = {
    cancelled: ['Run cancelled', 'Recorded results remain available. Unfinished work was not completed.'],
    cancel_requested: ['Stopping safely', 'Cancellation was requested; active work may still be finishing.'],
    paused: ['Remediation is paused', 'The run is paused, not completed. Review its controls before resuming.'],
    stalled: ['Worker progress has stopped', 'Inspect worker activity and retries before starting this work again.'],
    retry_scheduled: ['Retry scheduled', 'A temporary issue delayed this work. Recorded results remain available.'],
    failed: ['Remediation failed', 'Inspect failed documents and remaining work before retrying.'],
  }
  if (runStates[snapshot.state]) return { code: snapshot.state, title: runStates[snapshot.state][0], detail: runStates[snapshot.state][1] }
  if (!snapshot.terminal && old(snapshot.generated_at, now)) return { code: 'stale', title: 'Waiting for a fresh update', detail: 'The last snapshot does not confirm current activity.' }
  if (snapshot.terminal) {
    if (positive(snapshot.documents?.failed) || snapshot.state === 'failed') return { code: 'failed', title: 'Processing finished with failures', detail: 'Inspect failed documents and remaining review items.' }
    return { code: 'complete', title: 'Automatic processing finished', detail: positive(snapshot.review?.items) ? 'Your review is still needed. Open Review to decide which suggestions to apply.' : 'Finished processing does not mean every finding was fixed.' }
  }
  if (view?.available === false) return { code: 'history-unavailable', title: 'AI history unavailable for this run', detail: 'Missing history does not establish whether AI was used.' }
  if (view?.ai_enabled === false) return { code: 'disabled', title: 'AI is off for this run', detail: 'Rule-based corrections can continue; AI stages stay still.' }
  if (view?.spending?.blocked) return { code: 'blocked', title: 'Further AI spending is on hold', detail: 'A charge needs reconciliation; this is not evidence of a failed model response.' }
  if (positive(snapshot.documents?.processing)) return { code: 'processing', title: 'Documents are processing', detail: 'Motion marks confirmed AI or verification activity. Other work can continue between those steps.' }
  if (positive(snapshot.documents?.waiting)) return { code: 'waiting', title: 'Waiting to process documents', detail: 'Documents are queued; model activity has not been inferred.' }
  return { code: 'unknown', title: 'Waiting for activity records', detail: 'A quiet graph does not imply a completed fix.' }
}
export function waterfallStageStatus(stage, { aiEnabled, terminal = false, unavailable = false } = {}) {
  if (aiEnabled === false) return 'AI disabled for this run'
  if (unavailable || !stage) return 'Activity history unavailable'
  if (positive(stage.uncertain) || positive(stage.breached)) return 'Charge needs reconciliation'
  if (positive(stage.active)) return terminal ? 'Unsettled charge remains' : 'Request dispatched · charge pending'
  if (positive(stage.reserved)) return terminal ? 'Unused reservation remains' : 'Reserved · waiting for dispatch'
  if (positive(stage.settled)) return 'Charge recorded · inspect saved output'
  if (positive(stage.released)) return 'Reservation released without charge'
  if (stage.operations === 0) return terminal ? 'Not used in this run' : 'Not used yet · only if needed'
  return 'Recorded activity · inspect history'
}
export default function WaterfallRunNotice(props) {
  const notice = waterfallRunNotice(props)
  return <div className="wf-note" role="status" data-waterfall-state={notice.code}><strong>{notice.title}</strong><span> · {notice.detail}</span></div>
}
