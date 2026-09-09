import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Drawer from './Drawer.jsx'
import RemediationRunInsights from './RemediationRunInsights.jsx'
import { getFindingDispositions } from './api.js'
import { authEpoch } from './apiIdentity.js'
import useWaterfallActivity from './useWaterfallActivity.js'
import WaterfallCount from './WaterfallCount.jsx'
import useWaterfallMotion from './useWaterfallMotion.js'
import RemediationThroughput from './RemediationThroughput.jsx'
import './remediation-waterfall-card.css'

const OUTCOMES = [
  ['resolved_verified', 'Fixed and checked', 'resolved_verified', 'Applied changes with qualifying verification evidence.'],
  ['awaiting_review', 'Awaiting your review', 'awaiting_review', 'Findings awaiting a person’s decision. These are not verified fixes.'],
  ['approved_pending_verification', 'Approved, awaiting completion', 'approved_pending_verification', 'Approval recorded; application or verification is still outstanding.'],
  ['unchanged_no_fix', 'No eligible fix', 'unchanged_no_fix', 'Still needs work: no eligible correction was applied.'],
  ['failed', 'Remediation failed', 'remediation_failed', 'Still needs work: remediation did not complete successfully.'],
  ['excluded', 'Excluded by policy', 'excluded_by_policy', 'Excluded from correction under the accepted run policy.'],
  ['superseded', 'Superseded by reassessment', 'superseded_by_reassessment', 'A newer assessment replaced these findings.'],
]
const money = value => Number.isSafeInteger(value) ? new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6,
}).format(value / 1000000) : 'Unavailable'
const count = value => Number.isSafeInteger(value) && value >= 0

function Stage({ title, detail, children, stamp, paused, identity, onClick, selected, active = false, activeLabel = 'Checking corrected documents' }) {
  const previous = useRef(null)
  const [pulse, setPulse] = useState(0)
  useEffect(() => {
    const before = previous.current
    previous.current = { stamp, identity }
    setPulse(0)
    if (paused || before?.identity !== identity || before.stamp == null || stamp == null || before.stamp === stamp) return undefined
    setPulse(value => value + 1)
    const timer = setTimeout(() => setPulse(0), 1600)
    return () => clearTimeout(timer)
  }, [stamp, paused, identity])
  return <li className={`wf-stage${active ? ' wf-stage-active' : ''}`}><button type="button" className={`wf-stage-button${selected ? ' wf-selected' : ''}`} onClick={onClick} aria-pressed={selected}>
    {pulse > 0 && !paused && <span key={pulse} className="wf-stage-flare" aria-hidden="true" />}
    <strong>{title}</strong>{active && <span className="wf-working"><i aria-hidden="true" />{activeLabel}</span>}<span className="wf-secondary">{detail}</span>{children}
  </button><span className="wf-connector" aria-hidden="true">↓</span></li>
}

