import { useEffect, useState, useCallback } from 'react'
import { getAdminAnalytics } from './api.js'
import { Bars } from './charts.jsx'

const SOURCE_COLOR = { drive: '#4285F4', sharepoint: '#0078D4', local: '#6E62C4', unknown: '#9a948f' }
const SOURCE_LABEL = { drive: 'Google Drive', sharepoint: 'SharePoint', local: 'Local', unknown: 'Unknown' }
const PERIOD_OPTS = [
  ['today', 'Today'],
  ['7d',    'Last 7 days'],
  ['30d',   'Last 30 days'],
  ['90d',   'Last 90 days'],
  ['all',   'All time'],
]

function fmt(n, decimals = 0) {
  if (n == null) return '—'
  return typeof n === 'number' ? n.toFixed(decimals) : String(n)
}

function fmtDate(iso) {
  if (!iso) return '—'
  return iso.slice(0, 10)
}

function KpiCard({ label, value, sub, color }) {
  return (
    <div className="panel" style={{ flex: '1 1 160px', minWidth: 140, padding: '18px 20px' }}>
      <div style={{ fontSize: 28, fontWeight: 700, color: color || 'var(--ink)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function DirectionBadge({ direction }) {
  if (!direction || direction === 'insufficient') return null
  const cfg = {
    improving: { label: 'Improving', color: '#639922' },
    declining:  { label: 'Declining',  color: '#A32D2D' },
    flat:       { label: 'Stable',     color: '#854F0B' },
  }[direction]
  if (!cfg) return null
  return (
    <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color,
                   background: cfg.color + '1a', borderRadius: 4, padding: '2px 8px' }}>
      {cfg.label}
    </span>
  )
}

export function AdminInsights({ me }) {
  const [period, setPeriod]   = useState('30d')
  const [source, setSource]   = useState(null)
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(() => {
    let live = true
    setLoading(true); setError(null)
    getAdminAnalytics(period, source)
      .then((d) => { if (live) { setData(d); setLoading(false) } })
      .catch((e) => { if (live) { setError(e?.message || 'Load failed'); setLoading(false) } })
    return () => { live = false }
  }, [period, source])

  useEffect(() => { return load() }, [load])

  const sources = data ? Object.keys(data.by_source || {}) : []
  const barItems = sources.map((src) => {
    const b = data.by_source[src]
    const rate = b.docs ? Math.round(b.certifiable / b.docs * 100) : null
    return { label: SOURCE_LABEL[src] || src, value: rate, color: SOURCE_COLOR[src] || '#9a948f',
             sub: `${b.scans} scan${b.scans !== 1 ? 's' : ''} · ${b.docs} docs` }
  })

  const trend = data?.trend?.summary || {}

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Admin Insights</h1>
        <span style={{ fontSize: 13, color: 'var(--muted)' }}>Estate analytics</span>
      </div>

      {/* Control bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 24 }}>
        {/* Scope — placeholder for v1 */}
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Scope filter — coming soon">
          Scope: All
        </button>

        {/* Period */}
        <select className="chip" value={period} onChange={(e) => setPeriod(e.target.value)}
                style={{ border: 'none', background: 'transparent', cursor: 'pointer' }}>
          {PERIOD_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>

        {/* Compare — placeholder */}
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Period comparison — coming soon">
          Compare
        </button>

        {/* Rubric — placeholder */}
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Rubric filter — coming soon">
          Rubric: All
        </button>

        {/* More filters — placeholder */}
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Additional filters — coming soon">
          More filters
        </button>

        <div style={{ flex: 1 }} />

        <button className="chip" onClick={load} disabled={loading} title="Refresh">
          {loading ? 'Loading…' : 'Refresh'}
        </button>
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Export — coming soon">
          Export
        </button>
      </div>

      {error && (
        <div className="panel" style={{ color: 'var(--error)', marginBottom: 20, padding: 16 }}>
          {error}
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        <KpiCard label="Scans" value={data ? fmt(data.scans) : '—'} />
        <KpiCard label="Documents" value={data ? fmt(data.docs) : '—'} />
        <KpiCard
          label="Certifiable rate"
          value={data?.certifiable_rate != null ? `${fmt(data.certifiable_rate, 1)}%` : '—'}
          sub={data ? `${fmt(data.certifiable)} of ${fmt(data.docs)} docs` : undefined}
          color={data?.certifiable_rate >= 80 ? '#3B6D11' : data?.certifiable_rate >= 50 ? '#854F0B' : data?.certifiable_rate != null ? '#A32D2D' : undefined}
        />
        <KpiCard
          label="Avg compliance score"
          value={data?.avg_score != null ? fmt(data.avg_score, 1) : '—'}
          sub={data?.avg_score != null ? '/ 100' : undefined}
          color={data?.avg_score >= 80 ? '#3B6D11' : data?.avg_score >= 50 ? '#854F0B' : data?.avg_score != null ? '#A32D2D' : undefined}
        />
        <KpiCard
          label="Trend"
          value={<DirectionBadge direction={trend.direction} />}
          sub={trend.delta != null ? `${trend.delta > 0 ? '+' : ''}${fmt(trend.delta, 1)} pts (${fmt(trend.span_days)}d)` : 'Insufficient data'}
        />
      </div>

      {/* Source filter pills + by-source breakdown */}
      {sources.length > 0 && (
        <div className="panel" style={{ marginBottom: 20, padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>By source</span>
            {sources.map((src) => (
              <button key={src} className="chip"
                      style={{ borderColor: source === src ? SOURCE_COLOR[src] : undefined,
                               color: source === src ? SOURCE_COLOR[src] : undefined }}
                      onClick={() => setSource(source === src ? null : src)}>
                {SOURCE_LABEL[src] || src}
              </button>
            ))}
          </div>
          <Bars
            items={barItems.map((it) => ({ ...it, value: it.value }))}
            cols="120px 1fr 44px"
            suffix="%"
            max={100}
          />
        </div>
      )}

      {/* Recent scans table */}
      {data?.recent_scans?.length > 0 && (
        <div className="panel" style={{ padding: '18px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 14 }}>
            Recent scans{data.scans > 20 ? ` (showing 20 of ${data.scans})` : ''}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Date', 'Source', 'Docs', 'Certifiable', 'Score', 'Owner'].map((h) => (
                    <th key={h} style={{ textAlign: 'left', padding: '4px 10px 8px 0',
                                        fontWeight: 600, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.recent_scans.map((s, i) => {
                  const pct = s.files && s.certifiable != null
                    ? Math.round(s.certifiable / s.files * 100) : null
                  return (
                    <tr key={s.id || i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{fmtDate(s.completed_at)}</td>
                      <td style={{ padding: '7px 10px 7px 0' }}>
                        <span style={{ fontSize: 11, color: SOURCE_COLOR[s.source] || 'var(--muted)' }}>
                          {SOURCE_LABEL[s.source] || s.source || '—'}
                        </span>
                      </td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums' }}>{fmt(s.files)}</td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums' }}>
                        {s.certifiable != null ? `${fmt(s.certifiable)} (${fmt(pct)}%)` : '—'}
                      </td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums' }}>
                        {s.avg_score != null ? fmt(s.avg_score, 1) : '—'}
                      </td>
                      <td style={{ padding: '7px 0 7px 0', color: 'var(--muted)', fontSize: 12, maxWidth: 180,
                                   overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.owner_email || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && data && data.scans === 0 && (
        <div className="panel" style={{ padding: 32, textAlign: 'center', color: 'var(--muted)' }}>
          No completed scans in this period.
        </div>
      )}
    </div>
  )
}
