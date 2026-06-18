// Simulated multi-source compliance estate — no backend, no real Drive. Synthetic
// data so we can showcase agentic discovery, auto-tagging, and unified cross-source
// compliance. Modeled on a health-system org (UT Southwestern) with departments.

export const SIM = true
export const IDENTITY = { email: 'alex.rivera@utsouthwestern.edu', name: 'Alex Rivera', org: 'UT Southwestern' }

// connected content stores (made up) — the agent monitors each
export const SOURCES = [
  { id: 'gdrive', name: 'Google Drive', kind: 'google_drive', dept: 'Shared drives', files: 4120, access: 'read-only', agent: 'continuous' },
  { id: 'sharepoint', name: 'SharePoint', kind: 'sharepoint', dept: 'Intranet & policies', files: 9870, access: 'read-only', agent: 'continuous' },
  { id: 'confluence', name: 'Confluence', kind: 'confluence', dept: 'Clinical & eng docs', files: 2310, access: 'read-only', agent: 'daily' },
  { id: 'box', name: 'Box', kind: 'box', dept: 'Finance & contracts', files: 1640, access: 'read-only', agent: 'continuous' },
  { id: 'cms', name: 'Website / CMS', kind: 'web', dept: 'Public web', files: 5280, access: 'read-only', agent: 'continuous' },
]
const SRC = Object.fromEntries(SOURCES.map((s) => [s.id, s]))

export const TAGS = {
  'public-facing': ['#E6F1FB', '#185FA5'], 'PII': ['#FCEBEB', '#A32D2D'],
  'legal-hold': ['#EEEDFE', '#3C3489'], 'high-traffic': ['#FAEEDA', '#854F0B'],
  'auto-fixable': ['#E1F5EE', '#0F6E56'], 'needs-review': ['#FAECE7', '#993C1D'],
  'remediation-queued': ['#FAEEDA', '#854F0B'], 'certified': ['#E7F0DC', '#3B6D11'],
  'policy': ['#F1EFE8', '#5F5E5A'], 'financial': ['#F1EFE8', '#5F5E5A'], 'marketing': ['#F1EFE8', '#5F5E5A'],
}

export const DEPARTMENTS = [
  'Cardiology', 'Radiology', 'Oncology', 'Neurology', 'Patient Education',
  'Human Resources', 'Legal & Compliance', 'Research Administration', 'Finance', 'Communications',
]

