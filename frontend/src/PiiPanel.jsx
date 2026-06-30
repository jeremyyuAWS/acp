import { useState, useEffect } from 'react'
import { getScanPii } from './api.js'

// Sensitive-data (PII) exposure — surfaces the deep-scan's findings (ADR 0006) that were
// recorded server-side but never shown in the dashboard. Self-contained: fetches its own
// data and renders nothing when the deep scan wasn't run or found no sensitive data.
export default function PiiPanel({ scanId }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    if (!scanId) return undefined
    let alive = true
    getScanPii(scanId).then((d) => { if (alive) setData(d) }).catch(() => {})
    return () => { alive = false }
  }, [scanId])

  const summary = data?.summary
  if (!summary || !summary.documents) return null   // deep scan off, or no sensitive data found
  const byType = summary.by_type || []
  const max = Math.max(1, ...byType.map((t) => t.count || 0))

  return (
    <section className="panel" style={{ borderLeft: '4px solid #1F5FA8' }}>
      <h2>🔒 Sensitive data exposure <span className="muted" style={{ fontWeight: 400 }}>· PII detected by the deep scan</span></h2>
      <div className="metrics" style={{ marginTop: 8 }}>
        <div className="metric"><span>documents with PII</span><b style={{ color: '#1F5FA8' }}>{summary.documents.toLocaleString()}</b></div>
        <div className="metric"><span>items detected</span><b>{(summary.items || 0).toLocaleString()}</b></div>
        <div className="metric"><span>data types</span><b>{byType.length}</b></div>
      </div>
      {byType.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {byType.slice(0, 8).map((t) => (
            <div className="critrow" key={`${t.pii_type}-${t.label}`} style={{ gridTemplateColumns: '180px 1fr 44px', marginBottom: 4 }}>
              <span className="critlabel" style={{ textAlign: 'left' }}>{t.label || t.pii_type}</span>
              <span className="track"><i style={{ width: `${(t.count / max) * 100}%`, background: '#1F5FA8', transition: 'width .9s ease' }} /></span>
              <span className="critn">{(t.count || 0).toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.5 }}>
        All samples are masked — raw values are never stored. Documents carrying SSNs, card numbers or other
        regulated data warrant an access-control / retention review alongside accessibility remediation.
      </p>
    </section>
  )
}
