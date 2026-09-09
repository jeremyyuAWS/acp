import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { assessMetrics } from './assessMetrics.js'
import { scOf } from './fixSummary.js'
import { getFindingDispositions } from './api.js'
import { authEpoch } from './apiIdentity.js'
import WaterfallCount from './WaterfallCount.jsx'
import AssessIncompleteChecks from './AssessIncompleteChecks.jsx'
import './remediation-assessment-progress.css'

const valid = n => Number.isSafeInteger(n) && n >= 0
const n = value => valid(value) ? value.toLocaleString() : 'Unavailable'
export const FINDING_BUCKETS = [
  ['resolved_verified', 'Fixed and verified'],
  ['awaiting_review', 'Awaiting a decision'],
  ['approved_pending_verification', 'Approved, not yet verified'],
  ['unchanged_no_fix', 'No fix recorded'],
  ['failed', 'Fix unsuccessful'],
  ['excluded', 'Excluded by plan'],
  ['superseded', 'Replaced by reassessment'],
]
export function findingMath(snapshot) {
  const rec = snapshot.finding_reconciliation || {}
  const exact = rec.exact === true && !rec.violations?.length
    && !snapshot.integrity?.affected?.includes('finding_reconciliation')
    && valid(rec.assessed) && FINDING_BUCKETS.every(([key]) => valid(rec[key]))
    && FINDING_BUCKETS.reduce((sum, [key]) => sum + rec[key], 0) === rec.assessed
  return { exact, total: valid(rec.assessed) ? rec.assessed : null,
    fixed: exact ? rec.resolved_verified : null,
    remaining: exact ? rec.assessed - rec.resolved_verified : null, rec }
}
export function originalFindingMetrics(groups, total) {
  if (!Array.isArray(groups) || !valid(total)) return null
  const normalized = new Map()
  let automatic = 0, sum = 0
  for (const row of groups) {
    if (!row.file || !scOf(row.rule_id) || !valid(row.finding_count) || !['auto', 'assisted', 'human'].includes(row.fix_mode)) return null
    const key = JSON.stringify([row.file, scOf(row.rule_id)])
    if (normalized.has(key)) return null
    normalized.set(key, { count: row.finding_count, automatic: row.fix_mode === 'auto' })
    sum += row.finding_count
    if (row.fix_mode === 'auto') automatic += row.finding_count
  }
  return sum === total ? { groups: normalized, autoFixAvailable: automatic, humanReviewRequired: total - automatic } : null
}

// Only original finding identities can drain an eligibility bucket. A count of change
// records (including AI changes) is never subtracted from automatic finding eligibility.
export function automaticResolved(metrics, items, expected) {
  if (!Array.isArray(items) || items.length !== expected) return null
  const groups = new Map()
  if (metrics.groups) for (const [key, group] of metrics.groups) groups.set(key, { ...group })
  for (const row of (metrics.rows || []).filter(row => row.opened)) for (const f of row.findings) {
    const key = JSON.stringify([row.file, f.sc])
    const group = groups.get(key) || { count: 0, automatic: f.auto }
    group.count++; groups.set(key, group)
  }
  const seen = new Set()
  let automatic = 0
  for (const item of items) {
    if (!item.finding_id || seen.has(item.finding_id) || !item.verified_at) return null
    seen.add(item.finding_id)
    const group = groups.get(JSON.stringify([item.file, scOf(item.rule_id)]))
    if (!group || group.count <= 0) return null
    group.count--
    if (group.automatic) automatic++
  }
  return automatic
}


function RemainingCount({ value, identity, paused }) {
  const previous = useRef(null)
  const [delta, setDelta] = useState(null)
  useEffect(() => {
    const before = previous.current
    setDelta(null)
    if (before?.identity !== identity) previous.current = { identity, value: null }
    if (!valid(value)) return undefined
    previous.current = { identity, value }
    if (paused || before?.identity !== identity || !valid(before.value) || value >= before.value) return undefined
    setDelta({ value: before.value - value, identity })
    const timer = setTimeout(() => setDelta(null), 2600)
    return () => clearTimeout(timer)
  }, [value, identity, paused])
  return <span className="wf-count"><span>{n(value)}</span>{!paused && delta?.identity === identity && <span className="wf-delta" aria-hidden="true">−{n(delta.value)}</span>}</span>
}

