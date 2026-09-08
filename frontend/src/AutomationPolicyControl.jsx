import { useEffect, useId, useMemo, useState } from 'react'
import { AUTOMATION_LEVELS, DEFAULT_AUTOMATION_LEVEL, automationForecast, automationLevel,
  reviewCardImpact } from './automationPolicy.js'
import WhyFindingsStayWithPeople from './WhyFindingsStayWithPeople.jsx'
import { reviewTimeImpact } from './reviewerTime.js'
import './automation-policy.css'
import AutomationPolicyActions from './AutomationPolicyActions.jsx'

const storageKey = (runId) => `acp.remediation.automation-preview.${runId || 'current'}`
const impact = (findings, files) => `${findings} ${findings === 1 ? 'finding' : 'findings'} across ${files} ${files === 1 ? 'file' : 'files'}`
const signed = (number) => number > 0 ? `+${number}` : number < 0 ? `−${Math.abs(number)}` : '0'
const CATEGORY_COPY = {
  threshold: ['Review at this setting', 'Eligible work below the selected automation threshold'],
  authoring: ['Needs authoring', 'No supported fix proposal is available yet'],
  judgement: ['Human judgement', 'Subjective or human-only decisions stay protected'],
  rejected: ['Previously rejected', 'A reviewer already rejected the proposed fix'],
}

