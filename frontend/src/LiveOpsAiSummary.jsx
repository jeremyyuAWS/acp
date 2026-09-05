import { useEffect, useState } from 'react'
import { getAiCosts, getAiProvidersHealth } from './api.js'

export default function LiveOpsAiSummary() {
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    const refresh = () => Promise.all([getAiCosts(), getAiProvidersHealth(24)])
      .then(([costs, health]) => { if (live) { setData({ costs, health }); setFailed(false) } })
      .catch(() => { if (live) setFailed(true) })
    refresh()
    const timer = window.setInterval(refresh, 60000)
    return () => { live = false; window.clearInterval(timer) }
  }, [])
  if (failed) return <section className="panel" role="status" style={{ padding: 12, marginBottom: 12 }}>
    <b>AI operations unavailable</b><div className="muted" style={{ fontSize: 12 }}>Provider telemetry could not be refreshed. No values are estimated.</div>
  </section>
  if (!data) return <section className="panel muted" style={{ padding: 12, marginBottom: 12 }}>Loading AI operations…</section>
  const today = data.costs?.today || {}
  const second = (today.by_surface || []).find((x) => x.key === 'assessment_second_opinion')
  const providers = Object.values(data.health?.providers || {})
  const errors = providers.reduce((n, p) => n + Number(p.errors || 0), 0)
  return <section className="panel" aria-label="Live AI operations" style={{ padding: 12, marginBottom: 12 }}>
    <div><b>AI operations</b><div className="muted" style={{ fontSize: 12 }}>Measured provider activity from the shared AI call ledger</div></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginTop: 10 }}>
      <div><span className="muted" style={{ fontSize: 11 }}>TODAY</span><br /><b>{today.calls || 0} calls</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>SECOND OPINIONS</span><br /><b>{second?.calls || 0} calls</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>MEASURED AI COST</span><br /><b>${Number(today.cost_usd || 0).toFixed(4)}</b></div>
      <div><span className="muted" style={{ fontSize: 11 }}>PROVIDER HEALTH</span><br /><b>{providers.length ? `${errors} errors / 24h` : 'Not reported'}</b></div>
    </div>
  </section>
}