export default function RemediationAssessmentProgress({ snapshot, assessmentContext, identity, paused = false }) {
  const math = findingMath(snapshot)
  const { rec, exact, total, fixed, remaining } = math
  const latest = useMemo(() => assessmentContext ? assessMetrics(assessmentContext.files, assessmentContext) : null, [assessmentContext])
  const original = useMemo(() => originalFindingMetrics(rec.original_assessment, total), [rec.original_assessment, total])
  // Current file data can explain selected checks, but never defines original eligibility.
  const m = latest && latest.totalFindings === total && (!assessmentContext.scanId || assessmentContext.scanId === (snapshot.scan_id || snapshot.run_id)) ? latest : null
  const [linked, setLinked] = useState(null)
  const epoch = authEpoch()
  const revision = snapshot.revision ?? snapshot.generated_at ?? null
  useEffect(() => {
    let active = true
    setLinked(null)
    if (!exact || !original || fixed === 0) return undefined
    getFindingDispositions(snapshot.scan_id || snapshot.run_id, 'resolved_verified').then(result => {
      if (!active || authEpoch() !== epoch || !result.available || result.batch_id !== snapshot.batch_id) return
      const count = automaticResolved(original, result.items, fixed)
      if (count !== null) setLinked({ identity, fixed, revision, count })
    }).catch(() => {})
    return () => { active = false }
  }, [identity, fixed, exact, original, epoch, snapshot.scan_id, snapshot.run_id, snapshot.batch_id, revision])
  const resolvedAuto = exact && original && fixed === 0 ? 0 : linked?.identity === identity && linked.fixed === fixed && linked.revision === revision ? linked.count : null
  const autoRemaining = original && valid(resolvedAuto) ? original.autoFixAvailable - resolvedAuto : null
  const [checksOpen, setChecksOpen] = useState(false)
  const checkId = useId()
  const trigger = useRef(null)
  useEffect(() => setChecksOpen(false), [identity])
  const count = value => <WaterfallCount value={value} identity={identity} paused={paused} />
  const tile = (label, value, detail, green = false) => <div className={`rap-tile${green ? ' rap-green' : ''}`}><dt>{label}</dt><dd>{label === 'Automatic fixes remaining' ? <RemainingCount value={value} identity={identity} paused={paused} /> : count(value)}<p>{detail}</p></dd></div>
  return <section className="rap" aria-label="Assessment findings and remediation progress">
    <h4>Assessment findings · remediation progress</h4>
    <p>The starting assessment stays unchanged. Only verified finding resolutions reduce what remains.</p>
    <dl className="rap-grid">
      {tile('Starting findings', total, 'The assessed findings for this run.')}
      {tile('Fixed and verified', fixed, 'Original findings with recorded verification evidence.', true)}
      {tile('Not yet verified fixed', remaining, 'Includes review, unfinished work, exclusions, and replaced findings.')}
    </dl>
    {exact ? <p className="rap-equation">{n(fixed)} fixed + {n(remaining)} not yet verified fixed = {n(total)} starting findings</p>
      : <p className="rap-equation">{n(total)} starting findings · outcome breakdown unavailable. Change records cannot be subtracted from findings.</p>}
    {!original && <p>The original automatic-eligibility breakdown is unavailable for this recorded assessment.</p>}
    {original && <>
      <dl className="rap-grid">
        {tile('Automatic fixes remaining', autoRemaining, `${n(original.autoFixAvailable)} originally eligible · ${n(resolvedAuto)} verified resolved. Eligibility does not guarantee a successful fix.`, true)}
        {tile('Other findings remaining', valid(autoRemaining) && exact ? remaining - autoRemaining : null, `${n(original.humanReviewRequired)} originally needed review or another approach.`)}
        {m && <div className="rap-tile"><dt>Checks not completed</dt><dd><button type="button" ref={trigger} aria-expanded={checksOpen} aria-controls={checkId} onClick={() => setChecksOpen(open => !open)}>{n(m.unableToAssess)} <small>checks · View checks →</small></button><p>Unknown check results. These are separate from findings.</p></dd></div>}
      </dl>
      <p className="rap-equation">Originally: {n(original.autoFixAvailable)} automatic + {n(original.humanReviewRequired)} other = {n(total)} findings.
        {valid(autoRemaining) && exact && <> Remaining: {n(autoRemaining)} automatic + {n(remaining - autoRemaining)} other = {n(remaining)} findings.</>}</p>
      {valid(autoRemaining) && original.autoFixAvailable > 0 && <progress className="rap-drain" aria-label="Automatic findings remaining" value={autoRemaining} max={original.autoFixAvailable} />}
      {m && <p>{n(m.checksEvaluated)} completed checks + {n(m.unableToAssess)} checks not completed = {n(m.selectedChecks)} selected checks across {n(m.documentsAssessed)} assessed documents. Checks are separate from findings.</p>}
      {m && checksOpen && <AssessIncompleteChecks id={checkId} rows={m.rows} assessment={assessmentContext.assessment} onClose={() => { setChecksOpen(false); trigger.current?.focus() }} />}
    </>}
    {exact && <><h4 className="rap-subheading">What makes up the remaining {n(remaining)} findings?</h4><dl className="rap-grid rap-outcomes">{FINDING_BUCKETS.slice(1).map(([key, label]) => <div className="rap-tile" key={key}><dt>{label}</dt><dd>{count(rec[key])}</dd></div>)}</dl>
      <p className="rap-equation">{FINDING_BUCKETS.slice(1).map(([key]) => n(rec[key])).join(' + ')} = {n(remaining)} not yet verified fixed</p></>}
    <dl className="rap-grid rap-separate">
      {tile('Review items · not findings', snapshot.integrity?.affected?.includes('review') ? null : snapshot.review?.items, 'Grouped review tasks; one item can cover several findings. Not added to the finding totals.')}
      {tile('Verified changes · all origins', snapshot.integrity?.affected?.includes('fixes') ? null : snapshot.fixes?.verified, 'Recorded corrections from rules and AI. Not the number of original findings resolved.')}
      {tile('Documents processing', snapshot.integrity?.affected?.includes('documents') ? null : snapshot.documents?.processing, 'Document activity, separate from finding totals.')}
    </dl>
  </section>
}