export default function AutomationPolicyControl({ findings, runId = null, previewStatus = 'ready',
  policyPreview = null, reviewAnalytics = null }) {
  const sliderId = useId()
  const [level, setLevel] = useState(() => {
    try {
      const saved = Number(sessionStorage.getItem(storageKey(runId)))
      return saved >= 1 && saved <= 5 ? saved : DEFAULT_AUTOMATION_LEVEL
    } catch { return DEFAULT_AUTOMATION_LEVEL }
  })
  useEffect(() => {
    try { sessionStorage.setItem(storageKey(runId), String(level)) } catch { /* private storage unavailable */ }
  }, [level, runId])

  const selected = automationLevel(level)
  const production = automationLevel(DEFAULT_AUTOMATION_LEVEL)
  const hasData = Array.isArray(findings)
  const forecast = useMemo(() => automationForecast(hasData ? findings : [], level), [findings, hasData, level])
  const baseline = useMemo(() => automationForecast(hasData ? findings : [], DEFAULT_AUTOMATION_LEVEL), [findings, hasData])
  const human = forecast.review + forecast.protected
  const candidateDelta = forecast.candidates - baseline.candidates
  const humanDelta = human - (baseline.review + baseline.protected)
  const consistent = forecast.candidates + forecast.review + forecast.protected === forecast.total
  const cardImpact = useMemo(() => reviewCardImpact(hasData ? findings : [], level), [findings, hasData, level])
  const timeImpact = useMemo(() => reviewTimeImpact(cardImpact.delta, reviewAnalytics),
    [cardImpact.delta, reviewAnalytics])
  const announcement = `Preview ${selected.name}. ${cardImpact.preview} review ${cardImpact.preview === 1 ? 'card' : 'cards'}, ${signed(cardImpact.delta)} from the current ${cardImpact.current}.`
  const state = previewStatus === 'pending' ? 'pending'
    : previewStatus === 'inconsistent' ? 'inconsistent'
    : previewStatus === 'error' || !hasData ? 'unknown'
    : !consistent ? 'inconsistent' : 'ready'

  return (
    <section className="automation-policy" aria-labelledby="automation-policy-title" data-preview-state={state}>
      <div className="automation-policy__heading">
        <div>
          <div className="automation-policy__eyebrow">Automation policy <span>Preview only</span></div>
          <h2 id="automation-policy-title">Choose how much ACP can automate</h2>
          <p>Preview how this run’s eligible findings would route. Eligibility is unchanged.</p>
        </div>
        <div className="automation-policy__policies">
          <div><span>Current production policy</span><strong>{production.name}</strong></div>
          <span className="automation-policy__policy-arrow" aria-hidden="true">→</span>
          <div className="is-preview"><span>Preview policy</span><strong>{selected.name}</strong></div>
        </div>
      </div>

      <div className="automation-policy__slider">
        <label className="sr-only" htmlFor={sliderId}>Preview automation policy</label>
        <input id={sliderId} type="range" min="1" max="5" step="1" value={level}
          onChange={(event) => setLevel(Number(event.target.value))}
          aria-valuetext={`${selected.name}: ${selected.description}`} />
        <div className="automation-policy__ticks">
          {AUTOMATION_LEVELS.map((option) =>
            <button key={option.value} type="button" className={option.value === level ? 'is-selected' : ''}
              style={{ left: `${(option.value - 1) * 25}%` }} onClick={() => setLevel(option.value)}
              aria-label={`Preview ${option.name}: ${option.description}`}
              aria-current={option.value === level ? 'step' : undefined}>
              <span aria-hidden="true" />{option.name}
            </button>)}
        </div>
        <p className="automation-policy__description">{selected.description}</p>
      </div>

      {state === 'pending' ? (
        <p className="automation-policy__empty" role="status">Calculating routing impact from the current run…</p>
      ) : state === 'unknown' ? (
        <p className="automation-policy__empty" role="status">Routing impact is unavailable. No counts are shown because the current run’s preview data was not returned.</p>
      ) : state === 'inconsistent' ? (
        <p className="automation-policy__empty is-error" role="alert">Routing impact could not be reconciled. Refresh the run before using this preview.</p>
      ) : forecast.total > 0 ? (
        <div className="automation-policy__results">
          <p className="automation-policy__sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
          <p className="automation-policy__outcome">
            {forecast.candidates === 0
              ? <><strong>{selected.name} would automate none of the {forecast.total} open findings.</strong> All {human} stay with people.</>
              : <>At <strong>{selected.name}</strong>, ACP would handle <strong>{forecast.candidates} of {forecast.total} findings automatically</strong>. The remaining <strong>{human}</strong> stay with people.</>}
          </p>
          <div className="automation-policy__card-impact">
            <span><b>{cardImpact.current}</b> current review {cardImpact.current === 1 ? 'card' : 'cards'}</span>
            <span aria-hidden="true">→</span>
            <span><b>{cardImpact.preview}</b> in this preview</span>
            <span className={`automation-policy__delta ${cardImpact.delta <= 0 ? 'is-positive' : 'is-negative'}`}>
              {signed(cardImpact.delta)} {Math.abs(cardImpact.delta) === 1 ? 'card' : 'cards'}
            </span>
          </div>
          <p className="automation-policy__units">Review cards are decisions a person opens. Findings are accessibility issues; one card can cover several findings in a file.</p>
          {timeImpact && cardImpact.delta !== 0 && <p className="automation-policy__time-impact" title={timeImpact.basis}>
            Estimated human-review time {timeImpact.direction < 0 ? 'decreases' : 'increases'} by <b>{timeImpact.delta}</b>.
            {' '}<span>Basis: measured median {timeImpact.median} across {timeImpact.reviewed} timed reviews.</span>
          </p>}
          <div className="automation-policy__flow" role="group" aria-label={`Routing impact: ${forecast.total} open findings; ${forecast.candidates} automated; ${forecast.review} sent to review; ${forecast.protected} always requires a person`}>
            <div className="automation-policy__source"><span>Open findings</span><b>{forecast.total}</b></div>
            <span className="automation-policy__flow-arrow" aria-hidden="true">→</span>
            <div className="automation-policy__routes">
              <div className="is-automatic"><span>ACP automates</span><b className="automation-policy__route-impact">{impact(forecast.candidates, forecast.candidateFiles)}</b>
                {level !== DEFAULT_AUTOMATION_LEVEL && candidateDelta !== 0 && <em key={`auto-${level}`} className="automation-policy__delta">{signed(candidateDelta)} vs production</em>}</div>
              <div className="is-review"><span>Routes to review</span><b className="automation-policy__route-impact">{impact(forecast.review, forecast.reviewFiles)}</b>
                {level !== DEFAULT_AUTOMATION_LEVEL && humanDelta !== 0 && <em key={`human-${level}`} className="automation-policy__delta">{signed(humanDelta)} total human decisions</em>}</div>
              <div className="is-protected"><span>Always requires a person</span><b className="automation-policy__route-impact">{impact(forecast.protected, forecast.protectedFiles)}</b></div>
            </div>
          </div>
          {!policyPreview && forecast.humanCategories.length > 0 && (
            <details className="automation-policy__breakdown">
              <summary>Why {human} findings stay with people</summary>
              <div className="automation-policy__categories">
                {forecast.humanCategories.map((category) => {
                  const [label, description] = CATEGORY_COPY[category.key]
                  return <div className="automation-policy__category" key={category.key}>
                    <div><strong>{label}</strong><span>{description}</span></div>
                    <b>{impact(category.findings, category.files)}</b>
                    <details><summary>View affected criteria and files</summary>
                      <p>{category.criteria.map(({ criterion, count }) => `${criterion} (${count})`).join(' · ')}</p>
                      <p>{category.fileNames.slice(0, 8).join(' · ')}{category.fileNames.length > 8 ? ` · +${category.fileNames.length - 8} more` : ''}</p>
                    </details>
                  </div>
                })}
              </div>
            </details>
          )}
          {policyPreview && <WhyFindingsStayWithPeople preview={policyPreview} />}
        </div>
      ) : (
        <p className="automation-policy__empty" role="status">There are no open eligible findings in this run, so no policy has anything to automate or route.</p>
      )}
      <p className="automation-policy__guardrail">Human-only, subjective, unsupported, missing-evidence and failed-verification work always stays in review. This preview does not change the active run or production policy.</p>
      <AutomationPolicyActions runId={runId} previewLevel={level} onReset={setLevel} />
    </section>
  )
}
