import { useState } from 'react'

// ─── Data ─────────────────────────────────────────────────────────────────────
const GD = 'google'   // Google Drive
const SP = 'msft'     // SharePoint / Microsoft 365
const BE = 'shared'   // Shared backend work

const PROVIDER_META = {
  google: { label: 'Google Drive',      short: 'GDrive',  color: '#1F5FA8', bg: '#E2EDFB', icon: 'G' },
  msft:   { label: 'SharePoint / M365', short: 'SP',      color: '#3C3489', bg: '#EEEDFE', icon: 'M' },
  shared: { label: 'Shared Backend',    short: 'Backend', color: '#5F5E5A', bg: '#EFEDEA', icon: '⬡' },
}

const STATUS_META = {
  todo:     { label: 'To do',      dot: '○', color: '#5F5E5A' },
  partial:  { label: 'In design',  dot: '◐', color: '#854F0B' },
  done:     { label: 'Done',       dot: '●', color: '#3B6D11' },
}

const PHASES = [
  // ── Google Drive ────────────────────────────────────────────────────────────
  {
    id: 'GD-1', provider: GD, label: 'Auth & File Discovery', effort: '1–2 wk',
    desc: 'Wire OAuth 2.0 and list Drive files by MIME type — zero backend needed for this phase.',
    items: [
      { text: 'Google Cloud project + Drive API v3 enabled', status: 'partial' },
      { text: 'OAuth 2.0 web client (Google Identity Services sign-in button)', status: 'todo' },
      { text: 'Drive file listing by MIME type (docx, pdf, pptx, xlsx, html)', status: 'todo' },
      { text: 'File metadata sync: name, owner, modified date, size, shared status', status: 'todo' },
      { text: 'Token refresh + session management (localStorage → httpOnly cookie)', status: 'todo' },
      { text: 'Pagination for large Drive folders (pageToken handling)', status: 'todo' },
      { text: 'Shared Drive (Team Drive) enumeration', status: 'todo' },
    ],
  },
  {
    id: 'GD-2', provider: GD, label: 'File Processing', effort: '2–3 wk',
    desc: 'Download files and run the existing in-browser scan pipeline — core engine already ships.',
    items: [
      { text: 'Drive file download (API v3 /files/{id}?alt=media)', status: 'todo' },
      { text: 'Export Google Docs → DOCX via Drive export endpoint', status: 'todo' },
      { text: 'Export Google Sheets → XLSX, Slides → PPTX', status: 'todo' },
      { text: 'In-browser scan pipeline (DOCX/PDF/PPTX/HTML engines already built — zero delta)', status: 'done' },
      { text: 'Result persistence: Firestore / Postgres replaces localStorage', status: 'todo' },
      { text: 'Concurrent scan queue with back-pressure (Web Worker pool)', status: 'todo' },
    ],
  },
  {
    id: 'GD-3', provider: GD, label: 'Write-Back & Remediation', effort: '2–3 wk',
    desc: 'Upload remediated files back to Drive and preserve originals as a revision.',
    items: [
      { text: 'Upload remediated file to Drive (Files.update — same ID, new content)', status: 'todo' },
      { text: 'Preserve original via revision API before any overwrite', status: 'todo' },
      { text: 'Drive Comments API — attach remediation notes as in-document comments', status: 'todo' },
      { text: 'Permission-aware upload: check write scope before attempting (handle read-only shares)', status: 'todo' },
      { text: 'Shared Drive write support (requiresRoot delegation)', status: 'todo' },
    ],
  },
  {
    id: 'GD-4', provider: GD, label: 'Automation & Change Detection', effort: '2–3 wk',
    desc: 'Watch folders for new files and automatically trigger compliance scans.',
    items: [
      { text: 'Drive push notifications: channels.watch on target folders', status: 'todo' },
      { text: 'Webhook receiver endpoint (Cloud Run / Lambda)', status: 'todo' },
      { text: 'Delta tracking: only re-scan files whose modifiedTime changed', status: 'todo' },
      { text: 'Scheduled full sweep: Cloud Scheduler / cron (nightly)', status: 'todo' },
      { text: 'Compliance drift alert: email/Slack when previously-passing file regresses', status: 'todo' },
    ],
  },

  // ── SharePoint ───────────────────────────────────────────────────────────────
  {
    id: 'SP-1', provider: SP, label: 'Auth & File Discovery', effort: '1–2 wk',
    desc: 'Azure AD app registration + MSAL.js to enumerate SharePoint document libraries.',
    items: [
      { text: 'Azure AD app registration (single-tenant or multi-tenant)', status: 'partial' },
      { text: 'Microsoft Identity Platform (MSAL.js) sign-in with on-behalf-of flow', status: 'todo' },
      { text: 'Graph API scopes: Files.Read, Sites.Read.All, User.Read', status: 'todo' },
      { text: 'SharePoint site enumeration (Graph /sites?search=*)', status: 'todo' },
      { text: 'Document library listing (Graph /drives per site)', status: 'todo' },
      { text: 'File metadata sync: name, author, modified, content type, compliance label', status: 'todo' },
      { text: 'On-premises SharePoint routing (SPO vs. on-prem gateway)', status: 'todo' },
    ],
  },
  {
    id: 'SP-2', provider: SP, label: 'File Processing', effort: '2–3 wk',
    desc: 'Download files via Microsoft Graph and feed the existing scan pipeline.',
    items: [
      { text: 'SharePoint file download (Graph /drives/{id}/items/{id}/content)', status: 'todo' },
      { text: 'Large file handling: chunked download for files >4 MB (range requests)', status: 'todo' },
      { text: 'SharePoint Search API integration (find files by type / date range)', status: 'todo' },
      { text: 'In-browser scan pipeline (shared with GDrive — same engines)', status: 'done' },
      { text: 'Result persistence (shared Postgres/Firestore backend with GDrive results)', status: 'todo' },
    ],
  },
  {
    id: 'SP-3', provider: SP, label: 'Write-Back & Remediation', effort: '2–3 wk',
    desc: 'Upload remediated files back to SharePoint preserving version history.',
    items: [
      { text: 'Upload remediated file (Graph PUT /driveItem/content)', status: 'todo' },
      { text: 'SharePoint versioning: preserve original as prior version, not overwrite', status: 'todo' },
      { text: 'Metadata update: write compliance status to SharePoint list column', status: 'todo' },
      { text: 'Checkout / check-in workflow (Graph checkout + upload + checkin)', status: 'todo' },
      { text: 'Document Set support (multi-file compliance packages)', status: 'todo' },
    ],
  },
  {
    id: 'SP-4', provider: SP, label: 'Automation & Change Detection', effort: '2–3 wk',
    desc: 'Graph change notifications fire a scan on every new or modified document.',
    items: [
      { text: 'Graph API change notification subscriptions (webhook) on document libraries', status: 'todo' },
      { text: 'Subscription renewal (Graph subs expire after 30 days — auto-renew cron)', status: 'todo' },
      { text: 'Delta query for incremental sync (Graph /delta endpoint — avoid full re-list)', status: 'todo' },
      { text: 'Compliance drift alert: Adaptive Card to Teams channel when doc regresses', status: 'todo' },
    ],
  },

  // ── Shared Backend ───────────────────────────────────────────────────────────
  {
    id: 'BE-1', provider: BE, label: 'Backend API & Persistence', effort: '3–4 wk',
    desc: 'The one backend service that both GDrive and SharePoint integrations share.',
    items: [
      { text: 'REST API: Node.js/FastAPI — /v1/scan, /v1/results, /v1/estate', status: 'todo' },
      { text: 'PostgreSQL (hosted: Supabase/Neon) or Firestore — results + estate inventory', status: 'todo' },
      { text: 'JWT authentication middleware (validates GIS + MSAL tokens)', status: 'todo' },
      { text: 'Per-tenant data isolation (org_id column on all tables)', status: 'todo' },
      { text: 'Scan job queue: BullMQ / Celery / Cloud Tasks', status: 'todo' },
      { text: 'Rate limiting per provider (Drive: 1,000 req/100s; Graph: 10k req/10min)', status: 'todo' },
      { text: 'Retry + exponential back-off for 429 / 503 responses', status: 'todo' },
      { text: 'Health endpoint + structured logging (OpenTelemetry traces)', status: 'todo' },
    ],
  },
  {
    id: 'BE-2', provider: BE, label: 'Enterprise Hardening', effort: '3–4 wk',
    desc: 'SSO, RBAC, audit log, data residency — what enterprise procurement checklists require.',
    items: [
      { text: 'SSO / SAML 2.0 integration (Okta, Azure AD, Google Workspace IdP)', status: 'todo' },
      { text: 'Role-based access control: enforce the privilege matrix from Settings → Permissions', status: 'todo' },
      { text: 'Immutable audit log: who scanned what, when, result hash (Postgres append-only table)', status: 'todo' },
      { text: 'Data residency controls: EU (GCP europe-west1 / Azure North Europe) vs. US', status: 'todo' },
      { text: 'GDPR / data retention policy: auto-purge results older than N days', status: 'todo' },
      { text: 'Admin delegation: org admin can manage sub-team scopes without super-admin', status: 'todo' },
      { text: 'Multi-workspace support: one deployment, N tenants (schema-per-tenant or row-level)', status: 'todo' },
      { text: 'SLA dashboard + PagerDuty/OpsGenie alert on scan failure rate > 5%', status: 'todo' },
    ],
  },
]

