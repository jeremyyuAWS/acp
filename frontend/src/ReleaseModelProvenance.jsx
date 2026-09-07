import { useEffect, useMemo, useState } from 'react'
import { getReleaseAiProvenance } from './api.js'

const REVIEW_KEYS = ['approve', 'edit', 'reject', 'skip']
const VALIDATION_KEYS = ['verified_cleared', 'verified_regressed', 'verified_still_failing', 'could_not_verify', 'write_unresolved']

export function aggregateReleaseModelCalls(calls = []) {
  const groups = new Map()
  calls.forEach((call) => {
    const provider = call.provider || 'not reported'
    const model = call.model || 'not reported'
    const zone = call.zone || 'not reported'
    const key = `${provider}\u0000${model}\u0000${zone}`
    const row = groups.get(key) || {
      provider, model, zone, calls: 0, succeeded: 0, failed: 0,
      latencyTotal: 0, latencySamples: 0, costUsd: 0, costSamples: 0,
      review: Object.fromEntries(REVIEW_KEYS.map((name) => [name, 0])), reviewLinked: 0,
      validation: Object.fromEntries(VALIDATION_KEYS.map((name) => [name, 0])), validationLinked: 0,
      newlyFailing: 0,
    }
    row.calls += 1
    if (call.ok === true || call.ok === 1) row.succeeded += 1
    else row.failed += 1
    if (Number.isFinite(Number(call.latency_ms))) {
      row.latencyTotal += Number(call.latency_ms)
      row.latencySamples += 1
    }
    if (call.cost_usd !== null && call.cost_usd !== undefined && Number.isFinite(Number(call.cost_usd))) {
      row.costUsd += Number(call.cost_usd)
      row.costSamples += 1
    }
    ;(call.review_decisions || []).forEach((decision) => {
      if (REVIEW_KEYS.includes(decision.action)) {
        row.review[decision.action] += 1
        row.reviewLinked += 1
      }
    })
    ;(call.validation_outcomes || []).forEach((outcome) => {
      if (VALIDATION_KEYS.includes(outcome.outcome)) {
        row.validation[outcome.outcome] += 1
        row.validationLinked += 1
        if (Array.isArray(outcome.regressions) && outcome.regressions.length) row.newlyFailing += 1
      }
    })
    groups.set(key, row)
  })
  return [...groups.values()].map((row) => ({
    ...row,
    averageLatencyMs: row.latencySamples ? Math.round(row.latencyTotal / row.latencySamples) : null,
  })).sort((a, b) => b.calls - a.calls || a.provider.localeCompare(b.provider))
}

const Count = ({ value, singular, plural = `${singular}s` }) => <span>{value} {value === 1 ? singular : plural}</span>

export default function ReleaseModelProvenance({ scanId, selectedFiles = [] }) {
  const [calls, setCalls] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const selectedKey = selectedFiles.join('\u0000')
  useEffect(() => {
    let live = true
    setLoaded(false)
    setLoadFailed(false)
    const files = selectedKey ? selectedKey.split('\u0000') : []
    getReleaseAiProvenance(scanId, files).then((rows) => {
      if (live) setCalls(Array.isArray(rows) ? rows : [])
    }).catch(() => { if (live) { setCalls([]); setLoadFailed(true) } }).finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [scanId, selectedKey])

  const rows = useMemo(() => aggregateReleaseModelCalls(calls), [calls])
  if (!loaded) return <div className="release-model-evidence muted" role="status">Loading recorded AI provenance…</div>
  if (loadFailed) return <div className="release-model-evidence" role="status"><b>AI provenance unavailable</b><span className="muted">Recorded calls, reviewer decisions, and post-write validation could not be loaded. No outcome is assumed.</span></div>
  if (!rows.length) return (
    <div className="release-model-evidence">
      <b>AI provenance</b>
      <span className="muted">No model calls are recorded for the selected files.</span>
    </div>
  )

  const total = rows.reduce((sum, row) => sum + row.calls, 0)
  return (
    <section className="release-model-evidence" aria-labelledby="release-ai-provenance-heading">
      <div className="release-model-evidence__heading">
        <b id="release-ai-provenance-heading">AI provenance</b>
        <span>{total} recorded model {total === 1 ? 'call' : 'calls'} for this selection</span>
      </div>
      <div className="release-model-evidence__rows">
        {rows.map((row) => <article className="release-model-evidence__row" key={`${row.provider}:${row.model}:${row.zone}`}>
          <h4>{row.provider} · {row.model} · {row.zone}</h4>
          <div className="release-model-evidence__groups">
            <div><b>Call operation</b><div><Count value={row.succeeded} singular="succeeded" plural="succeeded" /> · <Count value={row.failed} singular="failed" plural="failed" /> · {row.averageLatencyMs == null ? 'latency not reported' : `${row.averageLatencyMs.toLocaleString()} ms average`} · {row.costSamples ? `$${row.costUsd.toFixed(4)} measured spend` : 'spend not reported'}</div></div>
            <div><b>Reviewer decisions</b>{row.reviewLinked
              ? <div><Count value={row.review.approve} singular="approved unchanged" plural="approved unchanged" /> · <Count value={row.review.edit} singular="edited then approved" plural="edited then approved" /> · <Count value={row.review.reject} singular="rejected" plural="rejected" />{row.review.skip ? <> · <Count value={row.review.skip} singular="skipped" plural="skipped" /></> : null}</div>
              : <div className="release-model-evidence__missing">Not recorded for these calls</div>}</div>
            <div><b>Post-write validation</b>{row.validationLinked
              ? <div><Count value={row.validation.verified_cleared} singular="cleared" plural="cleared" /> · <Count value={row.validation.verified_regressed} singular="regressed" plural="regressed" /> · <Count value={row.validation.verified_still_failing} singular="still failing" plural="still failing" /> · <Count value={row.validation.could_not_verify} singular="not verified" plural="not verified" /> · <Count value={row.validation.write_unresolved} singular="write unresolved" plural="writes unresolved" />{row.newlyFailing ? <> · <Count value={row.newlyFailing} singular="outcome with a newly failing criterion" /></> : null}</div>
              : <div className="release-model-evidence__missing">Not recorded for these calls</div>}</div>
          </div>
        </article>)}
      </div>
      <details className="release-model-evidence__definitions">
        <summary>What these outcomes mean</summary>
        <dl>
          <dt>Call operation</dt><dd>Whether the provider returned a usable response, plus recorded latency and spend. It is not review or validation evidence.</dd>
          <dt>Reviewer decisions</dt><dd>Only human actions carrying the exact durable ID of one of these model calls. “Not recorded” is unknown, not zero decisions.</dd>
          <dt>Post-write validation</dt><dd>Only re-scan outcomes linked to that same call ID. Cleared means the target criterion passed; regressed means the write introduced a newly failing criterion.</dd>
        </dl>
      </details>
    </section>
  )
}
