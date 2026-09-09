import { useId } from 'react'
import './waterfall-drawer-charts.css'

const valid = n => typeof n === 'number' && Number.isFinite(n) && n >= 0
const format = (n, unit) => !valid(n) ? 'Unavailable' : unit === 'USD' ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(n) : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n)
const palette = ['#28728a', '#3966bf', '#8254a1', '#a84284', '#a67410', '#55734f']
function Empty({ children }) { return <p className="wd-chart-empty">{children || 'Recorded chart data is unavailable for this scope.'}</p> }

export function ContributionBars({ data, onInspect }) {
  const rows = (data?.rows || []).filter(row => valid(row.value))
  const max = Math.max(0, ...rows.map(row => row.value))
  return <section className="wd-chart" aria-label={data?.title || 'Contribution'}>
    <h3>{data?.title || 'What this step added'}</h3>
    {!rows.length ? <Empty>{data?.reason}</Empty> : <>
      <p>{data.unit} · {data.basis}</p>
      <ul className="wd-bars">{rows.map((row, index) => <li key={row.id}>
        {onInspect ? <button type="button" className="wd-bar-button" onClick={() => onInspect(row.id)} aria-label={`Inspect ${row.label}: ${format(row.value)} ${data.unit}`}><span>{row.label}</span><strong>{format(row.value)}</strong></button> : <div className="wd-bar-label"><span>{row.label}</span><strong>{format(row.value)}</strong></div>}
        <div className="wd-bar-track" aria-hidden="true"><i style={{ width: `${max ? row.value / max * 100 : 0}%`, background: palette[index % palette.length] }} /></div>
      </li>)}</ul>
    </>}
  </section>
}

export function ActivityTrend({ data }) {
  const titleId = useId()
  const points = data?.points || []
  const known = points.filter(point => valid(point.value) && Number.isFinite(Date.parse(point.timestamp)))
  const timestamps = points.map(point => Date.parse(point.timestamp)).filter(Number.isFinite)
  const start = Math.min(...timestamps), end = Math.max(...timestamps)
  const max = Math.max(1, ...known.map(point => point.value))
  const x = point => 18 + (end > start ? (Date.parse(point.timestamp) - start) / (end - start) : .5) * 324
  const y = point => 110 - point.value / max * 90
  let pen = false
  const path = points.map(point => {
    if (!valid(point.value) || !Number.isFinite(Date.parse(point.timestamp))) { pen = false; return '' }
    const command = `${pen ? 'L' : 'M'} ${x(point)} ${y(point)}`; pen = true; return command
  }).join(' ')
  return <section className="wd-chart" aria-label="Activity over time"><h3>Activity over time</h3>
    {!known.length ? <Empty>{data?.reason}</Empty> : <>
      <p>{data.unit} · {data.bucketLabel} · {data.timeZone}<br />{data.windowLabel}</p>
      <svg className="wd-trend" viewBox="0 0 360 135" role="img" aria-labelledby={titleId}>
        <title id={titleId}>Recorded activity; exact timestamps and values are in the chart data table. Missing observations are gaps.</title>
        <path d="M18 20V110H342" fill="none" stroke="currentColor" opacity=".25" />
        <path d={path} fill="none" stroke="#3966bf" strokeWidth="3" />
        {known.map((point, index) => <circle key={`${point.timestamp}-${index}`} cx={x(point)} cy={y(point)} r="3" fill="#8254a1" />)}
        <text x="20" y="132">0</text><text x="20" y="15">{format(max)} {data.unit}</text>
      </svg>
      <details><summary>Chart data</summary><table><caption>{data.unit} · {data.timeZone}</caption><thead><tr><th>Time</th><th>Value</th></tr></thead><tbody>{points.map((point, index) => <tr key={`${point.timestamp}-${index}`}><td><time>{point.timestamp}</time></td><td>{format(point.value)}</td></tr>)}</tbody></table></details>
    </>}
  </section>
}

