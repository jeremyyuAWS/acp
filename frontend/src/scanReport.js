// Scan-level (estate) report data-gathering + client-side aggregation. Keeps
// pdfReport.js a pure renderer: this module fetches the scan-scoped endpoints and
// rolls them up the SAME way the on-screen panels do — per-rule outcomes exactly
// like Transparency's RuleBreakdown, per-document routing via sim's
// recommendationSummary — then hands a fully-aggregated object to exportScanReport.
//
// Truthful metrics only: "conformant" is a real count of certifiable documents,
// never an estimated confidence %. Sections with no data are simply omitted.
import { getScanTraces, listHitlQueue, getConfig } from './api.js'
import { statusOf, statusCounts as countStatuses, avgScore as avgOf } from './docStatus.js'
import { WCAG } from './wcagCatalog.js'
import { recommendationSummary } from './sim.js'
import { fixSteps, hasGuidance, appName } from './remediationGuide.js'

// Normalize a filename to one of the native-app formats the remediation guide keys on.
const CHECKLIST_CAP = 60
const fmtOfName = (name) => {
  const ext = String(name || '').split('.').pop().toLowerCase()
  if (/^html?$/.test(ext)) return 'html'
  if (['docx', 'xlsx', 'pptx', 'pdf'].includes(ext)) return ext
  return null
}

const LEVEL_RANK = { A: 1, AA: 2, AAA: 3 }
// Same per-scan target the Assess runner persisted (Transparency reads this too).
const assessLevel = (scanId) => {
  try { return JSON.parse(sessionStorage.getItem(`acp-assess-${scanId || 'none'}`) || 'null')?.level || 'AA' } catch { return 'AA' }
}
const deptOf = (f) => f.department || f.dept || 'Unassigned'

const APPENDIX_CAP = 150

