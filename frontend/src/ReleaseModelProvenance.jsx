import { useEffect, useMemo, useState } from 'react'
import { getScanAiCalls } from './api.js'

export function aggregateReleaseModelCalls(calls = [], selectedFiles = []) {
  const selected = new Set(selectedFiles)
  const scoped = calls.filter((call) => !selected.size || selected.has(call.file))
  const groups = new Map()
  scoped.forEach((call) => {
    const provider = call.provider || 'not reported'
    const model = call.model || 'not reported'
    const zone = call.zone || 'not reported'
    const key = `${provider}\u0000${model}\u0000${zone}`
    const row = groups.get(key) || { provider, model, zone, calls: 0, succeeded: 0, failed: 0, latencyTotal: 0, latencySamples: 0, costUsd: 0, costSamples: 0 }
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
    groups.set(key, row)
  })
  return [...groups.values()].map((row) => ({
    ...row,
    averageLatencyMs: row.latencySamples ? Math.round(row.latencyTotal / row.latencySamples) : null,
  })).sort((a, b) => b.calls - a.calls || a.provider.localeCompare(b.provider))
}

export default function ReleaseModelProvenance({ scanId, selectedFiles = [] }) {
  const [calls, setCalls] = useState([])
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let live = true
    setLoaded(false)
    if (!scanId) { setCalls([]); setLoaded(true); return undefined }
    getScanAiCalls(scanId).then((rows) => {
      if (live) setCalls(Array.isArray(rows) ? rows : [])
    }).finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [scanId])

  const selectedKey = selectedFiles.join('\u0000')
  const rows = useMemo(() => aggregateReleaseModelCalls(calls, selectedKey ? selectedKey.split('\u0000') : []), [calls, selectedKey])
  if (!loaded) return <div className="release-model-evidence muted" role="status">Loading recorded AI provenance…</div>
  if (!rows.length) return (
    <div className="release-model-evidence">
      <b>AI provenance</b>
      <span className="muted">No model calls are recorded for the selected files.</span>
    </div>
  )

  const total = rows.reduce((sum, row) => sum + row.calls, 0)
  return (
    <section className="release-model-evidence" aria-label="AI provenance for selected release files">
      <div className="release-model-evidence__heading">
        <b>AI provenance</b>
        <span>{total} recorded model {total === 1 ? 'call' : 'calls'}</span>
      </div>
      <div className="release-model-evidence__rows">
        {rows.map((row) => <div className="release-model-evidence__row" key={`${row.provider}:${row.model}:${row.zone}`}>
          <span><b>{row.provider}</b> · {row.model} · {row.zone}</span>
          <span>{row.succeeded} succeeded{row.failed ? ` · ${row.failed} failed` : ''} · {row.averageLatencyMs == null ? 'latency not reported' : `${row.averageLatencyMs.toLocaleString()} ms avg`} · {row.costSamples ? `$${row.costUsd.toFixed(4)} measured` : 'spend not reported'}</span>
        </div>)}
      </div>
      <p>These are recorded call outcomes, not proof that a reviewer accepted the draft or that the written fix passed validation.</p>
    </section>
  )
}
