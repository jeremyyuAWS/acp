// Shared ontology engine — the rules/metadata model the Ontology Manager authors and
// that the live workflow (Remediate queue, Overview, file drawer) consumes. Pure JS, no
// React, so both the admin UI and the runtime read from one source of truth.
export const LS_KEY = 'mova_ontology_v1'

// ---- Field registry: what the rules engine can test, mapped to real corpus fields ----
export const exposureOf = (f) => (f.tags || []).includes('public-facing') ? 'public-facing' : (f.tags || []).includes('high-traffic') ? 'high-traffic' : 'internal'
export const sensitivityOf = (f) => (f.tags || []).includes('PII') ? 'PII' : (f.tags || []).includes('legal-hold') ? 'legal-hold' : 'none'
export const SEV_ORDER = ['none', 'MINOR', 'MODERATE', 'SERIOUS', 'CRITICAL']
export const worstSev = (f) => { const idx = (f.issues || []).map((i) => SEV_ORDER.indexOf(i.severity)).filter((x) => x >= 0); return idx.length ? SEV_ORDER[Math.max(...idx)] : 'none' }

export const FIELDS = {
  department: { label: 'Department', type: 'enum', get: (f) => f.department, ops: ['is', 'is not'] },
  repository: { label: 'Repository / source', type: 'enum', get: (f) => f.sourceName, ops: ['is', 'is not'] },
  type: { label: 'File type', type: 'enum', get: (f) => f.type, ops: ['is', 'is not'] },
  filename: { label: 'Filename', type: 'text', get: (f) => f.file, ops: ['contains', 'starts with', 'matches regex'] },
  tag: { label: 'Tag', type: 'enum', get: (f) => f.tags || [], ops: ['has', 'does not have'] },
  seniority: { label: 'Owner seniority', type: 'enum', get: (f) => f.seniority, ops: ['is', 'is not'] },
  exposure: { label: 'External exposure', type: 'enum', get: exposureOf, ops: ['is', 'is not'] },
  sensitivity: { label: 'Sensitivity', type: 'enum', get: sensitivityOf, ops: ['is', 'is not'] },
  ageDays: { label: 'Age · days since modified', type: 'number', get: (f) => f.ageDays, ops: ['older than', 'newer than'], unit: 'days' },
  views90d: { label: 'Usage · views / 90d', type: 'number', get: (f) => f.views90d, ops: ['greater than', 'less than'], unit: 'views' },
  sizeKB: { label: 'Size · KB', type: 'number', get: (f) => f.sizeKB, ops: ['greater than', 'less than'], unit: 'KB' },
  severity: { label: 'Worst WCAG finding', type: 'sev', get: worstSev, ops: ['is at least'] },
}
const uniq = (a) => [...new Set(a)].filter(Boolean).sort()
export const deriveOptions = (files) => ({
  department: uniq(files.map((f) => f.department)),
  repository: uniq(files.map((f) => f.sourceName)),
  type: uniq(files.map((f) => f.type)),
  tag: uniq(files.flatMap((f) => f.tags || [])),
  seniority: uniq(files.map((f) => f.seniority)),
  exposure: ['public-facing', 'high-traffic', 'internal'],
  sensitivity: ['PII', 'legal-hold', 'none'],
  severity: ['MINOR', 'MODERATE', 'SERIOUS', 'CRITICAL'],
})

export function evalCond(f, c) {
  const fd = FIELDS[c.field]; if (!fd) return false
  const v = fd.get(f); const val = c.value
  const s = (x) => String(x).toLowerCase()
  switch (c.op) {
    case 'is': return s(v) === s(val)
    case 'is not': return s(v) !== s(val)
    case 'contains': return s(v).includes(s(val))
    case 'starts with': return s(v).startsWith(s(val))
    case 'matches regex': try { return new RegExp(val, 'i').test(String(v)) } catch { return false }
    case 'has': return Array.isArray(v) && v.map(s).includes(s(val))
    case 'does not have': return Array.isArray(v) && !v.map(s).includes(s(val))
    case 'older than': return Number(v) > Number(val)
    case 'newer than': return Number(v) < Number(val)
    case 'greater than': return Number(v) > Number(val)
    case 'less than': return Number(v) < Number(val)
    case 'is at least': return SEV_ORDER.indexOf(v) >= SEV_ORDER.indexOf(val)
    default: return false
  }
}
export const evalRule = (f, rule) => { const cs = rule.conditions || []; return cs.length ? (rule.match === 'any' ? cs.some((c) => evalCond(f, c)) : cs.every((c) => evalCond(f, c))) : false }

