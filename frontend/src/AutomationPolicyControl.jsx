import { useEffect, useMemo, useState } from 'react'
import { AUTOMATION_LEVELS, DEFAULT_AUTOMATION_LEVEL, automationForecast, automationLevel } from './automationPolicy.js'
import './automation-policy.css'

const storageKey = (runId) => `acp.remediation.automation-preview.${runId || 'current'}`
const impact = (findings, files) => `${findings} ${findings === 1 ? 'finding' : 'findings'} across ${files} ${files === 1 ? 'file' : 'files'}`
const signed = (number) => number > 0 ? `+${number}` : number < 0 ? `−${Math.abs(number)}` : '0'
const percent = (part, total) => total ? Math.round((part / total) * 100) : 0

const CATEGORY_COPY = {
  threshold: ['Review at this setting', 'Eligible work below the selected automation threshold'],
  authoring: ['Needs authoring', 'No supported fix proposal is available yet'],
  judgement: ['Human judgement', 'Subjective or human-only decisions stay protected'],
  rejected: ['Previously rejected', 'A reviewer already rejected the proposed fix'],
}

export default function AutomationPolicyControl({ findings = [], runId = null }) {
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
  const forecast = useMemo(() => automationForecast(findings, level), [findings, level])
  const baseline = useMemo(() => automationForecast(findings, DEFAULT_AUTOMATION_LEVEL), [findings])
  const human = forecast.review + forecast.protected
  const baselineHuman = baseline.review + baseline.protected
  const candidateDelta = forecast.candidates - baseline.candidates
  const humanDelta = human - baselineHuman

  return (
    <section className="automation-policy" aria-labelledby="automation-policy-title">
      <div className="automation-policy__heading">
        <div>
          <div className="automation-policy__eyebrow">Automation policy <span>Preview only</span></div>
          <h2 id="automation-policy-title">Choose how much ACP can automate</h2>
          <p>See how the current review queue would be routed before changing production policy.</p>
        </div>
        <div className="automation-policy__selection" aria-live="polite">
          <strong>{selected.name}</strong>
          <span>{selected.description}</span>
        </div>
      </div>

      <div className="automation-policy__slider">
        <input
          type="range"
          min="1"
          max="5"
          step="1"
          value={level}
          onChange={(event) => setLevel(Number(event.target.value))}
          aria-label="Automation level"
          aria-valuetext={`${selected.name}: ${selected.description}`}
        />
        <div className="automation-policy__ticks" aria-hidden="true">
          {AUTOMATION_LEVELS.map((option, index) =>
            <span key={option.value} style={{ left: `${index * 25}%` }}>{option.name}</span>)}
        </div>
      </div>

      {forecast.total > 0 ? (
        <div className="automation-policy__results" aria-live="polite">
          <p className="automation-policy__outcome">
            At <strong>{selected.name}</strong>, ACP handles <strong>{forecast.candidates} of {forecast.total} findings automatically</strong>.
            {' '}The remaining <strong>{human}</strong> stay with people.
          </p>

          <div className="automation-policy__allocation" role="img"
            aria-label={`${forecast.candidates} findings automated, ${forecast.review} in review, ${forecast.protected} safety protected`}>
            {forecast.candidates > 0 && <span className="is-automatic" style={{ width: `${percent(forecast.candidates, forecast.total)}%` }} />}
            {forecast.review > 0 && <span className="is-review" style={{ width: `${percent(forecast.review, forecast.total)}%` }} />}
            {forecast.protected > 0 && <span className="is-protected" style={{ width: `${percent(forecast.protected, forecast.total)}%` }} />}
          </div>

          <div className="automation-policy__forecast">
            <div className="is-automatic">
              <span className="automation-policy__label">ACP handles automatically</span>
              <b>{impact(forecast.candidates, forecast.candidateFiles)}</b>
              <span>{percent(forecast.candidates, forecast.total)}% of open findings</span>
              {level !== DEFAULT_AUTOMATION_LEVEL && <span key={`auto-${level}`} className={`automation-policy__delta ${candidateDelta > 0 ? 'is-positive' : 'is-negative'}`}>{signed(candidateDelta)} vs Balanced</span>}
            </div>
            <div className="is-review">
              <span className="automation-policy__label">Your review queue</span>
              <b>{impact(forecast.review, forecast.reviewFiles)}</b>
              <span>{percent(forecast.review, forecast.total)}% needs review at this setting</span>
              {level !== DEFAULT_AUTOMATION_LEVEL && <span key={`human-${level}`} className={`automation-policy__delta ${humanDelta < 0 ? 'is-positive' : 'is-negative'}`}>{signed(humanDelta)} human decisions vs Balanced</span>}
            </div>
            <div className="is-protected">
              <span className="automation-policy__label">Always requires a person</span>
              <b>{impact(forecast.protected, forecast.protectedFiles)}</b>
              <span>{percent(forecast.protected, forecast.total)}% protected by safety rules</span>
            </div>
          </div>

          {forecast.humanCategories.length > 0 && (
            <details className="automation-policy__breakdown">
              <summary>Why {human} findings stay with people</summary>
              <div className="automation-policy__categories">
                {forecast.humanCategories.map((category) => {
                  const [label, description] = CATEGORY_COPY[category.key]
                  return <div className="automation-policy__category" key={category.key}>
                    <div><strong>{label}</strong><span>{description}</span></div>
                    <b>{impact(category.findings, category.files)}</b>
                    <details>
                      <summary>View affected criteria and files</summary>
                      <p>{category.criteria.map(({ criterion, count }) => `${criterion} (${count})`).join(' · ')}</p>
                      <p>{category.fileNames.slice(0, 8).join(' · ')}{category.fileNames.length > 8 ? ` · +${category.fileNames.length - 8} more` : ''}</p>
                    </details>
                  </div>
                })}
              </div>
            </details>
          )}
        </div>
      ) : (
        <p className="automation-policy__empty">No open review findings are available to preview for this run.</p>
      )}

      <p className="automation-policy__guardrail">
        Human-only, subjective, unsupported, missing-evidence and failed-verification work always stays in review.
        This preview does not change the active run or production policy.
      </p>
    </section>
  )
}
