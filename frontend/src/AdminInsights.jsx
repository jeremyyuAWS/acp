import { lazy, Suspense, useEffect, useState, useCallback } from 'react'
import { getAdminAnalytics } from './api.js'

const AdminLiveTraffic = lazy(() => import('./AdminLiveTraffic.jsx'))

const SOURCE_COLOR = { drive: '#4285F4', sharepoint: '#0078D4', local: '#6E62C4', unknown: '#9a948f' }
const SOURCE_LABEL = { drive: 'Google Drive', sharepoint: 'SharePoint', local: 'Local', unknown: 'Unknown' }
// A scan lands in this table with completed_at set — but 'done' is not the only way to get
// there. cancel_scan and the lost-worker sweeper both stamp completed_at on a scan that never
// reached assessment, leaving files/certifiable at 0 for a reason that has nothing to do with
// what was found. A 0 on one of those statuses renders as the status word itself, so "0 docs"
// never has to be read as "assessed, found nothing."
// 'failed' is deliberately absent here, even though it's a real scan_runs status: every path
// that sets it (api/store.py's set_scan_status, the dead-letter sweep) touches status only,
// never completed_at, and this table's query (list_scans_admin -> list_scans) requires
// completed_at IS NOT NULL. A failed scan can therefore never reach this row-rendering code at
// all — an entry here would be a label that can never actually show, implying a case is handled
// that isn't. Making failed scans visible in Recent Scans is a real, separate product decision
// (stamping completed_at on failure, or a broader admin query) — not a rendering fix.
const SCAN_STATUS_LABEL = { cancelled: 'Cancelled', interrupted: 'Interrupted' }
const SCAN_STATUS_TITLE = {
  cancelled: 'Stopped before assessment finished — this reflects only what ran before the stop.',
  interrupted: 'The worker running this scan died mid-run — this reflects only what ran before it died.',
}

/** Docs/Certifiable read as a real zero on a normal completed scan, but on a scan that never
 * reached assessment a 0 means something else entirely — swap in the status word itself rather
 * than let both cases render identically. */
function statusOrCount(status, value, render) {
  const label = SCAN_STATUS_LABEL[status]
  if (label && !value) {
    return (
      <span style={{ color: 'var(--warn-fg)', fontStyle: 'italic', fontSize: 12.5 }} title={SCAN_STATUS_TITLE[status]}>
        {label}
      </span>
    )
  }
  return render()
}
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

function scoreColor(v) {
  if (v == null) return undefined
  return v >= 80 ? 'var(--success-fg)' : v >= 50 ? 'var(--warn-fg)' : 'var(--error-fg-strong)'
}

function LineChart({ points, height = 100, color = '#4285F4' }) {
  if (!points?.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--muted)', fontSize: 12 }}>
        No data for this period
      </div>
    )
  }
  const VW = 300, VH = height
  const pad = { t: 8, b: 8, l: 4, r: 4 }
  const vals = points.map(p => typeof p.certifiable_pct === 'number' ? p.certifiable_pct : 0)
  const maxV = Math.max(...vals, 1)
  const iH = VH - pad.t - pad.b
  const iW = VW - pad.l - pad.r
  const n = points.length

  const coords = vals.map((v, i) => [
    pad.l + (n > 1 ? i / (n - 1) : 0.5) * iW,
    VH - pad.b - (v / maxV) * iH,
  ])

  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${coords[n-1][0].toFixed(1)},${VH - pad.b} L${coords[0][0].toFixed(1)},${VH - pad.b} Z`
  const gradId = `lg-${color.replace('#', '')}`

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none"
         style={{ width: '100%', height, display: 'block' }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradId})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function KpiCard({ label, value, sub, color }) {
  return (
    <div className="panel" style={{ flex: '1 1 140px', minWidth: 120, padding: '16px 18px' }}>
      <div style={{ fontSize: 26, fontWeight: 700, color: color || 'var(--ink)',
                    fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 5 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function DirectionBadge({ direction }) {
  if (!direction || direction === 'insufficient') {
    return <span style={{ fontSize: 13, color: 'var(--muted)' }}>—</span>
  }
  const cfg = {
    improving: { label: 'Improving', color: '#639922' },
    declining:  { label: 'Declining',  color: 'var(--error-fg-strong)' },
    flat:       { label: 'Stable',     color: 'var(--warn-fg)' },
  }[direction]
  if (!cfg) return null
  return (
    <span style={{ fontSize: 13, fontWeight: 600, color: cfg.color,
                   background: cfg.color + '1a', borderRadius: 4, padding: '2px 8px' }}>
      {cfg.label}
    </span>
  )
}

function FunnelStage({ label, count, maxCount, color }) {
  const w = maxCount > 0 ? Math.max(count / maxCount * 100, 0) : 0
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || 'var(--ink)',
                    fontVariantNumeric: 'tabular-nums', marginBottom: 6 }}>
        {fmt(count)}
      </div>
      <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${w}%`, background: color || 'var(--ink)', borderRadius: 3,
                      transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