export function ProcessingPace({ data }) {
  const gauge = valid(data?.scaleMax) && data.scaleMax > 0 && data.scaleLabel
  const usable = valid(data?.value) && data?.observedSeconds >= 60
  const rotation = -90 + Math.min(1, (data?.value || 0) / (data?.scaleMax || 1)) * 180
  return <section className="wd-chart" aria-label="Processing pace"><h3>Processing pace</h3>
    {!usable ? <Empty>{data?.reason || (data?.observedSeconds < 60 ? 'Collecting pace data.' : 'A recorded time window is not available.')}</Empty> : <>
      {gauge && <svg className="wd-gauge" viewBox="0 0 220 125" role="img" aria-label={`Pace ${format(data.value)} ${data.unit}; scale zero to ${data.scaleMax}, ${data.scaleLabel}`}>
        <path d="M25 110A85 85 0 0 1 195 110" fill="none" stroke="#e7e0ef" strokeWidth="14" />
        <path d="M25 110A85 85 0 0 1 195 110" fill="none" stroke="#3966bf" strokeWidth="14" pathLength="100" strokeDasharray={`${Math.min(100, data.value / data.scaleMax * 100)} 100`} />
        <path d="M110 110V42" stroke="#50415e" strokeWidth="3" transform={`rotate(${rotation} 110 110)`} /><circle cx="110" cy="110" r="5" fill="#50415e" />
      </svg>}
      <strong className="wd-pace-number">{format(data.value)}</strong><p>{data.unit}<br />{data.windowLabel}</p>
      {gauge && <p className="wd-chart-meta">Scale 0–{data.scaleMax}: {data.scaleLabel}{data.value > data.scaleMax ? ' · Above displayed scale' : ''}</p>}
    </>}
  </section>
}

export function SettledSpend({ data }) {
  const rows = (data?.rows || []).filter(row => valid(row.value))
  const sum = rows.reduce((total, row) => total + row.value, 0)
  const complete = rows.length === (data?.rows || []).length && data?.unit === 'USD' && new Set(rows.map(row => row.id)).size === rows.length && data?.complete === true && data?.partition === true && valid(data?.total) && Math.abs(sum - data.total) < .0000001
  const sorted = [...rows].sort((a, b) => b.value - a.value)
  const slices = sorted.length > 6 ? [...sorted.slice(0, 5), { id: 'other', label: 'Other', value: sorted.slice(5).reduce((total, row) => total + row.value, 0) }] : sorted
  const donut = complete && sum > 0 && rows.filter(row => row.value > 0).length > 1
  let offset = 0
  return <section className="wd-chart" aria-label="Settled spend by model"><h3>Settled spend by model</h3>
    {!rows.length ? <Empty>{data?.reason || 'Cost not recorded.'}</Empty> : <>
      {!complete && <p>{data?.reason || 'Partial attribution. Available recorded charges are listed without percentages.'}</p>}
      {donut && <svg className="wd-donut" viewBox="0 0 140 140" role="img" aria-label={`Settled spend ${format(sum, data.unit)}; model amounts follow below.`}>{slices.map((row, index) => {
        const percent = row.value / sum * 100; const before = offset; offset += percent
        return <circle key={row.id} cx="70" cy="70" r="52" pathLength="100" fill="none" stroke={palette[index]} strokeWidth="19" strokeDasharray={`${percent} ${100 - percent}`} strokeDashoffset={-before} transform="rotate(-90 70 70)" />
      })}</svg>}
      <ul className="wd-spend-list">{slices.map((row, index) => <li key={row.id}><span><i style={{ background: palette[index % palette.length] }} aria-hidden="true" />{row.label}</span><strong>{format(row.value, data.unit)}{donut ? ` · ${format(row.value / sum * 100)}%` : ''}</strong></li>)}</ul>
      <p>Settled charges only. Reserved spending is separate.</p>
    </>}
  </section>
}

export default function WaterfallDrawerCharts({ contribution, pace, trend, spend, onInspect, showSpend = false }) {
  return <div className="wd-charts"><ContributionBars data={contribution} onInspect={onInspect} />{showSpend ? <SettledSpend data={spend} /> : <ProcessingPace data={pace} />}<ActivityTrend data={trend} /></div>
}
