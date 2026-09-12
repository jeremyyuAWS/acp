import './waterfall-drawer-story.css'
import { recordedRunGraphGroups } from './remediationRunGraphPresentation.js'
import RemediationCategoryPill from './RemediationCategoryPill.jsx'

const known = value => Number.isSafeInteger(value) && value >= 0
const count = value => known(value) ? value.toLocaleString('en-US') : 'Not recorded'
const titles = { primary: 'Primary AI', fallback_1: 'First fallback', fallback_2: 'Second fallback' }

export function RecordedModelJourney({ graph, selectedModel, onSelectStage }) {
  const steps = recordedRunGraphGroups(graph)?.flat() || []
  return <section className="wds-panel" aria-label="Recorded model journey"><h3>Model journey</h3>
    <p className="wds-note">Saved generation positions and recorded reviewers · run scope</p>
    {!steps.length ? <p>Generation positions were not recorded for this run.</p> : <ol className="wds-journey">{steps.map(step => {
      const selected = selectedModel?.id ? selectedModel.id === step.id : !!step.stepId && selectedModel?.stepId === step.stepId
      const contents = <><span className="wds-step-title">{titles[step.stepId] || step.role}</span><span>{step.provider || 'Provider not recorded'} · {step.model || 'Model not recorded'}</span><strong>{step.detail}</strong><span className="wds-step-reason">{step.explanation || 'Transition reason not recorded.'}</span></>
      return <li key={step.id} data-stage={step.stepId || step.stage} data-selected={selected}>
        {onSelectStage ? <button type="button" aria-current={selected ? 'step' : undefined} onClick={() => onSelectStage(step.stage, step)}>{contents}</button> : <div aria-current={selected ? 'step' : undefined}>{contents}</div>}
      </li>
    })}</ol>}
    <p className="wds-note">Positions show configuration and recorded outcomes. Sequence alone does not prove a fallback occurred.</p>
  </section>
}

export function RunBudgetMeter({ spending }) {
  const keys = ['spent_units', 'held_units', 'available_units']
  const usable = spending?.currency === 'USD' && known(spending.cap_units) && keys.every(key => known(spending[key]))
  const sum = usable ? keys.reduce((n, key) => n + spending[key], 0) : 0
  const balanced = usable && sum === spending.cap_units && sum > 0
  const money = value => known(value) && spending?.currency === 'USD' ? new Intl.NumberFormat('en-US', { style:'currency', currency:'USD', maximumFractionDigits:6 }).format(value / 1000000) : 'Not recorded'
  return <section className="wds-panel" aria-label="Run spending"><h3>Run spending</h3><p className="wds-note">All models and documents · saved allowance {money(spending?.cap_units)}</p>
    {balanced && <div className="wds-budget" role="img" aria-label={`Settled ${money(spending.spent_units)}, reserved ${money(spending.held_units)}, remaining ${money(spending.available_units)}`}>{keys.map(key => <span key={key} className={`wds-${key}`} style={{width:`${spending[key] / sum * 100}%`}} />)}</div>}
    <dl className="wds-budget-values">{keys.map((key, i) => <div key={key}><dt><i className={`wds-${key}`} aria-hidden="true" />{['Settled', 'Reserved', 'Remaining'][i]}</dt><dd>{money(spending?.[key])}</dd></div>)}</dl>
    {!usable && <p className="wds-note">Complete budget amounts are unavailable.</p>}
    {usable && !balanced && <p className="wds-note">{sum > spending.cap_units ? 'Recorded commitments exceed the saved allowance.' : 'No proportional budget chart is available for these amounts.'}</p>}
    {known(spending?.unknown_charges) && spending.unknown_charges > 0 && <p className="wds-attention">{spending.unknown_charges} uncertain charge(s) need reconciliation.</p>}
    <p className="wds-note">Reservations are commitments, not settled charges.</p>
  </section>
}

export function RunEvidenceSummary({ snapshot = {}, selectTab }) {
  const fixes = snapshot.fixes || {}
  const review = snapshot.review || {}
  return <section className="wds-panel" aria-label="Run verification evidence"><h3>Results and evidence</h3><p className="wds-note">Whole run · all origins, including rule-based changes</p>
    <dl className="wds-outcomes">
      <div className="wds-verified"><dt><RemediationCategoryPill category="verified" /> changes</dt><dd>{count(fixes.verified)}</dd></div>
      <div className="wds-applied"><dt>↳ Applied changes</dt><dd>{count(fixes.applied)}</dd></div>
      <div className="wds-review"><dt>◇ Review items</dt><dd>{count(review.items)}</dd></div>
    </dl><p className="wds-note">These counts overlap and use different units. Verification covers recorded checks; it does not establish complete document accessibility.</p>
    <button type="button" className="ghost" onClick={() => selectTab?.('Evidence')}>Inspect verification evidence</button>
  </section>
}

export default function WaterfallDrawerStory({ view, selectedModel, snapshot, selectTab, onSelectStage }) {
  return <div className="wds-story"><RecordedModelJourney graph={view?.run_graph} selectedModel={selectedModel} onSelectStage={onSelectStage} /><RunEvidenceSummary snapshot={snapshot} selectTab={selectTab}/><RunBudgetMeter spending={view?.spending}/></div>
}
