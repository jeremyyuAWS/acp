import { useEffect, useState } from 'react'
import CollapsibleSection from './CollapsibleSection.jsx'
import { getLiveOpsCosts } from './api.js'

export function money(value, digits = 2) {
  return value == null ? 'Not reported' : `$${Number(value).toFixed(digits)}`
}

function age(iso) {
  if (!iso) return 'measurement time unavailable'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`
}

function SetupSignal({ label, state }) {
  const configured = !!state?.configured
  const connected = configured && state?.available !== false
  const status = !configured ? 'Not configured' : connected ? 'Connected' : 'Unavailable'
  return <div role="group" aria-label={`${label}: ${status.toLowerCase()}`}
    style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '8px 10px', minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
      <span aria-hidden="true" style={{ color: connected ? 'var(--success-fg,#287d3c)' : 'var(--amber-ink,#92400e)' }}>
        {connected ? '●' : '○'}
      </span>
      <b>{label}</b>
      <span className="muted" style={{ marginLeft: 'auto' }}>{status}</span>
    </div>
    {state?.reason && <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{state.reason}</div>}
  </div>
}

function serviceAllocation(service) {
  if (service.allocated_vcpu != null && service.allocated_memory_gib != null) {
    return `${service.allocated_vcpu} vCPU · ${service.allocated_memory_gib} GiB allocated`
  }
  if (service.replicas != null && service.cpu_cores_per_replica != null && service.memory_gib_per_replica != null) {
    return `${service.replicas * service.cpu_cores_per_replica} vCPU · ${service.replicas * service.memory_gib_per_replica} GiB allocated`
  }
  return 'Capacity not reported'
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
  const setup = costs.setup || {
    capacity: { configured: !!costs.configured },
    rate_card: { configured: !!costs.rate_source },
    billing_actuals: { configured: !!costs.billing?.configured },
  }
  const missing = Object.values(setup).filter((item) => !item?.configured).length
  return <CollapsibleSection id="cost" label="Azure cost transparency"
    summary={<span style={{ display: 'inline-flex', justifyContent: 'space-between', alignItems: 'start',
      gap: 12, flexWrap: 'wrap', width: 'calc(100% - 18px)' }}>
      <span><b>Cost transparency</b>
        <span className="muted" style={{ display: 'block', fontSize: 12 }}>{estimated ? costs.estimate_label : 'No infrastructure cost has been calculated'}</span></span>
      <span className="chip">{estimated ? 'Estimated' : `${missing || 1} input${missing === 1 ? '' : 's'} missing`} · {age(costs.measured_at)}</span>
    </span>}>
    <div aria-label="Cost data connections" style={{ display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: 8, marginTop: 10 }}>
      <SetupSignal label="Worker capacity" state={setup.capacity} />
      <SetupSignal label="Rate card" state={setup.rate_card} />
      <SetupSignal label="Billing actuals" state={setup.billing_actuals} />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginTop: 10 }}>
      <div><span className="muted" style={{ fontSize: 11 }}>CURRENT CAPACITY / HOUR</span><br /><b style={{ fontSize: 20 }}>{money(costs.estimated_hourly_usd, 4)}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>PROJECTED / DAY</span><br /><b style={{ fontSize: 20 }}>{money(costs.estimated_daily_usd)}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>RATE SOURCE</span><br /><b>{costs.rate_source || 'Not configured'}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>AZURE BILLING ACTUALS</span><br /><b>{costs.billing?.freshness_label || 'Not reported'}</b></div>
    </div>
    {!!costs.services?.length && <details style={{ marginTop: 10 }} open={!estimated}>
      <summary><b>Capacity and cost by worker service</b></summary>
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        {costs.services.map((service) => <div key={service.app} style={{ display: 'flex', justifyContent: 'space-between', gap: 12,
          fontSize: 12, borderTop: '1px solid var(--line)', paddingTop: 6, flexWrap: 'wrap' }}>
          <span><b>{service.app}</b> · {service.replicas ?? 'Not reported'} running replicas
            <span className="muted" style={{ display: 'block', marginTop: 2 }}>{serviceAllocation(service)}</span></span>
          <span style={{ textAlign: 'right' }}>{service.estimated_hourly_usd == null
            ? <><b>Estimate unavailable</b><span className="muted" style={{ display: 'block', marginTop: 2 }}>{service.unavailable_reason || 'Required cost inputs are missing'}</span></>
            : <>{money(service.estimated_hourly_usd, 4)}/hour</>}</span>
        </div>)}
      </div>
    </details>}
    {costs.billing?.delay_note && <div className="muted" style={{ fontSize: 11, marginTop: 9 }}>
      Billing freshness: {costs.billing.delay_note}
    </div>}
    <div className="muted" style={{ fontSize: 11, marginTop: 9 }}>
      Estimates use running replica allocation and an explicit rate card. They are not invoices; billing actuals are shown separately because Azure Cost Management is delayed.
    </div>
  </CollapsibleSection>
}