const TYPES = ['pdf', 'docx', 'pptx', 'xlsx', 'html']
const ENG = { docx: '.net/office', pptx: '.net/office', xlsx: '.net/office', pdf: 'python/pdf', html: 'axe/web' }
const NAMES = {
  pdf: ['patient-handbook', 'care-pathway', 'discharge-instructions', 'clinical-guideline', 'consent-form', 'annual-summary'],
  docx: ['policy', 'procedure', 'protocol', 'sop', 'charter', 'guidelines'],
  pptx: ['town-hall', 'training-deck', 'grand-rounds', 'orientation'],
  xlsx: ['metrics-tracker', 'roster', 'budget', 'schedule'],
  html: ['intranet-page', 'public-page', 'faq', 'news-post'],
}
const SRC_FOR = { pdf: ['box', 'gdrive', 'sharepoint'], docx: ['sharepoint', 'confluence'], pptx: ['gdrive', 'box'], xlsx: ['box', 'sharepoint'], html: ['cms'] }
const ISS_POOL = {
  pdf: [['pdf.tagged', 'SC_1_3_1', 'SERIOUS'], ['pdf.alt-text', 'SC_1_1_1', 'CRITICAL'], ['pdf.document-language', 'SC_3_1_1', 'MODERATE'], ['pdf.reading-order', 'SC_1_3_2', 'MODERATE']],
  docx: [['DOCX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['DOCX-TITLE-001', 'SC_2_4_2', 'SERIOUS'], ['DOCX-TABLE-001', 'SC_1_3_1', 'SERIOUS'], ['DOCX-LINK-001', 'SC_2_4_4', 'MODERATE']],
  pptx: [['PPTX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['PPTX-TITLE-001', 'SC_2_4_2', 'SERIOUS'], ['PPTX-ORDER-001', 'SC_1_3_2', 'MODERATE']],
  xlsx: [['XLSX-ALT-001', 'SC_1_1_1', 'MODERATE'], ['XLSX-HEADER-001', 'SC_1_3_1', 'MODERATE'], ['XLSX-SHEET-001', 'SC_2_4_2', 'MINOR']],
  html: [['WEB-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['WEB-CONTRAST-001', 'SC_1_4_3', 'SERIOUS'], ['WEB-LABEL-001', 'SC_1_3_1', 'MODERATE'], ['WEB-LANG-001', 'SC_3_1_1', 'MINOR']],
}
const DEPT_TAGS = {
  'Patient Education': ['public-facing', 'high-traffic'], 'Communications': ['public-facing', 'high-traffic', 'marketing'],
  'Human Resources': ['PII', 'policy'], 'Legal & Compliance': ['legal-hold', 'policy'], 'Finance': ['financial'],
  'Research Administration': ['PII', 'policy'], 'Cardiology': ['PII'], 'Radiology': ['PII'], 'Oncology': ['PII'], 'Neurology': ['PII'],
}
const STATUS_CYCLE = ['issues', 'certifiable', 'issues', 'uncertain', 'issues', 'certifiable', 'issues', 'certifiable', 'issues', 'error']
const DEPT_COUNTS = [6, 5, 4, 7, 5, 4, 6, 4, 5, 4]
const slug = (d) => d.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const iss = (rows) => rows.map(([ruleId, wcag, severity]) => ({ ruleId, rule_id: ruleId, wcag, severity }))

function genCorpus() {
  const out = []; const seen = new Set(); let i = 0
  DEPARTMENTS.forEach((dept, di) => {
    const count = DEPT_COUNTS[di] || 5
    for (let j = 0; j < count; j++) {
      const type = TYPES[(di + j) % TYPES.length]
      const opts = SRC_FOR[type]; const source = opts[(di + j) % opts.length]
      const base = `${slug(dept)}-${NAMES[type][j % NAMES[type].length]}`
      let file = `${base}.${type}`; let k = 2
      while (seen.has(file)) { file = `${base}-${k++}.${type}` }
      seen.add(file)
      const status = STATUS_CYCLE[i % STATUS_CYCLE.length]
      const score = status === 'certifiable' ? 100 : status === 'error' ? null : status === 'uncertain' ? 88 + (i % 5) : 48 + ((i * 13) % 38)
      const pool = ISS_POOL[type]
      const issues = status === 'issues' ? iss(pool.slice(0, 2 + (i % 2) + (i % 3 === 0 ? 1 : 0))) : status === 'uncertain' ? iss(pool.slice(0, 1)) : []
      const stTag = status === 'certifiable' ? ['certified'] : status === 'uncertain' ? ['needs-review'] : status === 'issues' ? (i % 2 ? ['auto-fixable'] : ['remediation-queued']) : ['needs-review']
      const tags = [...new Set([...(DEPT_TAGS[dept] || []), ...stTag])].slice(0, 4)
      out.push({
        file, source, sourceName: SRC[source].name, department: dept, dept, type, owner: dept,
        status, score, compliant: status === 'certifiable', skipped_rules: status === 'uncertain' ? 2 : 0,
        engine: ENG[type], tags, issues,
      })
      i++
    }
  })
  return out
}
export const CORPUS = genCorpus()

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
  for (let i = 0; i < n; i += 3) steps.push(() => set({ phase: 'reading', files_found: n, files_done: Math.min(i + 3, n), current: files[Math.min(i + 1, n - 1)].file }))
  steps.push(() => set({ phase: 'tagging', files_done: n, current: null }))
  steps.push(() => set({ phase: 'analysing', files_done: n, current: null }))
  steps.push(() => set({ phase: 'scoring', files_done: n, current: null }))
  steps.push(() => { SCANS[sid] = buildScan(sourceId, files); set({ phase: 'done', done: true, scan_id: sid, files_done: n }) })
  let k = 0
  const tick = () => { if (k < steps.length) { steps[k++](); setTimeout(tick, k <= 2 ? 300 : 120) } }
  setTimeout(tick, 200)
  return { job_id: jid }
}
export const simGetJob = (jid) => JOBS[jid]
export const simGetScan = (sid) => SCANS[sid] || SCANS['scan-cur']
export const simListScans = () => {
  const cur = SCANS['scan-cur'].run
  return [
    { id: 'scan-cur', completed_at: cur.completed_at, source: 'all', avg_score: cur.avg_score, files: cur.files, certifiable: cur.certifiable, uncertain: cur.uncertain, error: cur.error },
    { id: 'h3', completed_at: '2026-06-10T09:00:00', avg_score: 74, files: 48 },
    { id: 'h2', completed_at: '2026-06-03T09:00:00', avg_score: 68, files: 46 },
    { id: 'h1', completed_at: '2026-05-27T09:00:00', avg_score: 61, files: 44 },
  ]
}

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
