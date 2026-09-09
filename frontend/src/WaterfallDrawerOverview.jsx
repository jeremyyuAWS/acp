import { useEffect, useState } from 'react'
import WaterfallDrawerCharts, { SettledSpend } from './WaterfallDrawerCharts.jsx'
import WaterfallCount from './WaterfallCount.jsx'
import useWaterfallDrawerMetrics from './useWaterfallDrawerMetrics.js'
import { buildWaterfallDrawerCharts } from './waterfallDrawerChartData.js'

export function selectedDrawerScope(model) {
  const stage = ['primary', 'fallback_1', 'fallback_2'].includes(model?.stepId) ? model.stepId
    : ['review', 'final_review'].includes(model?.purpose) ? model.purpose : null
  return stage ? { stage, provider: model?.provider || null, model: model?.model || null } : null
}
export default function WaterfallDrawerOverview({ scanId, batchId, identity, selectedModel, role,
  description, snapshot, live, paused, selectTab }) {
  const scope = selectedDrawerScope(selectedModel)
  const metrics = useWaterfallDrawerMetrics({ scanId, batchId, scope: scope || {}, live, enabled: !!scope })
  const [reduced, setReduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false)
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(!!media?.matches)
    media?.addEventListener?.('change', update)
    return () => media?.removeEventListener?.('change', update)
  }, [])
  const charts = buildWaterfallDrawerCharts({ metrics: metrics.data })
  const counterIdentity = `${identity}:${JSON.stringify(scope)}:${metrics.baseline || 0}`
  return <div className="wf-detail">
    <p>{description}</p>
    {selectedModel?.detail && selectedModel.detail !== 'Recorded outcome unknown.' && <p>{selectedModel.detail}</p>}
    {scope ? <>
      <p className="wf-secondary">Selected stage and model · {metrics.data?.mode === 'recorded' ? 'saved results' : live ? 'recorded activity updates' : 'saved results'}. Completions include the attempt lifecycle, not pure model response time.</p>
      {metrics.loading && !metrics.data && <p role="status">Loading recorded stage metrics…</p>}
      {metrics.error && <p role="status">{metrics.data ? 'Refresh delayed · showing the last recorded metrics.' : 'Stage metrics unavailable.'} <button type="button" onClick={metrics.refresh}>Retry metrics</button></p>}
      {metrics.data && <>
        <dl className="wf-spending" aria-label="Recorded attempt counters">{charts.contribution.rows.map(row => <div key={row.id}><dt>{row.label} · attempts</dt><dd><WaterfallCount value={row.value} identity={counterIdentity} paused={paused || reduced || metrics.error || !live} /></dd></div>)}</dl>
        <WaterfallDrawerCharts {...charts} />
        <details><summary>Settled cost for this stage and model</summary><SettledSpend data={charts.spend} /></details>
      </>}
    </> : role === 'rules' || role === 'verify' || role === 'approval' ? <>
      <dl className="wf-spending"><div><dt>{role === 'approval' ? 'Review items · run total' : 'Verified changes · all origins, run total'}</dt><dd><WaterfallCount value={role === 'approval' ? snapshot.review?.items : snapshot.fixes?.verified} identity={`${identity}:${role}`} paused={paused || reduced || !live} /></dd></div></dl>
      <p>No model pace is attributed to this stage. Saved evidence uses the units recorded for this run.</p>
    </> : <p>Chart scope unavailable: the saved records do not establish an exact generation position. Recorded attempts remain available.</p>}
    <button type="button" className="ghost" onClick={() => selectTab('Attempts')}>View attempts</button>
  </div>
}