// Weighted risk = WCAG severity × business criticality × exposure × regulatory × usage.
export const PRIORITY_W = { Critical: 4, High: 3, Medium: 2, Low: 1 }
export const SEV_W = { none: 0.5, MINOR: 1, MODERATE: 2, SERIOUS: 3, CRITICAL: 4 }
export function riskFactors(f, priority) {
  return {
    severity: SEV_W[worstSev(f)] || 0.5,
    criticality: PRIORITY_W[priority] || 2,
    exposure: { 'public-facing': 3, 'high-traffic': 2, internal: 1 }[exposureOf(f)],
    regulatory: sensitivityOf(f) === 'none' ? 1 : 3,
    usage: Math.max(1, Math.min(3, +(Math.log10((f.views90d || 1) + 1)).toFixed(2))),
  }
}
export const riskScore = (f, priority) => { const r = riskFactors(f, priority); return r.severity * r.criticality * r.exposure * r.regulatory * r.usage }

// ---- Natural-language → structured rule (deterministic; previews before activation) ----
export function parseNL(text, opts) {
  const t = ' ' + text.toLowerCase() + ' '
  const conditions = []
  opts.department.forEach((d) => { const key = d.toLowerCase().split(/[ &]/)[0]; if (key.length > 2 && t.includes(key)) conditions.push({ field: 'department', op: 'is', value: d }) })
  if (/\bexternal|public|customer-facing|customer facing|externally published|published\b/.test(t)) conditions.push({ field: 'exposure', op: 'is', value: 'public-facing' })
  ;['pdf', 'docx', 'pptx', 'xlsx', 'html'].forEach((ty) => { if (new RegExp(`\\b${ty}s?\\b`).test(t)) conditions.push({ field: 'type', op: 'is', value: ty }) })
  if (/\bpii|patient|phi|sensitive\b/.test(t)) conditions.push({ field: 'sensitivity', op: 'is', value: 'PII' })
  if (/\blegal hold|litigation\b/.test(t)) conditions.push({ field: 'sensitivity', op: 'is', value: 'legal-hold' })
  if (/\bexecutive|leadership|c-suite\b/.test(t)) conditions.push({ field: 'seniority', op: 'is', value: 'Executive' })
  const mm = t.match(/last (\d+) months?/); if (mm) conditions.push({ field: 'ageDays', op: 'newer than', value: String(+mm[1] * 30) })
  const my = t.match(/last (\d+) years?/); if (my) conditions.push({ field: 'ageDays', op: 'newer than', value: String(+my[1] * 365) })
  if (/\barchived|legacy|old\b/.test(t)) conditions.push({ field: 'ageDays', op: 'older than', value: '540' })
  const kw = t.match(/(?:titled|named|contain(?:ing|s)?|with) ["“]?([a-z0-9 _-]{3,})["”]?/); if (kw) conditions.push({ field: 'filename', op: 'contains', value: kw[1].trim().split(' ')[0] })
  const priority = /critical/.test(t) ? 'Critical' : /\bhigh\b/.test(t) ? 'High' : /\blow\b/.test(t) ? 'Low' : /\bmedium\b/.test(t) ? 'Medium' : (/prioriti|wcag first|first/.test(t) ? 'High' : null)
  const sla = (t.match(/within (\d+) days?/) || [])[1] || (/within a month|monthly|within 30 days/.test(t) ? '30' : null)
  const match = /\bor\b/.test(t) && !/\band\b/.test(t) ? 'any' : 'all'
  return { conditions, match, actions: { priority: priority || 'High', slaDays: sla ? +sla : null } }
}

