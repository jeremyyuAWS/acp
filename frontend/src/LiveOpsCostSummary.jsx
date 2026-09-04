import { useEffect, useState } from 'react'
import { getLiveOpsCosts } from './api.js'

export function money(value, digits = 2) {
  return value == null ? 'Not reported' : `$${Number(value).toFixed(digits)}`
}

function age(iso) {
  if (!iso) return 'measurement time unavailable'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`
}

export default function LiveOpsCostSummary() {
  const [costs, setCosts] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    const refresh = () => getLiveOpsCosts()
      .then((value) => { if (active) { setCosts(value); setFailed(false) } })
      .catch(() => { if (active) setFailed(true) })
    refresh()
    const timer = window.setInterval(refresh, 60000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  if (failed) return <section className="panel" role="status" style={{ padding: 12, marginBottom: 12 }}>
    <b>Cost transparency unavailable</b>
    <div className="muted" style={{ fontSize: 12 }}>No dollar value is estimated while the cost feed cannot be refreshed.</div>
  </section>
  if (!costs) return <section className="panel muted" style={{ padding: 12, marginBottom: 12 }}>Loading cost transparency…</section>

  const estimated = costs.estimated_hourly_usd != null
  return <section className="panel" aria-label="Azure cost transparency" style={{ padding: 12, marginBottom: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12, flexWrap: 'wrap' }}>
      <div><b>Cost transparency</b>
        <div className="muted" style={{ fontSize: 12 }}>{estimated ? costs.estimate_label : 'No infrastructure cost has been calculated'}</div></div>
      <span className="chip">{estimated ? 'Estimated' : 'Not reported'} · {age(costs.measured_at)}</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginTop: 10 }}>
      <div><span className="muted" style={{ fontSize: 11 }}>CURRENT CAPACITY / HOUR</span><br /><b style={{ fontSize: 20 }}>{money(costs.estimated_hourly_usd, 4)}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>PROJECTED / DAY</span><br /><b style={{ fontSize: 20 }}>{money(costs.estimated_daily_usd)}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>RATE SOURCE</span><br /><b>{costs.rate_source || 'Not configured'}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>AZURE BILLING ACTUALS</span><br /><b>{costs.billing?.freshness_label || 'Not reported'}</b></div>
    </div>
    {!!costs.services?.length && <details style={{ marginTop: 10 }}>
      <summary><b>Cost by worker service</b></summary>
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        {costs.services.map((service) => <div key={service.app} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
          <span><b>{service.app}</b> · {service.replicas ?? 'Not reported'} running replicas</span>
          <span>{money(service.estimated_hourly_usd, 4)}/hour</span>
        </div>)}
      </div>
    </details>}
    <div className="muted" style={{ fontSize: 11, marginTop: 9 }}>
      Estimates use running replica allocation and an explicit rate card. They are not invoices; billing actuals are shown separately because Azure Cost Management is delayed.
    </div>
  </section>
}