// Gather every scan-scoped input, aggregate, then render the PDF. Both the Overview
// toolbar and the Assess/Transparency RuleBreakdown header call this.
export async function generateScanReport({ scanId, files = [], org = 'your organisation' } = {}) {
  const [rowsRaw, hitlRaw, cfg] = await Promise.all([
    getScanTraces(scanId).catch(() => []),
    listHitlQueue(scanId).catch(() => []),
    getConfig().catch(() => null),
  ])
  const rows = Array.isArray(rowsRaw) ? rowsRaw : []
  const hitlItems = Array.isArray(hitlRaw) ? hitlRaw : []
  const targetLevel = assessLevel(scanId)

  // ── Per-rule rollup (identical to RuleBreakdown) ──────────────────────────
  const byRule = {}
  rows.forEach((r) => {
    const k = r.rule_id
    if (!byRule[k]) byRule[k] = { id: r.rule_id, name: r.plain_name || r.rule_name || r.rule_id, level: r.level, pass: 0, fail: 0, skip: 0, findings: 0 }
    const o = String(r.outcome || '').toUpperCase()
    if (o === 'PASS') byRule[k].pass++
    else if (o === 'FAIL') byRule[k].fail++
    else byRule[k].skip++
    byRule[k].findings += r.finding_count || 0
  })
  const rules = Object.values(byRule).sort((a, b) => b.fail - a.fail || a.id.localeCompare(b.id))
  const topFailing = rules.filter((r) => r.fail > 0).slice(0, 8)

  // In-scope / automated coverage counts (same scoping as RuleBreakdown's header).
  const targetRank = LEVEL_RANK[targetLevel] || 2
  const inScope = WCAG.filter((c) => c.docApplies !== false && (LEVEL_RANK[c.level] || 3) <= targetRank)
  const inScopeIds = new Set(inScope.map((c) => c.sc))
  const criteriaAutomated = rules.filter((r) => inScopeIds.has(r.id) || !WCAG.some((c) => c.sc === r.id)).length

  // ── Failure heatmap: top failing criteria × department (top depts by failures) ──
  const deptByFile = {}
  files.forEach((f) => { deptByFile[f.file] = deptOf(f) })
  const topIds = new Set(topFailing.map((r) => r.id))
  const cell = {}       // `${ruleId}::${dept}` -> count
  const deptFail = {}   // dept -> total failing rows across top criteria
  rows.forEach((r) => {
    if (String(r.outcome || '').toUpperCase() !== 'FAIL' || !topIds.has(r.rule_id)) return
    const dpt = deptByFile[r.file] || 'Unassigned'
    cell[`${r.rule_id}::${dpt}`] = (cell[`${r.rule_id}::${dpt}`] || 0) + 1
    deptFail[dpt] = (deptFail[dpt] || 0) + 1
  })
  const allFailDepts = Object.keys(deptFail).sort((a, b) => deptFail[b] - deptFail[a])
  const heatDepts = allFailDepts.slice(0, 6)
  const heatmap = {
    depts: heatDepts,
    moreDepts: Math.max(0, allFailDepts.length - heatDepts.length),
    rows: topFailing.map((r) => ({ id: r.id, name: r.name, cells: heatDepts.map((dpt) => cell[`${r.id}::${dpt}`] || 0) })),
  }

  // ── Manual remediation checklist: every FAILING criterion × the file format(s) it
  //    fails in, paired with the native-app menu path to fix it by hand on Mac and Windows.
  //    Driven entirely by real FAIL traces — no criterion appears that the scan did not flag.
  //    One row per (SC × format) so the instructions are exact for the app the user opens.
  const fileFmt = {}
  files.forEach((f) => { fileFmt[f.file] = fmtOfName(f.file) || (String(f.type || '').toLowerCase() || null) })
  const clMap = {}   // `${sc}::${fmt}` -> { sc, name, level, fmt, docs }
  rows.forEach((r) => {
    if (String(r.outcome || '').toUpperCase() !== 'FAIL') return
    const fmt = fileFmt[r.file]
    if (!fmt) return
    const sc = r.rule_id
    const key = `${sc}::${fmt}`
    if (!clMap[key]) clMap[key] = { sc, name: byRule[sc]?.name || r.plain_name || sc, level: byRule[sc]?.level || r.level || null, fmt, docs: 0 }
    clMap[key].docs++
  })
  const manualChecklist = Object.values(clMap)
    .map((it) => { const s = fixSteps(it.sc, it.fmt); return { ...it, app: appName(it.fmt), where: s.where, mac: s.mac, win: s.win, specific: hasGuidance(it.sc) } })
    // Most actionable first: criteria with a specific menu path, then most-affected, then by SC.
    .sort((a, b) => (b.specific - a.specific) || (b.docs - a.docs) || a.sc.localeCompare(b.sc))
  const checklistTruncated = manualChecklist.length > CHECKLIST_CAP

  // ── Document-level rollups ────────────────────────────────────────────────
  const totalFiles = files.length
  const conformantN = files.filter((f) => statusOf(f) === 'certifiable').length
  const conformantPct = totalFiles ? Math.round((conformantN / totalFiles) * 100) : 0
  const avgScore = avgOf(files)
  // The shared counter, not a hand-listed set of keys: this object was missing the unscored
  // bucket, and `statusCounts[statusOf(f)]++` on an absent key is NaN — so one unassessed
  // document turned a real count in the exported report into "NaN documents".
  const statusCounts = countStatuses(files)

  const groupBy = (fn) => files.reduce((m, f) => { const k = fn(f); if (k != null) (m[k] = m[k] || []).push(f); return m }, {})
  const rollup = (groups) => Object.entries(groups).map(([label, fs]) => ({
    label,
    docs: fs.length,
    avg: avgOf(fs),
    conformant: fs.filter((f) => statusOf(f) === 'certifiable').length,
    findings: fs.reduce((a, f) => a + (f.issues || []).length, 0),
  })).sort((a, b) => b.docs - a.docs)
  const byDept = rollup(groupBy(deptOf))
  const bySource = files.some((f) => f.sourceName) ? rollup(groupBy((f) => f.sourceName || 'Unknown')) : []

  // ── Remediation throughput (routing) — from sim's estate rollup ───────────
  const rec = recommendationSummary(files)
  const bucketN = (a) => rec.buckets.find((b) => b.action === a)?.n || 0
  const routing = {
    fixed: bucketN('auto'),
    humanRouted: bucketN('assisted') + bucketN('review') + bucketN('manual'),
    deferred: bucketN('archive') + bucketN('keep'),
    buckets: rec.buckets,
  }
  // No savedMin. It was manualMin - remediateMin, both invented per-finding constants, and
  // this object is an exported report model. autoPct is a real classification (which actions
  // the recommender chose), not a duration, so it stays.
  const effort = { remediateMin: rec.remediateMin, autoPct: rec.autoPct, remediableDocs: rec.remediableDocs }

  // ── HITL queue status ─────────────────────────────────────────────────────
  const hc = { pending: 0, approved: 0, rejected: 0, skipped: 0 }
  hitlItems.forEach((it) => { if (hc[it.status] != null) hc[it.status]++ })
  const hitl = { ...hc, total: hitlItems.length }

  // ── Appendix: worst-scoring first, capped ─────────────────────────────────
  const appendix = files
    .map((f) => ({ file: f.file, dept: deptOf(f), score: f.score ?? null, status: statusOf(f), action: f.rec?.action || null }))
    .sort((a, b) => (a.score == null ? 999 : a.score) - (b.score == null ? 999 : b.score))
    .slice(0, APPENDIX_CAP)

  const now = new Date()
  const { exportScanReport } = await import('./pdfReport.js')
  await exportScanReport({
    org,
    targetLevel,
    platformVersion: cfg?.version,
    date: now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
    timestamp: now.toLocaleString('en-US', { year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }),
    totalFiles, conformantN, conformantPct, avgScore, statusCounts,
    criteriaAutomated, inScopeCount: inScope.length,
    topFailing, heatmap, byDept, bySource, routing, effort, hitl, appendix,
    manualChecklist: manualChecklist.slice(0, CHECKLIST_CAP), checklistTruncated,
    checklistTotal: manualChecklist.length,
  })
}