function PlaceholderPanel({ title, detail }) {
  return (
    <div className="panel" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{title}</div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: '24px 0' }}>
        {detail}
      </div>
    </div>
  )
}

export function AdminInsights({ me }) {
  const [showLive, setShowLive] = useState(false)
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

  const sources   = data ? Object.keys(data.by_source || {}) : []
  const trend     = data?.trend?.summary || {}
  const points    = data?.trend?.points  || []
  const totalDocs = data?.docs     ?? 0
  const certifiable  = data?.certifiable ?? 0
  const errorDocs = data?.error_docs ?? 0
  const assessed  = totalDocs - errorDocs

  const twoCol = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }

  return (
    <div style={{ maxWidth: 980, margin: '0 auto', padding: '24px 16px' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Scan Analytics</h1>
        <span style={{ fontSize: 13, color: 'var(--muted)' }}>Compare scans</span>
      </div>

      <div className="subtabs" role="tablist" aria-label="Admin analytics views" style={{ marginBottom: 16 }}>
        <button role="tab" aria-selected={!showLive} className={!showLive ? 'fchip on' : 'fchip'}
          onClick={() => setShowLive(false)}>Historical analytics</button>
        <button role="tab" aria-selected={showLive} className={showLive ? 'fchip on' : 'fchip'}
          onClick={() => setShowLive(true)}>Live Azure traffic</button>
      </div>

      {showLive && <Suspense fallback={<div className="panel" style={{ padding: 18, marginBottom: 20 }}>Loading live Azure traffic…</div>}>
        <AdminLiveTraffic />
      </Suspense>}

      {!showLive && <>

      {/* Control bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 24 }}>
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Scope filter — coming soon">
          Scope: All
        </button>
        <select className="chip" value={period} onChange={(e) => setPeriod(e.target.value)}
                style={{ border: 'none', background: 'transparent', cursor: 'pointer' }}>
          {PERIOD_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Period comparison — coming soon">
          Compare
        </button>
        <button className="chip" style={{ opacity: 0.5, cursor: 'default' }} disabled title="Rubric filter — coming soon">
          Rubric: All
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
        <div className="panel" style={{ color: 'var(--error)', marginBottom: 20, padding: 16 }}>{error}</div>
      )}

      {/* KPI row */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <KpiCard
          label="Unique files"
          value={data ? fmt(totalDocs) : '—'}
          sub={data ? `across ${fmt(data.scans)} scan${data.scans !== 1 ? 's' : ''}` : undefined}
        />
        <KpiCard
          label="Coverage"
          value={data?.certifiable_rate != null ? `${fmt(data.certifiable_rate, 1)}%` : '—'}
          sub={data ? `${fmt(certifiable)} of ${fmt(totalDocs)} certifiable` : undefined}
          color={scoreColor(data?.certifiable_rate)}
        />
        <KpiCard
          label="Open risk"
          value={data ? fmt(totalDocs - certifiable) : '—'}
          sub={data?.uncertain ? `${fmt(data.uncertain)} uncertain` : undefined}
          color={data && (totalDocs - certifiable) > 0 ? 'var(--error-fg-strong)' : undefined}
        />
        <KpiCard
          label="Avg score"
          value={data?.avg_score != null ? fmt(data.avg_score, 1) : '—'}
          sub={data?.avg_score != null ? '/ 100' : undefined}
          color={scoreColor(data?.avg_score)}
        />
        <KpiCard
          label="Trend"
          value={data ? <DirectionBadge direction={trend.direction} /> : '—'}
          sub={trend.delta != null
            ? `${trend.delta > 0 ? '+' : ''}${fmt(trend.delta, 1)} pts (${fmt(trend.span_days)}d)`
            : (data ? 'Insufficient data' : undefined)}
        />
        {data?.review_pending != null && (
          <KpiCard
            label="Review queue"
            value={fmt(data.review_pending)}
            color={data.review_pending > 0 ? 'var(--warn-fg)' : undefined}
          />
        )}
      </div>

      {/* Estate lifecycle funnel */}
      {data && totalDocs > 0 && (
        <div className="panel" style={{ marginBottom: 20, padding: '18px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 16 }}>Estate lifecycle</div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <FunnelStage label="Scanned" count={totalDocs} maxCount={totalDocs} color="#6E62C4" />
            <span style={{ fontSize: 16, color: 'var(--muted)', paddingBottom: 14, flexShrink: 0 }}>→</span>
            <FunnelStage label="Assessed" count={assessed} maxCount={totalDocs} color="#4285F4" />
            <span style={{ fontSize: 16, color: 'var(--muted)', paddingBottom: 14, flexShrink: 0 }}>→</span>
            <FunnelStage label="Certifiable" count={certifiable} maxCount={totalDocs} color="var(--success-fg)" />
            {(data?.review_pending ?? 0) > 0 && (
              <>
                <span style={{ fontSize: 16, color: 'var(--muted)', paddingBottom: 14, flexShrink: 0 }}>→</span>
                <FunnelStage label="In review" count={data.review_pending} maxCount={totalDocs} color="var(--warn-fg)" />
              </>
            )}
          </div>
        </div>
      )}

      {/* Coverage by source | Remediation placeholder */}
      <div style={{ ...twoCol, marginBottom: 20 }}>
        <div className="panel" style={{ padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>Coverage by source</span>
            {sources.map((src) => (
              <button key={src} className="chip"
                      style={{ fontSize: 11, padding: '2px 8px',
                               borderColor: source === src ? SOURCE_COLOR[src] : undefined,
                               color:       source === src ? SOURCE_COLOR[src] : undefined }}
                      onClick={() => setSource(source === src ? null : src)}>
                {SOURCE_LABEL[src] || src}
              </button>
            ))}
          </div>
          {sources.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Source', 'Docs', 'Certifiable', 'Rate'].map((h) => (
                    <th key={h} style={{ textAlign: h === 'Source' ? 'left' : 'right',
                                         padding: '4px 0 8px', fontWeight: 600, color: 'var(--muted)', fontSize: 12 }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sources.map((src) => {
                  const b = data.by_source[src]
                  const rate = b.docs ? Math.round(b.certifiable / b.docs * 100) : null
                  return (
                    <tr key={src} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '7px 0', fontWeight: 500 }}>
                        <span style={{ color: SOURCE_COLOR[src], marginRight: 6, fontSize: 10 }}>●</span>
                        {SOURCE_LABEL[src] || src}
                      </td>
                      <td style={{ padding: '7px 0', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmt(b.docs)}</td>
                      <td style={{ padding: '7px 0', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmt(b.certifiable)}</td>
                      <td style={{ padding: '7px 0', textAlign: 'right' }}>
                        <span style={{ color: scoreColor(rate), fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                          {rate != null ? `${rate}%` : '—'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--muted)', padding: '12px 0' }}>No data for this period.</div>
          )}
        </div>

        <PlaceholderPanel
          title="Remediation & verification"
          detail="Human review and fix tracking — connects to the HITL queue (coming soon)"
        />
      </div>

      {/* Document types | Backlog aging */}
      <div style={{ ...twoCol, marginBottom: 20 }}>
        <PlaceholderPanel
          title="Document types"
          detail="File type breakdown — requires per-file metadata from the scan (coming soon)"
        />
        <PlaceholderPanel
          title="Backlog aging"
          detail="Finding age distribution — requires per-finding timestamps (coming soon)"
        />
      </div>

      {/* Progress over time | Exceptions & data quality */}
      <div style={{ ...twoCol, marginBottom: 20 }}>
        <div className="panel" style={{ padding: '18px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>Progress over time</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>Certifiable rate per scan</div>
          <LineChart points={points} height={100} color="#4285F4" />
          {points.length > 1 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11,
                          color: 'var(--muted)', marginTop: 6 }}>
              <span>{fmtDate(points[0]?.at)}</span>
              <span>{fmtDate(points[points.length - 1]?.at)}</span>
            </div>
          )}
        </div>

        <div className="panel" style={{ padding: '18px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 14 }}>Exceptions &amp; data quality</div>
          {data ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {[
                { label: 'Processing errors', value: data.error_docs ?? 0, unit: 'docs',
                  color: (data.error_docs ?? 0) > 0 ? 'var(--error-fg-strong)' : undefined },
                { label: 'Scans with exceptions', value: data.scan_exceptions ?? 0, unit: 'scans',
                  color: (data.scan_exceptions ?? 0) > 0 ? 'var(--warn-fg)' : undefined },
                { label: 'Uncertain docs', value: data.uncertain ?? 0, unit: 'docs',
                  color: (data.uncertain ?? 0) > 0 ? 'var(--warn-fg)' : undefined },
              ].map(({ label, value, unit, color }, i, arr) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                          padding: '10px 0',
                                          borderBottom: i < arr.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ fontSize: 13, color: 'var(--muted)' }}>{label}</span>
                  <span style={{ fontSize: 16, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                                  color: color || 'var(--ink)' }}>
                    {fmt(value)}
                    <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)', marginLeft: 4 }}>{unit}</span>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>—</div>
          )}
        </div>
      </div>

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
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                        {fmtDate(s.completed_at)}
                      </td>
                      <td style={{ padding: '7px 10px 7px 0' }}>
                        <span style={{ fontSize: 11, color: SOURCE_COLOR[s.source] || 'var(--muted)' }}>
                          {SOURCE_LABEL[s.source] || s.source || '—'}
                        </span>
                      </td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums' }}>
                        {statusOrCount(s.status, s.files, () => fmt(s.files))}
                      </td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums' }}>
                        {statusOrCount(s.status, s.certifiable,
                          () => s.certifiable != null ? `${fmt(s.certifiable)} (${fmt(pct)}%)` : '—')}
                      </td>
                      <td style={{ padding: '7px 10px 7px 0', fontVariantNumeric: 'tabular-nums',
                                    color: scoreColor(s.avg_score) }}>
                        {s.avg_score != null ? fmt(s.avg_score, 1) : '—'}
                      </td>
                      <td style={{ padding: '7px 0 7px 0', color: 'var(--muted)', fontSize: 12,
                                    maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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

      </>}

    </div>
  )
}
