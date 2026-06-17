// Simulated multi-source compliance estate — no backend, no real Drive. The whole
// app runs on this synthetic data so we can showcase the "art of the possible":
// agentic discovery, auto-tagging/classification, and unified cross-source compliance.

export const SIM = true // master switch

export const IDENTITY = { email: 'alex.rivera@northwind.com', name: 'Alex Rivera', org: 'Northwind Group' }

// connected content stores (made up) — the agent monitors each
export const SOURCES = [
  { id: 'gdrive', name: 'Google Drive', kind: 'google_drive', dept: 'Marketing', files: 1284, access: 'read-only', agent: 'continuous' },
  { id: 'sharepoint', name: 'SharePoint', kind: 'sharepoint', dept: 'HR & Legal', files: 3470, access: 'read-only', agent: 'continuous' },
  { id: 'confluence', name: 'Confluence', kind: 'confluence', dept: 'Engineering', files: 912, access: 'read-only', agent: 'daily' },
  { id: 'box', name: 'Box', kind: 'box', dept: 'Finance', files: 564, access: 'read-only', agent: 'continuous' },
  { id: 'cms', name: 'Website / CMS', kind: 'web', dept: 'Public site', files: 2106, access: 'read-only', agent: 'continuous' },
]
const SRC = Object.fromEntries(SOURCES.map((s) => [s.id, s]))

// agent-assigned tag taxonomy [bg, fg]
export const TAGS = {
  'public-facing': ['#E6F1FB', '#185FA5'], 'PII': ['#FCEBEB', '#A32D2D'],
  'legal-hold': ['#EEEDFE', '#3C3489'], 'high-traffic': ['#FAEEDA', '#854F0B'],
  'auto-fixable': ['#E1F5EE', '#0F6E56'], 'needs-review': ['#FAECE7', '#993C1D'],
  'remediation-queued': ['#FAEEDA', '#854F0B'], 'certified': ['#E7F0DC', '#3B6D11'],
  'policy': ['#F1EFE8', '#5F5E5A'], 'benefits': ['#F1EFE8', '#5F5E5A'],
  'financial': ['#F1EFE8', '#5F5E5A'], 'marketing': ['#F1EFE8', '#5F5E5A'],
  'contract': ['#F1EFE8', '#5F5E5A'], 'onboarding': ['#F1EFE8', '#5F5E5A'],
}

const iss = (rows) => rows.map(([ruleId, wcag, severity]) => ({ ruleId, rule_id: ruleId, wcag, severity }))
const ENG = { docx: '.net/office', pptx: '.net/office', xlsx: '.net/office', pdf: 'python/pdf', html: 'axe/web' }
function F(file, src, type, owner, status, score, tags, issues = []) {
  return {
    file, source: src, sourceName: SRC[src].name, dept: SRC[src].dept, type, owner,
    status, score, compliant: status === 'certifiable', skipped_rules: status === 'uncertain' ? 2 : 0,
    engine: ENG[type], tags, issues: iss(issues),
  }
}