export default function RemediationWaterfallCard({ snapshot, paused = false, activity = null }) {
  const scanId = snapshot.scan_id || snapshot.run_id
  const batchId = snapshot.batch_id
  const identity = `${authEpoch()}:${scanId}:${batchId}`
  const fetched = useWaterfallActivity(activity ? null : scanId, batchId, paused)
  const state = activity || fetched
  const data = state.view
  const rec = snapshot.finding_reconciliation || {}
  const exact = rec.exact === true && !rec.violations?.length && !snapshot.integrity?.affected?.includes('finding_reconciliation')
    && count(rec.assessed) && OUTCOMES.every(([key]) => count(rec[key]))
    && OUTCOMES.reduce((sum, [key]) => sum + rec[key], 0) === rec.assessed
  const [selection, setSelection] = useState('rules')
  const [motionPaused, setMotionPaused] = useState(false)
  const motion = useWaterfallMotion(snapshot, data, { paused: paused || motionPaused, error: state.error, selected: selection })
  const visualsPaused = paused || motionPaused || motion.hidden
  const [drawer, setDrawer] = useState(null)
  const requestId = useRef(0)
  const close = useCallback(() => { requestId.current += 1; setDrawer(null) }, [])
  useEffect(() => { setSelection('rules'); close() }, [identity, close])
  useEffect(() => () => { requestId.current += 1 }, [])
  const openOutcome = async ([key, label, disposition, detail]) => {
    const id = ++requestId.current
    const epoch = authEpoch()
    setDrawer({ identity, label, detail, loading: true })
    try {
      const result = await getFindingDispositions(scanId, disposition)
      if (id !== requestId.current || epoch !== authEpoch()) return
      if (!result.available || result.batch_id !== batchId) throw new Error('The run changed. Refresh the card to see matching evidence.')
      if (result.items.length !== rec[key]) throw new Error('These findings changed while you opened them. Refresh the card for matching totals.')
      setDrawer({ identity, label, detail, items: result.items, loading: false })
    } catch (error) {
      if (id === requestId.current && epoch === authEpoch()) setDrawer({ identity, label, detail, error: error.message })
    }
  }
  const displayCount = value => <WaterfallCount value={value} identity={`${identity}:${exact ? 'findings' : 'changes'}`} paused={visualsPaused || state.error} />
  const stages = data?.stages || []
  const spending = data?.spending
  const selectedStage = stages.find(stage => stage.tier === (selection === 'first' ? 1 : selection === 'next' ? 2 : null))
  const descriptions = {
    rules: 'Supported rule-based changes follow the approval settings accepted for this run. Verified changes below include all origins; a rule-only finding split is not yet available.',
    first: 'The first configured model handles drafting and, if requested, review work. Counts describe recorded operations and charge states, not usable suggestions or fixed findings.',
    next: 'The next configured model can draft after an unusable response or review a draft when your plan permits. These counts include both purposes. Open saved history below to see which work it performed.',
    approval: 'You approve AI suggestions before they are applied. Optional AI reviews follow your accepted plan. Saved review results are available below; AI suggestions still require your approval.',
    verify: 'Approved changes must be applied and pass the existing verification checks. Document processing and provider responses do not count as fixed findings.',
  }
  return <section className={`wf-card${visualsPaused ? ' wf-paused' : ''}`} aria-label="Live remediation waterfall">
    <header className="wf-header"><div><span className="wf-eyebrow">Results · live remediation</span><h3>Watch the work move forward</h3><p>Rules first. AI where permitted. Your approval, then verification.</p></div><div className="wf-header-status"><span className="wf-tag">AI suggestions require your approval</span><RemediationThroughput mini data={snapshot.throughput} identity={identity} paused={visualsPaused || state.error} /></div></header>
    <div className="wf-motion-status"><span>{motion.documents > 0 ? <><i className="wf-processing-dot" aria-hidden="true" />{motion.documents} documents processing · counts update as results arrive</> : snapshot.terminal ? 'Automatic processing finished · review the recorded results' : 'Motion follows confirmed activity'}</span><button type="button" aria-pressed={motionPaused} disabled={paused} onClick={() => setMotionPaused(value => !value)}>{motionPaused ? 'Resume animation' : 'Pause animation'}</button></div>
    <div className="wf-metrics">
      <div><span>{exact ? 'Fixed and checked · findings' : 'Verified changes · all origins'}</span><strong>{displayCount(exact ? rec.resolved_verified : snapshot.fixes?.verified)}</strong></div>
      <div><span>{exact ? 'Awaiting your review · findings' : 'Review items · not findings'}</span><strong>{displayCount(exact ? rec.awaiting_review : snapshot.review?.items)}</strong></div>
      <div><span>Documents processing</span><strong>{displayCount(snapshot.documents?.processing)}</strong></div>
    </div>
    <section className="wf-outcomes" aria-label="Finding outcomes">
      <div className="wf-section-head"><h4>Where your findings stand</h4><span>{count(rec.assessed) ? `${rec.assessed.toLocaleString()} assessed findings` : 'Finding baseline unavailable'}</span></div>
      {exact ? <><div className="wf-outcome-bar" aria-hidden="true">{OUTCOMES.map(([key], index) => <span key={key} className={`wf-tone-${index}`} style={{ width: `${rec.assessed ? rec[key] / rec.assessed * 100 : 0}%` }} />)}</div>
        <div className="wf-legend">{OUTCOMES.map((row, index) => <button key={row[0]} type="button" onClick={() => openOutcome(row)}><i className={`wf-tone-${index}`} aria-hidden="true" />{row[1]} {displayCount(rec[row[0]])}<span className="sr-only">. View finding details.</span></button>)}</div>
        <details><summary>View outcomes as a table</summary><table><thead><tr><th>Outcome</th><th>Findings</th></tr></thead><tbody>{OUTCOMES.map(row => <tr key={row[0]}><th><button type="button" className="linklike" onClick={() => openOutcome(row)}>{row[1]}</button></th><td>{rec[row[0]].toLocaleString()}</td></tr>)}</tbody></table></details>
      </> : <p className="wf-note">Finding outcomes are not fully reconciled yet. Verified changes and review items above use separate units; a complete finding bar is unavailable.</p>}
    </section>
    <div className="wf-layout"><div><h4>Live AI waterfall</h4><ol className="wf-stages">
      <Stage title="01 · Rules" detail="Supported corrections under your plan" identity={identity} stamp="rules" paused={visualsPaused} selected={selection === 'rules'} onClick={() => setSelection('rules')}><span>No LLM call required</span></Stage>
      {[1, 2].map(tier => {
        const stage = stages.find(item => item.tier === tier)
        const selected = tier === 1 ? 'first' : 'next'
        const models = stage?.models || []
        const modelTitle = models.length ? [...new Set(models.map(item => item.model))].join(' + ') : stage?.operations === 0 ? 'Not used yet' : 'Model not recorded'
        const role = tier === 1 ? 'First attempt' : 'Fallback'
        const modelDetail = models.length ? `${role} · ${[...new Set(models.map(item => item.provider))].join(', ')}` : `${role} · ${data?.ai_enabled === false ? 'AI disabled for this run' : 'Recorded model identity unavailable'}`
        return <Stage key={tier} title={`${tier + 1 < 10 ? '0' : ''}${tier + 1} · ${modelTitle}`} detail={modelDetail} activeLabel="Request dispatched · awaiting response or charge" identity={identity} stamp={JSON.stringify(stage)} paused={visualsPaused || state.error} active={motion.stage === selected} selected={selection === selected} onClick={() => setSelection(selected)}>
          {stage ? <><span className="wf-stage-total">{displayCount(stage.operations)} recorded operations</span><span className="wf-secondary">{displayCount(stage.active)} dispatched · {displayCount(stage.settled)} settled · {displayCount(stage.uncertain)} uncertain</span><span className="wf-secondary">{money(stage.spent_units)} settled · {money(stage.held_units)} reserved</span></> : <span className="wf-secondary">No measured count available</span>}
        </Stage>
      })}
      <Stage title="04 · Your approval" detail="AI suggestions stay in human review" identity={identity} stamp={rec.awaiting_review} paused={visualsPaused} selected={selection === 'approval'} onClick={() => setSelection('approval')}><span>Review before application</span></Stage>
      <Stage title="05 · Apply and verify" detail="Only checked changes count as fixed" identity={identity} stamp={snapshot.fixes?.verified} paused={visualsPaused} active={motion.stage === 'verify'} selected={selection === 'verify'} onClick={() => setSelection('verify')}><span>{displayCount(snapshot.fixes?.verified)} verified changes · all origins</span></Stage>
    </ol></div><aside className="wf-detail"><h4>{({ rules: 'Rules lead the way', first: 'What the first AI did', next: 'What the next AI did', approval: 'Your decision matters', verify: 'Evidence of completion' })[selection]}</h4><p>{descriptions[selection]}</p>{selectedStage && <><dl key={selectedStage.tier} className="wf-spending">{[['reserved', 'Reserved, not dispatched'], ['active', 'Dispatched, awaiting charge'], ['settled', 'Charge recorded'], ['released', 'Released without charge'], ['uncertain', 'Charge uncertain'], ['breached', 'Charge exceeded reservation']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{displayCount(selectedStage[key])}</dd></div>)}</dl><p className="wf-secondary">These are attempt states. Recorded operations deduplicate admission retries.</p></>}
      <section><h4>What each AI step added</h4><p>{data?.contribution_reason || 'AI step breakdown unavailable for this run. Calls cannot yet be joined to usable suggestions.'}</p><p className="wf-secondary">Optional AI reviews check a suggestion; they do not add another finding. Open saved model history below to see recorded reviews.</p></section>
      <section><h4>Models behind current proposals</h4>{data?.models?.length ? <><ul className="wf-models">{data.models.map(model => <li key={`${model.provider}:${model.model}`}><strong>{model.provider} · {model.model}</strong><span>{model.linked_calls} recorded call{model.linked_calls === 1 ? '' : 's'} linked to current proposals</span><span>Recorded call cost: {typeof model.recorded_cost_usd === 'number' ? money(Math.round(model.recorded_cost_usd * 1000000)) : 'Unavailable'}</span></li>)}</ul><p className="wf-secondary">These models produced the current proposals for this scan. Proposals and their recorded call costs may come from other runs. This is not a model breakdown for the selected run; do not add these costs to its charges below.</p></> : <p>No provider/model identity is linked to current proposals for this view. Historical run attribution is unavailable.</p>}</section>
      <section><h4>Spending for this run</h4><dl className="wf-spending">{[['spent_units', 'Settled provider charges'], ['held_units', 'Reserved · may still be charged'], ['available_units', 'Remaining allowance'], ['cap_units', 'Approved spending limit']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd><WaterfallCount value={spending?.[key]} identity={identity} paused={visualsPaused || state.error} format={money} /></dd></div>)}</dl>{spending?.unknown_charges > 0 && <p className="wf-note">{spending.unknown_charges} charge(s) unknown. Their reservations remain held.</p>}{spending?.blocked && <p className="wf-note">Further AI spending is blocked pending reconciliation.</p>}<p className="wf-secondary">Provider charges only. Infrastructure costs are separate.</p></section>
    </aside></div>
    <RemediationRunInsights scanId={scanId} batchId={batchId} />
    <footer className="wf-footer"><span>{state.error ? data ? 'Refresh delayed · showing the last recorded AI activity' : 'AI activity unavailable · retrying' : visualsPaused ? 'Animation paused · recorded totals remain available' : 'Updates follow recorded activity'}</span><span>{data?.generated_at ? `AI snapshot ${new Date(data.generated_at).toLocaleTimeString()}` : data?.available === false ? 'No managed waterfall records for this run' : 'Waiting for AI activity records'}</span></footer>
    {drawer?.identity === identity && createPortal(<Drawer title={drawer.label} subtitle={drawer.detail} onClose={close}><div className="wf-drawer-content">{drawer.loading && <p role="status">Loading findings…</p>}{drawer.error && <p role="alert">{drawer.error}</p>}{drawer.items && <><p>{drawer.items.length} findings in this outcome.</p>{drawer.items.length === 0 && <p>No findings in this outcome.</p>}<ul>{drawer.items.map(item => <li key={item.finding_id}><strong>{item.file}</strong><span>WCAG {item.rule_id} · {item.instance_key}</span>{item.verified_at && <span>Verified {new Date(item.verified_at).toLocaleString()}</span>}</li>)}</ul></>}</div></Drawer>, document.body)}
  </section>
}
