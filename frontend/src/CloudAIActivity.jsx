import useWaterfallDrawerMetrics from './useWaterfallDrawerMetrics.js'
import WaterfallDrawerCharts, { ContributionBars, SettledSpend } from './WaterfallDrawerCharts.jsx'
import './waterfall-drawer-charts.css'

const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0
  ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value) : 'Unavailable'
export function observedPaceScale(pace, trend) {
  const values = (trend?.points || []).map(point => point.value).filter(value => typeof value === 'number' && Number.isFinite(value) && value >= 0)
  if (typeof pace?.value !== 'number' || !Number.isFinite(pace.value) || pace.value < 0 || !values.length) return pace
  return { ...pace, scaleMax: Math.max(1, pace.value, ...values), scaleLabel: 'Highest observed minute in this window; not a capacity target' }
}
export function AIActivityCharts({ data }) {
  const models = data.models?.rows || []
  return <div className="wd-charts wd-ai-dashboard">
    <WaterfallDrawerCharts contribution={data.models} pace={observedPaceScale(data.pace, data.trend)} trend={data.trend} />
    <SettledSpend data={data.spend} />
    <ContributionBars data={data.contribution} />
    <section className="wd-chart wd-model-details" aria-label="Individual model usage">
      <h3>Individual model usage</h3>
      <p>Tokens are provider-reported. Missing usage stays unavailable. Usable AI output is not a verified repair.</p>
      {!models.length ? <p>No recorded model calls for this run.</p> : <div className="wd-model-scroll" tabIndex={0} role="region" aria-label="Scrollable model usage table">
        <table><thead><tr><th>Provider and model</th><th>Attempts</th><th>Awaiting result</th><th>Input tokens</th><th>Output tokens</th><th>Average attempt time</th></tr></thead>
          <tbody>{models.map(model => <tr key={model.id}><th scope="row">{model.label}</th><td>{number(model.value)}</td><td>{number(model.active)}</td><td>{number(model.input_tokens)}</td><td>{number(model.output_tokens)}</td><td>{number(model.average_seconds)}{model.average_seconds != null ? ' s' : ''}<br /><small>{number(model.timed_attempts)} measured attempts</small></td></tr>)}</tbody></table>
      </div>}
      <p>{data.timing?.basis || 'Timing includes the attempt lifecycle, not just model response time.'}</p>
    </section>
  </div>
}
export default function CloudAIActivity({ scanId, batchId, live, paused, aiEnabled }) {
  const metrics = useWaterfallDrawerMetrics({ scanId, batchId, scope: {}, live: live && !paused, enabled: aiEnabled !== false })
  if (aiEnabled === false) return null
  return <section aria-label="AI usage for this remediation run">
    <h3>AI usage · this run</h3>
    <p>Actual local and cloud model activity, including fallback attempts. Select a waterfall model below for its individual evidence.</p>
    {metrics.loading && !metrics.data && <p role="status">Loading AI usage…</p>}
    {metrics.error && <p role="status">{metrics.data ? 'Refresh delayed; showing the last recorded usage.' : 'AI usage unavailable.'} <button type="button" onClick={metrics.refresh}>Retry usage</button></p>}
    {metrics.data && <><p>{metrics.data.mode === 'recorded' ? 'Saved activity' : 'Live activity'} · {metrics.data.complete ? 'Complete retained attempt coverage' : 'Partial retained coverage; charts are not whole-run totals'}</p><AIActivityCharts data={metrics.data} /></>}
  </section>
}