const SUMMARY = {
  google: { total: 23, done: 1, weeks: '7–11' },
  msft:   { total: 21, done: 1, weeks: '7–11' },
  shared: { total: 16, done: 0, weeks: '6–8' },
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function IntegrationRoadmap() {
  const [expanded, setExpanded] = useState(new Set())
  const [provFilter, setProvFilter] = useState('all')

  const toggle = (id) => setExpanded(s => {
    const x = new Set(s); x.has(id) ? x.delete(id) : x.add(id); return x
  })

  const phases = provFilter === 'all' ? PHASES : PHASES.filter(p => p.provider === provFilter)

  const groups = [
    { key: GD, phases: phases.filter(p => p.provider === GD) },
    { key: SP, phases: phases.filter(p => p.provider === SP) },
    { key: BE, phases: phases.filter(p => p.provider === BE) },
  ].filter(g => g.phases.length > 0)

  return (
    <div style={{ marginTop: 40, borderTop: '2px solid var(--line)', paddingTop: 24 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 18 }}>
        <div>
          <b style={{ fontSize: 15 }}>Integration Readiness · Google Drive &amp; SharePoint</b>
          <div className="muted" style={{ marginTop: 4, fontSize: 13 }}>
            Comprehensive work-breakdown for connecting the platform to real file stores — grouped by provider and phase.
            Click any tile to expand its item checklist.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          {['all', GD, SP, BE].map(k => {
            const m = k === 'all' ? null : PROVIDER_META[k]
            return (
              <button key={k} className={provFilter === k ? 'fchip on' : 'fchip'} onClick={() => setProvFilter(k)}>
                {k === 'all' ? 'All providers' : m.short}
              </button>
            )
          })}
        </div>
      </div>

      {/* Provider summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 24 }}>
        {Object.entries(SUMMARY).map(([prov, s]) => {
          const m = PROVIDER_META[prov]
          return (
            <div key={prov} style={{ background: m.bg, border: '1px solid ' + m.color + '44', borderRadius: 8, padding: '12px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ width: 22, height: 22, borderRadius: 4, background: m.color, color: '#fff', fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{m.icon}</span>
                <b style={{ fontSize: 13, color: m.color }}>{m.label}</b>
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1 }}>{s.total - s.done}<span style={{ fontSize: 12, fontWeight: 400, color: 'var(--muted)', marginLeft: 4 }}>items remaining</span></div>
              {s.done > 0 && <div style={{ fontSize: 12, color: '#3B6D11', marginTop: 2 }}>✓ {s.done} already built</div>}
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{s.weeks} wk estimated</div>
            </div>
          )
        })}
        <div style={{ background: '#f8f8f8', border: '1px solid var(--line)', borderRadius: 8, padding: '12px 16px' }}>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>Quick wins (no backend)</div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Drive Picker + scan</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>OAuth + download + in-browser scan = real files in ~2–3 days. No server needed.</div>
          <div style={{ marginTop: 8, fontSize: 12 }}>
            <span style={{ background: '#E7F0DC', color: '#3B6D11', borderRadius: 3, padding: '1px 6px', fontWeight: 600 }}>GD-1 + GD-2</span>
          </div>
        </div>
      </div>

      {/* Phase tiles per provider */}
      {groups.map(({ key: prov, phases: grpPhases }) => {
        const m = PROVIDER_META[prov]
        return (
          <div key={prov} style={{ marginBottom: 28 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ width: 24, height: 24, borderRadius: 5, background: m.color, color: '#fff', fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{m.icon}</span>
              <b style={{ color: m.color, fontSize: 14 }}>{m.label}</b>
              <span className="muted" style={{ fontSize: 12 }}>· {grpPhases.length} phases</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
              {grpPhases.map(ph => {
                const isOpen = expanded.has(ph.id)
                const doneCount = ph.items.filter(i => i.status === 'done').length
                const totalCount = ph.items.length
                return (
                  <div key={ph.id}
                    style={{ border: '1px solid ' + m.color + (isOpen ? '99' : '33'), borderRadius: 8, overflow: 'hidden', background: isOpen ? m.bg : '#fafafa', transition: 'background 0.15s' }}>
                    <button
                      onClick={() => toggle(ph.id)}
                      aria-expanded={isOpen}
                      style={{ width: '100%', textAlign: 'left', padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: m.color, letterSpacing: '0.04em' }}>{ph.id}</span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 11, color: 'var(--muted)' }}>{ph.effort}</span>
                          <span aria-hidden="true" style={{ fontSize: 10, color: 'var(--muted)' }}>{isOpen ? '▲' : '▼'}</span>
                        </span>
                      </div>
                      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{ph.label}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ flex: 1, height: 4, background: '#e0e0e0', borderRadius: 2, overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: (doneCount / totalCount * 100) + '%', background: m.color, borderRadius: 2 }} />
                        </div>
                        <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{doneCount}/{totalCount} done</span>
                      </div>
                    </button>

                    {isOpen && (
                      <div style={{ borderTop: '1px solid ' + m.color + '33', padding: '10px 14px 14px' }}>
                        <p className="muted" style={{ fontSize: 12, marginBottom: 10, lineHeight: 1.5 }}>{ph.desc}</p>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {ph.items.map((item, n) => {
                            const sm = STATUS_META[item.status]
                            return (
                              <li key={n} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12 }}>
                                <span style={{ color: sm.color, flexShrink: 0, marginTop: 1, fontWeight: 700 }}>{sm.dot}</span>
                                <span style={{ lineHeight: 1.5, color: item.status === 'done' ? 'var(--muted)' : 'var(--ink)', textDecoration: item.status === 'done' ? 'line-through' : 'none' }}>{item.text}</span>
                              </li>
                            )
                          })}
                        </ul>
                        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 12 }}>
                          {Object.entries(STATUS_META).map(([k, sm]) => (
                            <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                              <span style={{ color: sm.color, fontWeight: 700 }}>{sm.dot}</span>{sm.label}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