export const CORPUS = [
  F('2026-benefits-guide.pdf', 'gdrive', 'pdf', 'HR Ops', 'issues', 58, ['public-facing', 'benefits', 'high-traffic', 'remediation-queued'],
    [['pdf.tagged', 'SC_1_3_1', 'SERIOUS'], ['pdf.document-language', 'SC_3_1_1', 'MODERATE'], ['pdf.alt-text', 'SC_1_1_1', 'CRITICAL']]),
  F('open-enrollment-deck.pptx', 'gdrive', 'pptx', 'Benefits', 'issues', 72, ['public-facing', 'benefits', 'auto-fixable'],
    [['PPTX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['PPTX-TITLE-001', 'SC_2_4_2', 'SERIOUS']]),
  F('brand-style-guide.pdf', 'gdrive', 'pdf', 'Marketing', 'certifiable', 100, ['marketing', 'certified', 'public-facing'], []),
  F('campaign-q3-landing.html', 'cms', 'html', 'Web Team', 'issues', 64, ['public-facing', 'high-traffic', 'remediation-queued'],
    [['WEB-CONTRAST-001', 'SC_1_4_3', 'SERIOUS'], ['WEB-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['WEB-LABEL-001', 'SC_1_3_1', 'MODERATE']]),
  F('careers-page.html', 'cms', 'html', 'Web Team', 'issues', 81, ['public-facing', 'high-traffic', 'auto-fixable'],
    [['WEB-ALT-001', 'SC_1_1_1', 'MODERATE'], ['WEB-LANG-001', 'SC_3_1_1', 'MINOR']]),
  F('homepage.html', 'cms', 'html', 'Web Team', 'certifiable', 100, ['public-facing', 'high-traffic', 'certified'], []),
  F('employee-handbook-2026.docx', 'sharepoint', 'docx', 'People Ops', 'issues', 49, ['policy', 'PII', 'legal-hold', 'remediation-queued'],
    [['DOCX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['DOCX-TITLE-001', 'SC_2_4_2', 'SERIOUS'], ['DOCX-TABLE-001', 'SC_1_3_1', 'SERIOUS'], ['DOCX-LANG-001', 'SC_3_1_1', 'SERIOUS']]),
  F('code-of-conduct.docx', 'sharepoint', 'docx', 'Legal', 'certifiable', 100, ['policy', 'legal-hold', 'certified'], []),
  F('data-privacy-policy.docx', 'sharepoint', 'docx', 'Legal', 'issues', 86, ['policy', 'PII', 'legal-hold', 'auto-fixable'],
    [['DOCX-LINK-001', 'SC_2_4_4', 'MODERATE']]),
  F('offer-letter-template.docx', 'sharepoint', 'docx', 'Recruiting', 'certifiable', 100, ['contract', 'onboarding', 'certified'], []),
  F('severance-agreement.pdf', 'sharepoint', 'pdf', 'Legal', 'uncertain', 90, ['contract', 'PII', 'legal-hold', 'needs-review'],
    [['pdf.tagged', 'SC_1_3_1', 'MODERATE']]),
  F('org-chart.pptx', 'sharepoint', 'pptx', 'People Ops', 'error', null, ['needs-review'], []),
  F('api-reference.html', 'confluence', 'html', 'Eng Docs', 'certifiable', 100, ['certified'], []),
  F('architecture-overview.pdf', 'confluence', 'pdf', 'Platform', 'issues', 77, ['auto-fixable'],
    [['pdf.tagged', 'SC_1_3_1', 'SERIOUS'], ['pdf.reading-order', 'SC_1_3_2', 'MODERATE']]),
  F('onboarding-runbook.docx', 'confluence', 'docx', 'Eng Ops', 'issues', 83, ['onboarding', 'auto-fixable'],
    [['DOCX-LINK-001', 'SC_2_4_4', 'MODERATE'], ['DOCX-HEAD-001', 'SC_1_3_1', 'MODERATE']]),
  F('q3-board-deck.pptx', 'box', 'pptx', 'Finance', 'issues', 68, ['financial', 'legal-hold', 'remediation-queued'],
    [['PPTX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['PPTX-TITLE-001', 'SC_2_4_2', 'SERIOUS']]),
  F('annual-report-2025.pdf', 'box', 'pdf', 'Finance', 'issues', 71, ['financial', 'public-facing', 'high-traffic'],
    [['pdf.tagged', 'SC_1_3_1', 'SERIOUS'], ['pdf.alt-text', 'SC_1_1_1', 'SERIOUS']]),
  F('budget-model.xlsx', 'box', 'xlsx', 'FP&A', 'uncertain', 92, ['financial', 'PII', 'needs-review'],
    [['XLSX-ALT-001', 'SC_1_1_1', 'MODERATE']]),
  F('expense-policy.pdf', 'box', 'pdf', 'Finance', 'certifiable', 100, ['policy', 'financial', 'certified'], []),
  F('vendor-contract-acme.pdf', 'box', 'pdf', 'Procurement', 'error', null, ['contract', 'legal-hold', 'needs-review'], []),
]

const now = () => new Date().toISOString()

function buildScan(sourceId, files) {
  const certifiable = files.filter((f) => f.status === 'certifiable').length
  const uncertain = files.filter((f) => f.status === 'uncertain').length
  const error = files.filter((f) => f.status === 'error').length
  const scored = files.filter((f) => f.score != null).map((f) => f.score)
  return {
    run: {
      id: 'sim-' + sourceId, source: sourceId, completed_at: now(),
      files: files.length, certifiable, uncertain, error,
      avg_score: scored.length ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : null,
      rubric_hash: 'e85fcf7e14f9040c',
    },
    files: files.map((f) => ({ ...f })),
  }
}

const SCANS = { 'scan-cur': buildScan('all', CORPUS) }
const JOBS = {}
let seq = 0

export function simStartScan(sourceId) {
  const jid = 'simjob' + (++seq)
  const files = sourceId === 'all' || sourceId === 'local' ? CORPUS : CORPUS.filter((f) => f.source === sourceId)
  const n = files.length
  const sid = 'scan-' + jid
  const set = (p) => { JOBS[jid] = { phase: 'queued', files_found: 0, files_done: 0, current: null, done: false, scan_id: null, ...JOBS[jid], ...p } }
  set({})
  const steps = [() => set({ phase: 'connecting' }), () => set({ phase: 'discovering', files_found: n })]
  // step ~2 files per tick so even a throttled tab finishes quickly, while still showing per-file motion
  for (let i = 0; i < n; i += 2) steps.push(() => set({ phase: 'reading', files_found: n, files_done: Math.min(i + 2, n), current: files[Math.min(i + 1, n - 1)].file }))
  steps.push(() => set({ phase: 'tagging', files_done: n, current: null }))
  steps.push(() => set({ phase: 'analysing', files_done: n, current: null }))
  steps.push(() => set({ phase: 'scoring', files_done: n, current: null }))
  steps.push(() => { SCANS[sid] = buildScan(sourceId, files); set({ phase: 'done', done: true, scan_id: sid, files_done: n }) })
  let k = 0
  const tick = () => { if (k < steps.length) { steps[k++](); setTimeout(tick, k <= 2 ? 300 : 130) } }
  setTimeout(tick, 200)
  return { job_id: jid }
}
export const simGetJob = (jid) => JOBS[jid]
export const simGetScan = (sid) => SCANS[sid] || SCANS['scan-cur']
const RULE_DEFS = {
  docx: [
    ['DOCX-ALT-001', 'Images need alt text', 'SC_1_1_1', 'CRITICAL'],
    ['DOCX-TITLE-001', 'Document has a title', 'SC_2_4_2', 'SERIOUS'],
    ['DOCX-TABLE-001', 'Tables have header rows', 'SC_1_3_1', 'SERIOUS'],
    ['DOCX-LANG-001', 'Document language is set', 'SC_3_1_1', 'SERIOUS'],
    ['DOCX-HEAD-001', 'Heading styles used', 'SC_1_3_1', 'MODERATE'],
    ['DOCX-LINK-001', 'Links have meaningful text', 'SC_2_4_4', 'MODERATE'],
  ],
  pptx: [
    ['PPTX-ALT-001', 'Images need alt text', 'SC_1_1_1', 'CRITICAL'],
    ['PPTX-TITLE-001', 'Slides have titles', 'SC_2_4_2', 'SERIOUS'],
    ['PPTX-ORDER-001', 'Reading order is set', 'SC_1_3_2', 'MODERATE'],
  ],
  xlsx: [
    ['XLSX-ALT-001', 'Charts/images need alt text', 'SC_1_1_1', 'MODERATE'],
    ['XLSX-SHEET-001', 'Sheets are named', 'SC_2_4_2', 'MINOR'],
    ['XLSX-HEADER-001', 'Tables have header rows', 'SC_1_3_1', 'MODERATE'],
  ],
  pdf: [
    ['pdf.tagged', 'PDF is tagged', 'SC_1_3_1', 'SERIOUS'],
    ['pdf.alt-text', 'Figures need alt text', 'SC_1_1_1', 'CRITICAL'],
    ['pdf.document-language', 'Document language is set', 'SC_3_1_1', 'MODERATE'],
    ['pdf.reading-order', 'Logical reading order', 'SC_1_3_2', 'MODERATE'],
    ['pdf.display-title', 'Title shown in title bar', 'SC_2_4_2', 'MINOR'],
  ],
  web: [
    ['WEB-ALT-001', 'Images need alt text', 'SC_1_1_1', 'CRITICAL'],
    ['WEB-CONTRAST-001', 'Text contrast ≥ 4.5:1', 'SC_1_4_3', 'SERIOUS'],
    ['WEB-LABEL-001', 'Form fields have labels', 'SC_1_3_1', 'MODERATE'],
    ['WEB-LANG-001', 'Page language is set', 'SC_3_1_1', 'MINOR'],
  ],
}
const AA = new Set(['SC_1_4_3'])
export function simRules() {
  const findings = {}
  CORPUS.forEach((f) => f.issues.forEach((i) => { findings[i.ruleId] = (findings[i.ruleId] || 0) + 1 }))
  const out = {}
  for (const [fmt, defs] of Object.entries(RULE_DEFS)) {
    out[fmt] = defs.map(([id, title, wcag, severity]) => ({ id, title, wcag, severity, level: AA.has(wcag) ? 'AA' : 'A', enabled: true, findings: findings[id] || 0 }))
  }
  return out
}

export const simListScans = () => {
  const cur = SCANS['scan-cur'].run
  return [
    { id: 'scan-cur', completed_at: cur.completed_at, source: 'all', avg_score: cur.avg_score, files: cur.files, certifiable: cur.certifiable, uncertain: cur.uncertain, error: cur.error },
    { id: 'h3', completed_at: '2026-06-10T09:00:00', avg_score: 79, files: 20 },
    { id: 'h2', completed_at: '2026-06-03T09:00:00', avg_score: 71, files: 19 },
    { id: 'h1', completed_at: '2026-05-27T09:00:00', avg_score: 64, files: 18 },
  ]
}
