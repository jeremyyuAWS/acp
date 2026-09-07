import { useEffect, useMemo, useRef, useState } from 'react'
import { AUTOMATION_LEVELS, DEFAULT_AUTOMATION_LEVEL, automationForecast, automationLevel } from './automationPolicy.js'
import './automation-policy.css'

const storageKey = (runId) => `acp.remediation.automation-preview.${runId || 'current'}`
const impact = (findings, files) => `${findings} ${findings === 1 ? 'finding' : 'findings'} across ${files} ${files === 1 ? 'file' : 'files'}`

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
  const previousCandidates = useRef(forecast.candidates)
  const [candidateDelta, setCandidateDelta] = useState(null)

  useEffect(() => {
    const delta = forecast.candidates - previousCandidates.current
    previousCandidates.current = forecast.candidates
    setCandidateDelta(delta === 0 ? null : delta)
  }, [forecast.candidates])

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
        <div className="automation-policy__forecast" aria-live="polite">
          <div>
            <b>{impact(forecast.candidates, forecast.candidateFiles)}
              {candidateDelta != null && (
                <span key={`${level}-${candidateDelta}`} className={`automation-policy__delta ${candidateDelta > 0 ? 'is-positive' : 'is-negative'}`}
                  role="status" aria-live="polite" aria-label={`${candidateDelta > 0 ? 'Added' : 'Removed'} ${Math.abs(candidateDelta)} automatic ${Math.abs(candidateDelta) === 1 ? 'fix' : 'fixes'}`}>
                  {candidateDelta > 0 ? '+' : '−'}{Math.abs(candidateDelta)}
                </span>
              )}
            </b>
            <span>automatic fixes at this setting</span>
          </div>
          <div><b>{impact(forecast.review, forecast.reviewFiles)}</b><span>kept for review by this setting</span></div>
          <div><b>{impact(forecast.protected, forecast.protectedFiles)}</b><span>always protected by safety rules</span></div>
        </div>
      ) : (
        <p className="automation-policy__empty">No open review findings are available to preview for this run.</p>
      )}

      <p className="automation-policy__guardrail">
        Human-only, subjective, unsupported, missing-evidence and failed-verification work always stays in review.
        This preview does not change the active run.
      </p>
    </section>
  )
}