export const PRI_COLOR = { Critical: ['#1F5FA8', '#E2EDFB'], High: ['#854F0B', '#FAEEDA'], Medium: ['#3C3489', '#EEEDFE'], Low: ['#5F5E5A', '#EFEDEA'] }
export const PRI_RANK = { Critical: 0, High: 1, Medium: 2, Low: 3 }
export const condText = (c) => `${FIELDS[c.field]?.label || c.field} ${c.op} “${c.value}”`

// ---- Runtime consumers: classify a file against the PUBLISHED ontology ----
// Returns the first matching rule's classification, or null. First rule wins.
export function classifyFile(f, pub) {
  if (!pub || !(pub.rules || []).length) return null
  const rule = pub.rules.find((r) => evalRule(f, r))
  if (!rule) return null
  const label = (pub.labels || []).find((l) => l.id === rule.actions?.label) || null
  return { rule: { id: rule.id, name: rule.name }, priority: rule.actions?.priority || null, sla: rule.actions?.slaDays || null, label, score: riskScore(f, rule.actions?.priority) }
}
// Annotate a corpus with the published ontology (adds `.ont`). Identity-safe: returns the
// same array untouched when nothing is published, so views degrade gracefully.
export function annotate(files, pub) {
  if (!pub || !(pub.rules || []).length) return files
  return files.map((f) => ({ ...f, ont: classifyFile(f, pub) }))
}
// ---- Seed ontology — an org's starting model, live by default so the demo shows the
// loop closed without a manual publish. The admin edits → drafts → re-publishes. ----
export const DEFAULT_LABELS = [
  { id: 'l1', name: 'Patient Consent Forms', color: '#1F5FA8' },
  { id: 'l2', name: 'High-Risk Legal Contracts', color: '#854F0B' },
  { id: 'l3', name: 'Board Minutes', color: '#3C3489' },
  { id: 'l4', name: 'Legacy HR Policies', color: '#5F5E5A' },
]
export const DEFAULT_RULES = [
  { id: 'r1', name: 'Customer-facing PDFs → Critical', match: 'all', conditions: [{ field: 'exposure', op: 'is', value: 'public-facing' }, { field: 'type', op: 'is', value: 'pdf' }], actions: { priority: 'Critical', slaDays: 30, label: 'l1' } },
  { id: 'r2', name: 'Anything owned by Legal → High', match: 'all', conditions: [{ field: 'department', op: 'is', value: 'Legal & Compliance' }], actions: { priority: 'High', slaDays: null, label: 'l2' } },
  { id: 'r3', name: 'Archived marketing → Low', match: 'all', conditions: [{ field: 'department', op: 'is', value: 'Communications' }, { field: 'ageDays', op: 'older than', value: '540' }], actions: { priority: 'Low', slaDays: null } },
]
export const DEFAULT_TAXONOMY = { name: 'Corporate Documents', children: [
  { name: 'Legal', children: [{ name: 'Contracts' }, { name: 'Litigation' }, { name: 'Compliance' }] },
  { name: 'Human Resources', children: [{ name: 'Benefits' }, { name: 'Recruiting' }, { name: 'Payroll' }] },
  { name: 'Product', children: [{ name: 'Specifications' }, { name: 'Manuals' }, { name: 'Release Notes' }] },
] }
export const DEFAULT_PUBLISHED = { version: 1, at: 'seeded', by: 'system', rules: DEFAULT_RULES, labels: DEFAULT_LABELS }

// The published snapshot the runtime classifies against. Falls back to the working rules
// (for state saved before snapshots existed) and finally to the seed, so the queue is
// always ontology-aware in the demo.
export function loadPublished() {
  try {
    const s = JSON.parse(localStorage.getItem(LS_KEY))
    if (!s) return DEFAULT_PUBLISHED
    return s.published || (s.rules ? { version: s.version || 1, at: s.publishedAt || 'seeded', by: 'admin', rules: s.rules, labels: s.labels } : DEFAULT_PUBLISHED)
  } catch { return DEFAULT_PUBLISHED }
}
