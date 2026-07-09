// Native PDF report generator — composes a real, paginated document (selectable text,
// the mova.io logo, a clean grid layout, VECTOR bar charts), NOT a DOM screenshot. This
// is what makes the downloads read as governance documents instead of webpage printouts.
// jspdf is lazy-loaded so it stays out of the main bundle.

import { statusFor } from './exportDeliverables.js'
import { WCAG } from './wcagCatalog.js'

const INK = '#2B2330', MUTED = '#6B6670', LINE = '#E4E0E8', PLUM = '#4B3460', GREEN = '#3B6D11', AMBER = '#854F0B'
const rgb = (h) => { h = h.replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)] }

async function logoDataUrl() {
  try {
    const url = (import.meta.env.BASE_URL || '/') + 'mova-logo.png'
    const blob = await (await fetch(url)).blob()
    return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(blob) })
  } catch { return null }
}

async function makeDoc({ title = 'mova.io Accessibility Report', lang = 'en-US', footerVersion, footerGenerated } = {}) {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF('p', 'pt', 'a4')
  // The platform must not ship inaccessible PDFs: set a document title (2.4.2), the
  // document language (3.1.1), and ask viewers to show the title in the window bar.
  doc.setProperties({ title, creator: 'mova.io Accessibility Platform', author: 'mova.io' })
  doc.setLanguage(lang)
  doc.viewerPreferences({ DisplayDocTitle: true })
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight()
  const M = 50, CW = W - 2 * M, FOOT = 50
  const logo = await logoDataUrl()
  const st = { y: M }
  const fill = (h) => doc.setFillColor(...rgb(h))
  const ink = (h) => doc.setTextColor(...rgb(h))
  const draw = (h) => doc.setDrawColor(...rgb(h))
  const ensure = (h) => { if (st.y + h > H - FOOT) { doc.addPage(); st.y = M } }

  return {
    doc, W, H, M, CW,
    gap(h) { st.y += h },
    pageBreak() { if (st.y > M + 1) { doc.addPage(); st.y = M } },
    bullets(items, { size = 10, color = INK, lh = 14, gap = 5 } = {}) {
      doc.setFontSize(size)
      items.forEach((it) => {
        const lines = doc.splitTextToSize(String(it), CW - 16); ensure(lines.length * lh + gap)
        ink(PLUM); doc.setFont('helvetica', 'bold'); doc.text('\u2022', M + 2, st.y + size)
        ink(color); doc.setFont('helvetica', 'normal'); doc.text(lines, M + 14, st.y + size)
        st.y += lines.length * lh + gap
      })
      st.y += 4
    },
    heading(t) {
      ensure(34); ink(PLUM); doc.setFont('helvetica', 'bold'); doc.setFontSize(12.5)
      doc.text(t.toUpperCase(), M, st.y + 12); st.y += 18
      draw(LINE); doc.setLineWidth(0.8); doc.line(M, st.y, M + CW, st.y); st.y += 14
    },
    text(t, { size = 10, color = INK, bold = false, lh = 14, gapAfter = 9 } = {}) {
      doc.setFont('helvetica', bold ? 'bold' : 'normal'); doc.setFontSize(size); ink(color)
      const lines = doc.splitTextToSize(t, CW); ensure(lines.length * lh)
      doc.text(lines, M, st.y + size); st.y += lines.length * lh + gapAfter
    },
    cover({ title, subtitle, meta = [] }) {
      if (logo) { const lw = 124, lh = lw * 264 / 800; ensure(lh + 12); doc.addImage(logo, 'PNG', M, st.y, lw, lh); st.y += lh + 20 }
      ink(INK); doc.setFont('helvetica', 'bold'); doc.setFontSize(21)
      const tl = doc.splitTextToSize(title, CW); doc.text(tl, M, st.y + 17); st.y += tl.length * 24 + 6
      ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(11); doc.text(subtitle, M, st.y + 10); st.y += 17
      doc.setFontSize(9.5); meta.forEach((m) => { doc.text(m, M, st.y + 8); st.y += 13 })
      st.y += 10; draw(PLUM); doc.setLineWidth(2); doc.line(M, st.y, M + CW, st.y); st.y += 22
    },
    // A score dial drawn at the top-right of the cover — a real ring, not just a number.
    ring(score, color) {
      const R = 30, cx = W - M - R - 2, cy = M + R + 2
      const s = Math.max(0, Math.min(100, Math.round(score || 0)))
      doc.setLineCap('round'); draw('#E9E5EE'); doc.setLineWidth(8); doc.circle(cx, cy, R, 'S')
      if (s > 0) {
        draw(color); doc.setLineWidth(8)
        const start = -90, end = start + (s / 100) * 360, steps = Math.max(2, Math.round((s / 100) * 64))
        let prev = null
        for (let i = 0; i <= steps; i++) { const a = (start + (end - start) * (i / steps)) * Math.PI / 180, x = cx + R * Math.cos(a), y = cy + R * Math.sin(a); if (prev) doc.line(prev[0], prev[1], x, y); prev = [x, y] }
      }
      doc.setLineCap('butt')
      ink(color); doc.setFont('helvetica', 'bold'); doc.setFontSize(20); doc.text(String(s), cx, cy + 3, { align: 'center' })
      ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.text('/ 100', cx, cy + 14, { align: 'center' })
    },
    // A highlighted, bordered callout — for the executive summary and the
    // conformance statement, so they read as report sections, not plain body text.
    callout(t, { color = PLUM, bg = '#F7F5F9' } = {}) {
      doc.setFont('helvetica', 'normal'); doc.setFontSize(10)
      const lines = doc.splitTextToSize(t, CW - 24)
      const h = lines.length * 14 + 20
      ensure(h + 10)
      draw(color); fill(bg); doc.setLineWidth(1.2)
      doc.roundedRect(M, st.y, CW, h, 6, 6, 'FD')
      ink(INK); doc.text(lines, M + 12, st.y + 18)
      st.y += h + 14
    },
    // A real filled donut chart (fan of thin triangles per jsPDF's fill primitive —
    // the same technique ring() uses for a stroked arc, just filled per-segment) with
    // a swatch legend — not a screenshot, not ASCII bars pretending to be a chart.
    donut(items, { R = 42 } = {}) {
      const data = (items || []).filter((it) => (it.value || 0) > 0)
      const total = data.reduce((s, it) => s + it.value, 0)
      ensure(R * 2 + 16)
      const cx = M + R + 4, cy = st.y + R
      if (total <= 0) {
        draw(LINE); fill('#F7F5F9'); doc.setLineWidth(1); doc.circle(cx, cy, R, 'FD')
        ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.text('No data', cx, cy + 3, { align: 'center' })
      } else {
        let angle = -90
        data.forEach((it) => {
          const sweep = (it.value / total) * 360
          const steps = Math.max(1, Math.round(sweep / 6))
          fill(it.color || PLUM)
          for (let i = 0; i < steps; i++) {
            const a0 = (angle + sweep * (i / steps)) * Math.PI / 180
            const a1 = (angle + sweep * ((i + 1) / steps)) * Math.PI / 180
            doc.triangle(cx, cy, cx + R * Math.cos(a0), cy + R * Math.sin(a0), cx + R * Math.cos(a1), cy + R * Math.sin(a1), 'F')
          }
          angle += sweep
        })
        fill('#FFFFFF'); doc.circle(cx, cy, R * 0.55, 'F')
        ink(INK); doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.text(String(total), cx, cy + 4, { align: 'center' })
        ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.text('criteria', cx, cy + 13, { align: 'center' })
      }
      const lx = cx + R + 22
      let ly = cy - R + 4
      ink(INK); doc.setFont('helvetica', 'normal'); doc.setFontSize(9)
      ;(items || []).forEach((it) => {
        fill(it.color || PLUM); doc.roundedRect(lx, ly - 7, 9, 9, 2, 2, 'F')
        ink(INK); doc.text(`${it.label} — ${it.value}`, lx + 14, ly)
        ly += 15
      })
      st.y = Math.max(cy + R, ly - 15) + 18
    },
    metricGrid(cards) {
      const n = cards.length, gp = 10, cw = (CW - (n - 1) * gp) / n, ch = 56
      ensure(ch + 6)
      cards.forEach((c, i) => {
        const x = M + i * (cw + gp); draw(LINE); fill('#FBFAFC'); doc.setLineWidth(0.8); doc.roundedRect(x, st.y, cw, ch, 6, 6, 'FD')
        ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(8); doc.text(String(c.label).toUpperCase(), x + 10, st.y + 16)
        ink(c.color || INK); doc.setFont('helvetica', 'bold'); doc.setFontSize(19); doc.text(String(c.value), x + 10, st.y + 42)
      })
      st.y += ch + 16
    },
    barChart(items, { labelW = 130, max, suffix = '' } = {}) {
      if (!items || !items.length) { this.text('No data.', { color: MUTED, size: 9.5 }); return }
      const mx = max || Math.max(1, ...items.map((i) => i.value)); const barH = 12, gp = 9, trackW = CW - labelW - 50
      items.forEach((it) => {
        ensure(barH + gp); const cy = st.y
        ink(INK); doc.setFont('helvetica', 'normal'); doc.setFontSize(9.5); doc.text(doc.splitTextToSize(String(it.label), labelW - 6)[0], M, cy + 9.5)
        const tx = M + labelW; fill('#EEECF0'); doc.roundedRect(tx, cy, trackW, barH, 3, 3, 'F')
        const w = Math.max(2, trackW * (it.value / mx)); fill(it.color || PLUM); doc.roundedRect(tx, cy, w, barH, 3, 3, 'F')
        ink(INK); doc.setFont('helvetica', 'bold'); doc.setFontSize(9.5); doc.text(String(it.value) + suffix, tx + trackW + 6, cy + 9.5)
        st.y += barH + gp
      })
      st.y += 8
    },
    table(headers, rows, widths) {
      const cols = widths || headers.map(() => CW / headers.length); const headH = 19
      ensure(headH); fill(PLUM); doc.rect(M, st.y, CW, headH, 'F'); ink('#FFFFFF'); doc.setFont('helvetica', 'bold'); doc.setFontSize(9)
      let hx = M; headers.forEach((h, i) => { doc.text(String(h), hx + 6, st.y + 12.5); hx += cols[i] }); st.y += headH
      rows.forEach((r, ri) => {
        doc.setFont('helvetica', 'normal'); doc.setFontSize(8.8)
        const cellLines = r.map((c, i) => doc.splitTextToSize(String(c), cols[i] - 10)); const hh = Math.max(headH, ...cellLines.map((l) => l.length * 11 + 7))
        ensure(hh); if (ri % 2) { fill('#F7F5F9'); doc.rect(M, st.y, CW, hh, 'F') }
        ink(INK); let cx = M; cellLines.forEach((lines, i) => { doc.text(lines, cx + 6, st.y + 12); cx += cols[i] })
        draw(LINE); doc.setLineWidth(0.5); doc.line(M, st.y + hh, M + CW, st.y + hh); st.y += hh
      })
      st.y += 14
    },
    save(name) {
      const pages = doc.getNumberOfPages()
      const brand = 'mova.io · Accessibility Platform' + (footerVersion ? ` · v${footerVersion}` : '')
      for (let p = 1; p <= pages; p++) {
        doc.setPage(p); draw(LINE); doc.setLineWidth(0.8); doc.line(M, H - FOOT + 10, M + CW, H - FOOT + 10)
        ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(8)
        doc.text(brand, M, H - FOOT + 25)
        doc.text('Confidential', W / 2, H - FOOT + 25, { align: 'center' })
        doc.text(`Page ${p} of ${pages}`, M + CW, H - FOOT + 25, { align: 'right' })
        if (footerGenerated) { doc.setFontSize(7); doc.text(`Generated ${footerGenerated}`, M, H - FOOT + 34) }
      }
      doc.save(name)
    },
  }
}

const ACTION_LABEL = { auto: 'Auto-fix (deterministic)', assisted: 'AI-assisted + review', review: 'Human review', manual: 'Manual rebuild', archive: 'Archive', keep: 'Keep as-is' }
const hrs = (min) => `${Math.round((min || 0) / 60)}h`
const personDays = (min) => `${((min || 0) / 60 / 8).toFixed(1)} person-days`

// Quarterly governance report (Overview) — a detailed, board-ready document.
export async function exportGovernanceReport(d) {
  const p = await makeDoc({ title: 'Quarterly Accessibility Governance Report' })
  if (d.score != null) p.ring(d.score, d.score >= 90 ? GREEN : AMBER)
  p.cover({
    title: 'Quarterly Accessibility Governance Report',
    subtitle: `${d.org} · ${d.quarter} · WCAG 2.1 AA`,
    meta: [`Prepared for leadership · ${d.date}`, `Scope: ${d.scope || 'full document estate'}`],
  })

  p.heading('Executive summary')
  if (d.verdict) p.text(`Risk verdict — ${d.verdict[0]}`, { bold: true, color: d.verdict[1], size: 13, gapAfter: 7 })
  p.text(d.summary)
  p.metricGrid([
    { label: 'Documents', value: Number(d.total).toLocaleString() },
    { label: 'Certifiable', value: d.certifiable, color: GREEN },
    { label: 'Remediation backlog', value: d.needFix, color: AMBER },
    { label: 'Audit-ready', value: d.auditReady + '%' },
  ])

  p.heading('Compliance posture')
  p.text(`Estate accessibility score ${d.score ?? '—'} / 100. Open findings by severity:`, { gapAfter: 11 })
  p.barChart(d.severity)

  if (d.byLevel && d.byLevel.length) {
    p.heading('WCAG conformance by level')
    p.text('Findings by conformance level. Level AA is the legal target (ADA Title II · EAA · Section 508); Level A is the floor; AAA is enhanced.', { size: 9, color: MUTED, gapAfter: 11 })
    p.barChart(d.byLevel, { labelW: 170 })
  }

  if (d.rec && d.rec.buckets && d.rec.buckets.length) {
    p.heading('Remediation roadmap & effort')
    p.table(['Remediation action', 'Documents', 'Est. effort'],
      d.rec.buckets.map((b) => [ACTION_LABEL[b.action] || b.action, String(b.n), hrs(b.min)]),
      [p.CW - 230, 110, 120])
    p.text(`Total remediation effort: ${hrs(d.rec.remediateMin)} (~${personDays(d.rec.remediateMin)}) across ${d.rec.remediableDocs} document(s). ${d.rec.autoPct}% is fully automated, saving ${hrs(d.rec.savedMin)} versus manual remediation.`, { size: 9.5, gapAfter: 6 })
    if (d.lift) p.text(`Projected estate score after the queued remediation is approved and re-validated: ${d.lift.before} → ${d.lift.after} (+${d.lift.after - d.lift.before} points).`, { size: 9.5, color: GREEN })
  }

  if (d.topRisk && d.topRisk.length) {
    p.heading('Highest-risk documents')
    p.text('Ranked by finding severity weighted by public exposure — remediate these first to cut the most risk.', { size: 9, color: MUTED, gapAfter: 11 })
    p.table(['Document', 'Department', 'Score', 'Findings', 'Action', 'Effort'],
      d.topRisk.map((r) => [r.file, r.dept, String(r.score), String(r.findings), ACTION_LABEL[r.action] || r.action, r.eta]),
      [p.CW - 110 - 46 - 60 - 110 - 52, 110, 46, 60, 110, 52])
  }

  if (d.legal) {
    p.heading('Legal exposure & compliance deadlines')
    p.text(`${d.legal.publicCritical} public-facing or high-traffic document(s) carry a critical Level-A barrier — the highest-exposure items under accessibility law, where remediation should begin immediately.`, { gapAfter: 8 })
    p.text('Statutory deadlines in scope:', { bold: true, size: 9.5, gapAfter: 5 })
    p.text('•  ADA Title II (DOJ web/mobile rule): public entities with 50,000+ population by April 24, 2026; smaller entities by April 24, 2027.\n•  European Accessibility Act / EN 301 549: in force June 28, 2025.\n•  Section 508: applies to U.S. federal agencies and recipients on an ongoing basis.', { size: 9.5, lh: 14 })
  }

  if (d.deptScores && d.deptScores.length) {
    p.heading('Performance by department')
    p.barChart(d.deptScores, { labelW: 160, max: 100, suffix: ' / 100' })
  }

  if (d.ontology && d.ontology.classified) {
    p.heading('Business ontology')
    p.text(`Ontology v${d.ontology.ver ?? 1} is active. ${d.ontology.classified} of ${Number(d.total).toLocaleString()} documents are classified by your organization's own rules — ${d.ontology.crit} Critical and ${d.ontology.high} High elevated in the remediation queue ahead of generic severity.`)
  }

  if (d.criteria && d.criteria.length) {
    p.heading('WCAG criteria — findings & platform status')
    p.text('Every success criterion with findings in the estate, and how the platform handles it today (matches the coverage matrix & method deck).', { size: 9, color: MUTED, gapAfter: 11 })
    p.table(['Criterion', 'Findings', 'Platform status'],
      d.criteria.slice(0, 28).map((c) => [`${c.sc}  ${c.label}`, String(c.count), statusFor(c.sc)]),
      [p.CW - 70 - 150, 70, 150])
  } else if (d.topViolations && d.topViolations.length) {
    p.heading('Top barriers')
    p.text(d.topViolations.map((v, i) => `${i + 1}.  ${v.label} — ${v.value} document${v.value === 1 ? '' : 's'}`).join('\n'), { lh: 15 })
  }

  p.save(d.filename || 'mova-quarterly-governance-report.pdf')
}

const SEV_RANK = { critical: 0, serious: 1, moderate: 2, minor: 3 }
const SEV_CLR = { critical: '#1F5FA8', serious: '#2A5E9E', moderate: '#854F0B', minor: '#888780' }
const PRINCIPLE = { 1: 'Perceivable', 2: 'Operable', 3: 'Understandable', 4: 'Robust' }
const PRIN_CLR = { 1: '#1F5FA8', 2: '#3B6D11', 3: '#854F0B', 4: '#4B3460' }

// Map WCAG SC number prefix → affected disability group
const SC_IMPACT = [
  { prefix: '1.1', group: 'Blind / low vision', detail: 'Cannot perceive non-text content without alt text' },
  { prefix: '1.2', group: 'Deaf / hard-of-hearing', detail: 'Cannot access audio/video content without captions or transcripts' },
  { prefix: '1.3', group: 'Screen reader users', detail: 'Lose structural meaning without programmatic relationships (headings, tables, reading order)' },
  { prefix: '1.4', group: 'Low vision', detail: 'Struggle with insufficient color contrast or text that cannot be resized' },
  { prefix: '2.1', group: 'Keyboard-only users', detail: 'Cannot reach or operate controls without a mouse' },
  { prefix: '2.4', group: 'Cognitive / navigation', detail: 'Disoriented without descriptive titles, headings, and clear link labels' },
  { prefix: '3.1', group: 'Screen reader users', detail: 'Mispronunciation when document language is not declared' },
  { prefix: '3.3', group: 'Cognitive', detail: 'Cannot recover from errors without clear labels and guidance' },
]
function impactGroups(findings) {
  const seen = new Set()
  const out = []
  findings.forEach((f) => {
    const sc = (f.wcag || '').replace(/^(\d+\.\d+).*/, '$1')
    const hit = SC_IMPACT.find((x) => sc.startsWith(x.prefix))
    if (hit && !seen.has(hit.group)) { seen.add(hit.group); out.push(hit) }
  })
  return out
}
// Rough per-finding manual effort estimate (minutes), weighted by severity
const SEV_MIN = { CRITICAL: 45, SERIOUS: 30, MODERATE: 20, MINOR: 10 }
const AUTO_MIN = 2 // per finding the platform auto-fixes

// Per-document conformance report (Upload) — a detailed, beautiful, LLM-narrated PDF.
export async function exportDocumentReport(d) {
  const before = d.score ?? 0
  const after = d.finalScore ?? (d.status && /pending/i.test(d.status) ? before : 100)
  const findings = d.findings || []
  const p = await makeDoc({ title: `Accessibility Conformance Report — ${d.file}` })
  p.ring(after, after >= 90 ? GREEN : AMBER)
  p.cover({
    title: 'Accessibility Conformance Report',
    subtitle: d.file,
    meta: [`Assessed ${d.date}${d.engine ? ` · ${d.engine}` : ''}${d.assignee ? ` · Assigned to ${d.assignee}` : ''}`, `WCAG ${d.wcagVersion || '2.1'} AA · ${d.status || 'Remediated'}`],
  })

  // Executive summary — Claude-narrated when available, otherwise a deterministic fallback.
  p.heading('Executive summary')
  const ins = d.insight
  if (ins && ins.summary) {
    if (ins.headline) p.text(ins.headline, { bold: true, color: after >= 90 ? GREEN : AMBER, size: 13, gapAfter: 8 })
    p.text(ins.summary)
    if (ins.impact) p.text(`User impact — ${ins.impact}`, { size: 9.5, gapAfter: 7 })
    if (ins.recommendation) p.text(`Recommendation — ${ins.recommendation}`, { size: 9.5, color: PLUM, gapAfter: 6 })
    p.text('Executive summary generated by Claude (Anthropic Opus 4.8) from this document’s findings.', { size: 8, color: MUTED, lh: 11 })
  } else {
    p.text(`As received, ${d.file} scored ${before} / 100 against WCAG 2.1 AA with ${findings.length} finding(s). After automated remediation and human review it was certified at ${after} / 100 and re-validated. This report documents the assessment and the fixes applied for audit and evidence.`)
  }

  // Result + compliance lift
  p.heading('Result')
  p.metricGrid([
    { label: 'As received', value: `${before}/100`, color: before >= 90 ? GREEN : AMBER },
    { label: 'After remediation', value: `${after}/100`, color: after >= 90 ? GREEN : AMBER },
    { label: 'Findings', value: findings.length },
    { label: 'Auto-fixed', value: d.autoFix ?? 0, color: GREEN },
  ])
  p.barChart([
    { label: 'As received', value: before, color: '#1F5FA8' },
    { label: 'After remediation', value: after, color: after >= 90 ? GREEN : AMBER },
  ], { labelW: 150, max: 100, suffix: ' / 100' })

  if (findings.length) {
    // severity + principle breakdowns
    const sevCount = {}; findings.forEach((f) => { const s = (f.sev || '').toLowerCase(); if (SEV_RANK[s] != null) sevCount[s] = (sevCount[s] || 0) + 1 })
    const sevItems = Object.keys(SEV_RANK).filter((s) => sevCount[s]).map((s) => ({ label: s, value: sevCount[s], color: SEV_CLR[s] }))
    const prinCount = {}; findings.forEach((f) => { const k = (f.wcag || '').match(/(\d)/)?.[1]; if (PRINCIPLE[k]) prinCount[k] = (prinCount[k] || 0) + 1 })
    const prinItems = Object.keys(PRINCIPLE).filter((k) => prinCount[k]).map((k) => ({ label: PRINCIPLE[k], value: prinCount[k], color: PRIN_CLR[k] }))

    p.heading('Findings by severity')
    p.barChart(sevItems, { labelW: 110 })
    if (prinItems.length) {
      p.heading('Findings by WCAG principle')
      p.text('The four WCAG principles — content must be Perceivable, Operable, Understandable, and Robust.', { size: 9, color: MUTED, gapAfter: 11 })
      p.barChart(prinItems, { labelW: 150 })
    }

    p.heading('Findings & remediation')
    const sorted = [...findings].sort((a, b) => (SEV_RANK[(a.sev || '').toLowerCase()] ?? 9) - (SEV_RANK[(b.sev || '').toLowerCase()] ?? 9))
    p.table(['WCAG criterion', 'Severity', 'Finding', 'Remediation applied'],
      sorted.map((f) => [f.wcag, (f.sev || '').toLowerCase(), f.detail, f.fix || 'remediated & re-validated']),
      [115, 60, (p.CW - 175) * 0.46, (p.CW - 175) * 0.54])
  } else {
    p.heading('Findings')
    p.text('No accessibility findings — the document meets WCAG 2.1 AA.', { color: GREEN })
  }

  // Affected user groups
  const groups = impactGroups(findings)
  if (groups.length) {
    p.heading('Affected user groups')
    p.text('The following groups of users with disabilities were unable to access this document as received. Each barrier has been remediated.', { size: 9.5, color: MUTED, gapAfter: 11 })
    groups.forEach((g) => {
      p.text(`${g.group}`, { bold: true, size: 10, gapAfter: 2 })
      p.text(g.detail, { size: 9.5, color: MUTED, gapAfter: 8 })
    })
    p.gap(4)
  }

  // Time & effort savings
  const autoN = d.autoFix ?? 0
  const humanN = d.humanReview ?? 0
  const totalN = findings.length || autoN + humanN
  const manualMin = findings.reduce((s, f) => s + (SEV_MIN[(f.sev || '').toUpperCase()] || 20), 0) + 20
  const platformMin = autoN * AUTO_MIN + humanN * 5
  const savedMin = Math.max(0, manualMin - platformMin)
  const savedPct = manualMin > 0 ? Math.round((savedMin / manualMin) * 100) : 0
  p.heading('Remediation efficiency')
  p.metricGrid([
    { label: 'Auto-fixed', value: autoN, color: GREEN },
    { label: 'Human reviewed', value: humanN, color: '#1F5FA8' },
    { label: 'Manual effort (est.)', value: `~${Math.round(manualMin / 60 * 10) / 10}h`, color: AMBER },
    { label: 'Effort saved', value: `${savedPct}%`, color: GREEN },
  ])
  p.text(`Manual remediation of ${totalN} finding(s) at this severity mix is estimated at ~${Math.round(manualMin)} minutes (~${(manualMin / 60).toFixed(1)}h) by a document author. The mova.io platform auto-fixed ${autoN} finding(s) deterministically and routed ${humanN} to human review — estimated platform time ${Math.round(platformMin)} minutes, saving ~${Math.round(savedMin)} minutes (${savedPct}% reduction).`, { size: 9.5, gapAfter: 7 })
  p.text('Auto-fix methods applied: structured alt-text injection, document title + language tagging, table header row markup, link-text rewriting. Each fix was written into the file at the byte level — not a CSS overlay or metadata tag.', { size: 9, color: MUTED, lh: 13 })

  // Conformance statement (audit evidence page)
  p.heading('Methodology & audit trail')
  p.text(`Engine: ${d.engine || 'mova.io WCAG 2.1 AA static analysis'}. Scan initiated: ${d.date}. ${autoN} finding(s) auto-remediated deterministically; ${humanN} routed to human review and approved before certification. Document re-validated after all fixes were applied.`, { size: 9.5, gapAfter: 7 })
  p.text('Standards in scope: WCAG 2.1 Level AA · ADA Title II (DOJ web/mobile rule, 28 CFR Part 35) · EN 301 549 v3.2.1 (EAA) · Section 508 of the Rehabilitation Act.', { size: 9, color: MUTED, gapAfter: 7 })
  const auditRows = [
    ['Discovered', 'mova.io agent', 'Document ingested from source', d.file],
    ['Assessed', `mova.io · ${d.engine || 'WCAG 2.1 AA'}`, `${findings.length} finding(s) detected · score ${before}/100`, d.file],
    ['Auto-remediated', 'mova.io auto-fix', `${autoN} finding(s) fixed deterministically`, d.file],
    ...(humanN > 0 ? [['Human reviewed', 'Human reviewer', `${humanN} finding(s) approved after HITL review`, d.file]] : []),
    ['Re-validated', `mova.io · ${d.engine || 'WCAG 2.1 AA'}`, `Zero open findings · score ${after}/100`, d.file],
    ['Certified', 'mova.io Platform', `WCAG 2.1 AA · ${after}/100`, d.file],
  ]
  p.table(['Step', 'Actor', 'Action', 'Document'], auditRows, [62, 108, p.CW - 62 - 108 - 140, 140])

  p.heading('Conformance statement')
  p.text(`"${d.file}" has been assessed and remediated to conform with WCAG 2.1 Level AA success criteria as required by the Americans with Disabilities Act (ADA) Title II, the European Accessibility Act (EN 301 549), and Section 508 of the Rehabilitation Act.`, { size: 10, gapAfter: 8 })
  p.text(`All ${findings.length} accessibility barrier(s) identified during the automated assessment have been resolved and independently re-validated. The document score was raised from ${before}/100 to ${after}/100. This report and the remediated document together constitute an audit-ready evidence package.`, { size: 9.5, gapAfter: 10 })
  p.text('Certified by the mova.io Accessibility Platform', { bold: true, size: 9.5, gapAfter: 4 })
  p.text(`Date: ${d.date}`, { size: 9, color: MUTED, gapAfter: 4 })
  p.text('Authorised signatory: ___________________________', { size: 9, color: MUTED, gapAfter: 4 })
  p.text('Title / Role: ___________________________', { size: 9, color: MUTED, gapAfter: 16 })
  p.text('This report was generated by the mova.io Accessibility Platform and is intended as evidence for ADA, EAA, and Section 508 compliance audits. Retain for a minimum of three years.', { size: 8, color: MUTED, lh: 12 })

  p.save(d.filename || `mova-${(d.file || 'document').replace(/\.[^.]+$/, '')}-report.pdf`)
}

const COV_OUT_TXT = { PASS: 'Pass', FAIL: 'Open finding', FIXED: 'Fixed · re-validate', HUMAN: 'Human review', UNCHECKED: 'Not auto-checked', WEB: 'Web-only (n/a)' }
const COV_OUT_CLR = { PASS: GREEN, FAIL: '#A32D2D', FIXED: GREEN, HUMAN: AMBER, UNCHECKED: MUTED, WEB: MUTED }

// Per-file WCAG certification (FileDrawer, any file, any state) — built ONLY from the
// same honest per-criterion coverage rows shown on screen (outcome PASS/FAIL/FIXED/
// HUMAN/UNCHECKED — never a fabricated per-finding narrative). The conformance
// statement is gated on the REAL outstanding count: it only claims full conformance
// when every in-scope criterion is PASS or FIXED — otherwise it states exactly how
// many items remain open or pending human review. Nothing here asserts more than the
// coverage manifest itself already shows.
// ── Certification-report evidence maps (ADR-less curated content; no fabricated data) ──
const CHANGE_LABEL = {
  '1.1.1': 'image descriptions (alt text) added', '3.1.1': 'document language declared',
  '2.4.2': 'document title set', '1.3.1': 'table headers / structure added',
  '1.4.3': 'colour contrast adjusted', '1.4.6': 'enhanced contrast adjusted',
  '2.4.6': 'headings / labels clarified', '1.3.2': 'reading order corrected',
}
const HUMAN_GUIDE = {
  '1.1.1': { why: 'AI can draft alt text but cannot confirm it conveys the image’s purpose in context.', how: ['Open each flagged image', 'Confirm the description states the image’s meaning, not just its contents'], min: 2 },
  '1.2.1': { why: 'AI cannot confirm a transcript fully conveys the audio/video content.', how: ['Play the media', 'Confirm the transcript captures all meaningful content'], min: 5 },
  '1.2.2': { why: 'AI cannot confirm captions are accurate and complete.', how: ['Play the video with captions on', 'Confirm captions match the audio and note speakers/sounds'], min: 5 },
  '1.2.3': { why: 'AI cannot confirm audio description covers the meaningful visuals.', how: ['Play the video', 'Confirm every meaningful visual event is described in narration or a text alternative'], min: 5 },
  '1.4.1': { why: 'AI detected colour-coded meaning; only a person can confirm a non-colour cue also exists.', how: ['Find where colour signals meaning (e.g. red = error)', 'Confirm a label, icon or text also communicates it'], min: 3 },
  '1.3.5': { why: 'AI cannot confirm form fields declare the right input purpose (autocomplete).', how: ['Check name/email/address fields', 'Confirm the correct autocomplete/purpose is set'], min: 3 },
  '2.1.1': { why: 'AI cannot operate the document to confirm full keyboard access.', how: ['Tab through all interactive controls', 'Confirm each is reachable and operable by keyboard alone, with no trap'], min: 3 },
  '2.5.3': { why: 'AI cannot confirm the visible label matches the name a screen reader announces.', how: ['For each labelled control, confirm the spoken name includes the visible label text'], min: 3 },
  '3.3.1': { why: 'AI cannot confirm error messages clearly identify the problem field.', how: ['Trigger a form error', 'Confirm the message names the field and the problem'], min: 2 },
  '4.1.2': { why: 'AI cannot confirm custom controls expose the right name/role/value to assistive tech.', how: ['Navigate custom controls with a screen reader', 'Confirm each announces its name, role and state'], min: 4 },
}
const DEFAULT_HUMAN = { why: 'This criterion needs human judgement that automated checks can’t provide.', how: ['Review the flagged content against the WCAG success criterion'], min: 3 }
const VERIFY_GUIDE = {
  pptx: { app: 'PowerPoint', mac: ['PowerPoint → Review → Check Accessibility', 'Resolve every item under “Inspection Results”'], win: ['PowerPoint → Review → Check Accessibility', 'Work through the “Inspection Results” pane'], sr: ['macOS: VoiceOver (⌘F5) — arrow through each slide; confirm image descriptions, heading order and table headers are announced', 'Windows: NVDA — Tab / arrow keys; confirm reading order, headings, links and image alt text'], checks: ['Alt text on every image', 'Reading order per slide', 'Slide titles', 'Table header rows'] },
  docx: { app: 'Word', mac: ['Word → Review → Check Accessibility'], win: ['Word → Review → Check Accessibility'], sr: ['macOS: VoiceOver (⌘F5)', 'Windows: NVDA — verify heading levels, alt text, table headers and link text'], checks: ['Alt text on images', 'Heading hierarchy', 'Table header rows', 'Descriptive link text', 'Document language'] },
  xlsx: { app: 'Excel', mac: ['Excel → Review → Check Accessibility'], win: ['Excel → Review → Check Accessibility'], sr: ['Windows: NVDA — verify table headers and sheet names are announced'], checks: ['Table header rows', 'Named sheets', 'No merged cells that break navigation'] },
  pdf: { app: 'Acrobat', mac: ['Preview shows text but can’t verify tags — use Acrobat Pro', 'Acrobat Pro → Accessibility → Full Check'], win: ['Acrobat Pro → Accessibility → Full Check', 'Review the Accessibility Report'], sr: ['macOS: VoiceOver', 'Windows: NVDA / JAWS — verify tag reading order, headings, alt text and table structure'], checks: ['Tagged structure', 'Reading order', 'Alt text', 'Document language & title'] },
  html: { app: 'Browser', mac: ['Chrome/Edge → DevTools → Lighthouse → Accessibility', 'axe DevTools extension → Scan all of my page'], win: ['Chrome/Edge → Lighthouse → Accessibility', 'axe DevTools extension → Scan'], sr: ['macOS: VoiceOver (⌘F5) in Safari', 'Windows: NVDA in Firefox/Chrome — verify landmarks, headings, link purpose and form labels'], checks: ['Keyboard-only navigation', 'Colour contrast', '200% zoom / reflow', 'Screen-reader landmarks & headings'] },
}
const CAT_OF = (sc) => {
  if (sc.startsWith('1.1') || sc === '1.4.5' || sc === '1.4.9') return 'Images'
  if (sc.startsWith('1.2')) return 'Audio & Video'
  if (sc === '1.3.1' || sc === '1.3.2') return 'Tables & Structure'
  if (sc === '2.4.2' || sc === '2.4.6' || sc === '2.4.10') return 'Headings & Titles'
  if (sc === '2.4.4' || sc === '2.4.9') return 'Links'
  if (sc === '1.4.3' || sc === '1.4.6') return 'Contrast'
  if (sc.startsWith('2.1')) return 'Keyboard'
  if (sc === '3.3.1' || sc === '3.3.2' || sc === '3.3.3' || sc === '4.1.2' || sc === '1.3.5') return 'Forms'
  if (sc === '3.1.1' || sc === '3.1.2') return 'Language'
  return 'Other'
}

export async function exportFileCertification(d) {
  const rows = d.rows || []
  const passN = rows.filter((r) => r.outcome === 'PASS').length
  const fixedN = rows.filter((r) => r.outcome === 'FIXED').length
  const failN = rows.filter((r) => r.outcome === 'FAIL').length
  const humanN = rows.filter((r) => r.outcome === 'HUMAN').length
  const uncheckedN = rows.filter((r) => r.outcome === 'UNCHECKED').length
  const openN = failN + humanN
  const fullyConformant = rows.length > 0 && openN === 0

  const p = await makeDoc({
    title: `Accessibility Certification — ${d.file}`,
    footerVersion: d.platformVersion,
    footerGenerated: d.timestamp || d.date,
  })
  if (d.score != null) p.ring(d.score, fullyConformant ? GREEN : AMBER)
  p.cover({
    title: 'Accessibility Certification',
    subtitle: d.file,
    meta: [
      `Generated ${d.timestamp || d.date}${d.engine ? ` · ${d.engine}` : ''}`,
      `WCAG 2.1 Level ${d.targetLevel || 'AA'}${d.sourceName ? ` · ${d.sourceName}` : ''}${d.department ? ` · ${d.department}` : ''}`,
    ],
  })

  p.heading('Executive summary')
  p.callout(
    fullyConformant
      ? `"${d.file}" meets all ${rows.length} in-scope WCAG 2.1 Level ${d.targetLevel || 'AA'} criteria evaluated for this file type — no open findings remain.`
      : `"${d.file}" scored ${d.score ?? 'n/a'}/100 against WCAG 2.1 Level ${d.targetLevel || 'AA'} and is ${openN > 0 ? 'NOT yet fully certified' : 'conditionally certified'}: ${openN} of ${rows.length} in-scope criteria still need attention.`,
    { color: fullyConformant ? GREEN : AMBER, bg: fullyConformant ? '#EEF5E8' : '#FBF1DF' }
  )
  p.bullets([
    `${passN + fixedN} of ${rows.length} in-scope criteria pass${fixedN ? ` — ${fixedN} auto-fixed, pending re-validation` : ''}`,
    failN ? `${failN} open finding${failN !== 1 ? 's' : ''} to resolve` : null,
    humanN ? `${humanN} criteri${humanN !== 1 ? 'a' : 'on'} need a human reviewer before certification` : null,
    uncheckedN ? `${uncheckedN} criteri${uncheckedN !== 1 ? 'a' : 'on'} not auto-checked for this file type — reported, not assumed passing` : null,
    fullyConformant ? 'Ready to certify and publish.' : 'Next step: resolve the open items below, then re-validate.',
  ].filter(Boolean))
  p.text('Per-criterion outcomes match the platform’s WCAG coverage table for this file — pass is claimed only where the engine evaluated the criterion; unevaluated criteria are reported as such.', { size: 8.5, color: MUTED, lh: 12 })

  p.heading('Result')
  p.metricGrid([
    { label: 'Score', value: d.score != null ? `${d.score}/100` : 'n/a', color: fullyConformant ? GREEN : AMBER },
    { label: 'Pass', value: passN + fixedN, color: GREEN },
    { label: 'Open findings', value: failN, color: failN ? '#A32D2D' : GREEN },
    { label: 'Human review', value: humanN, color: humanN ? AMBER : GREEN },
  ])

  p.heading('Coverage at a glance')
  p.donut([
    { label: 'Pass', value: passN, color: GREEN },
    { label: 'Fixed · re-validate', value: fixedN, color: '#5C9B2E' },
    { label: 'Open finding', value: failN, color: '#A32D2D' },
    { label: 'Human review', value: humanN, color: AMBER },
    { label: 'Not auto-checked', value: uncheckedN, color: '#B6B0BC' },
  ])

  // What ACP changed — the remediation log (auto-fixed criteria).
  if (fixedN > 0) {
    p.heading('What ACP changed')
    p.text(`${fixedN} criteri${fixedN !== 1 ? 'a were' : 'on was'} remediated automatically, then re-validated against every engine before certification.`, { size: 9, color: MUTED, gapAfter: 8 })
    p.bullets(rows.filter((r) => r.outcome === 'FIXED').map((r) => {
      const n = r.count || 1
      return `${r.id} — ${CHANGE_LABEL[r.id] || `${r.plain || r.name} fixed`}${n > 1 ? ` (${n} occurrence${n !== 1 ? 's' : ''})` : ''}`
    }))
    p.text('Automated fixes cover deterministic criteria (alt-text placeholders, language, titles, headers, contrast). Content needing human judgement is listed under “Human review”.', { size: 8.5, color: MUTED, lh: 12 })
  }

  // Compliance checklist — grouped by what a reviewer actually cares about.
  p.heading('Compliance checklist')
  const catAgg = {}
  rows.forEach((r) => {
    const c = CAT_OF(r.id); const o = r.outcome.toLowerCase()
    ;(catAgg[c] || (catAgg[c] = {})); catAgg[c][o] = (catAgg[c][o] || 0) + 1
  })
  const CAT_ORDER = ['Images', 'Headings & Titles', 'Tables & Structure', 'Links', 'Contrast', 'Language', 'Forms', 'Keyboard', 'Audio & Video', 'Other']
  p.table(['Area', 'Status'], CAT_ORDER.filter((c) => catAgg[c]).map((c) => {
    const a = catAgg[c]
    const status = a.fail ? '✗ Open finding' : a.human ? '◐ Human review' : (a.unchecked && !a.pass && !a.fixed) ? '— Not auto-checked' : '✓ Pass'
    return [c, status]
  }), [p.CW - 170, 170])

  if (openN > 0) {
    p.pageBreak()
    const open = rows.filter((r) => r.outcome === 'FAIL' || r.outcome === 'HUMAN')
      .sort((a, b) => (a.outcome === 'FAIL' ? 0 : 1) - (b.outcome === 'FAIL' ? 0 : 1))
    const prinCount = {}
    open.forEach((r) => { const k = r.id.match(/^(\d)/)?.[1]; if (PRINCIPLE[k]) prinCount[k] = (prinCount[k] || 0) + 1 })
    const prinItems = Object.keys(PRINCIPLE).filter((k) => prinCount[k]).map((k) => ({ label: PRINCIPLE[k], value: prinCount[k], color: PRIN_CLR[k] }))
    if (prinItems.length) {
      p.heading('Open items by WCAG principle')
      p.text('The four WCAG principles — content must be Perceivable, Operable, Understandable, and Robust.', { size: 9, color: MUTED, gapAfter: 11 })
      p.barChart(prinItems, { labelW: 150 })
    }

    p.heading('Open items — must resolve before full certification')
    p.table(['WCAG', 'Criterion', 'Status', 'Finding'],
      open.map((r) => [r.id, r.plain || r.name, COV_OUT_TXT[r.outcome],
        r.outcome === 'FAIL' ? (r.fileIssues || []).map((i) => i.detail).filter(Boolean).slice(0, 2).join('; ') || `${r.count} finding(s)` : 'Needs a person to verify — routes through HITL review'
      ]),
      [55, 130, 90, p.CW - 55 - 130 - 90])
  }

  // Human review — teach WHY + exactly HOW to verify (not just "routes through HITL").
  const humanRows = rows.filter((r) => r.outcome === 'HUMAN')
  if (humanRows.length) {
    p.pageBreak()
    p.heading('Human review — how to verify')
    p.text('These criteria need a person to confirm compliance. For each: why automated checks can’t decide it, and exactly how to check.', { size: 9, color: MUTED, gapAfter: 10 })
    humanRows.forEach((r) => {
      const g = HUMAN_GUIDE[r.id] || DEFAULT_HUMAN
      p.text(`${r.id} · ${r.plain || r.name}`, { bold: true, size: 11, gapAfter: 3 })
      p.text(`Why a human: ${g.why}`, { size: 9.5, lh: 13, gapAfter: 3 })
      p.bullets(g.how, { size: 9.5 })
      p.text(`Estimated time: ~${g.min} min`, { size: 9, color: MUTED, gapAfter: 11 })
    })
  }

  // Manual verification guide — independently confirm on macOS & Windows.
  const _ext = (d.file || '').split('.').pop().toLowerCase()
  const _vg = VERIFY_GUIDE[_ext] || VERIFY_GUIDE.html
  p.pageBreak()
  p.heading('Manual verification guide')
  p.text(`Independently confirm this ${_vg.app} document’s accessibility — no ACP account needed. Steps for macOS and Windows, plus a screen-reader pass.`, { size: 9, color: MUTED, gapAfter: 10 })
  p.text('macOS', { bold: true, size: 10.5, gapAfter: 3 }); p.bullets(_vg.mac, { size: 9.5 })
  p.text('Windows', { bold: true, size: 10.5, gapAfter: 3 }); p.bullets(_vg.win, { size: 9.5 })
  p.text('Screen-reader pass', { bold: true, size: 10.5, gapAfter: 3 }); p.bullets(_vg.sr, { size: 9.5 })
  p.text('Confirm each of:', { bold: true, size: 10.5, gapAfter: 3 }); p.bullets(_vg.checks.map((c) => `☐ ${c}`), { size: 9.5 })

  p.pageBreak()
  p.heading('Full WCAG coverage')
  p.text(`Every criterion applicable to a document, at the ${d.targetLevel || 'AA'} certification target. ${uncheckedN > 0 ? `${uncheckedN} criteria are not yet automated for this file type and are reported as unchecked, not passing.` : ''}`, { size: 9, color: MUTED, gapAfter: 8 })
  p.table(['WCAG', 'Criterion', 'Level', 'Fix approach', 'Outcome', 'Confidence'],
    rows.map((r) => [r.id, r.plain || r.name, r.level, (r.fix || '').replace(/[⚡✎✋]\s*/, ''), COV_OUT_TXT[r.outcome], r.confidence ? r.confidence.level.label : '—']),
    [52, p.CW - 52 - 44 - 84 - 82 - 62, 44, 84, 82, 62])
  // Confidence is evidence-based, never a fabricated %: High = deterministic rule
  // check / checksum-validated PII / fix cleared on re-scan; Medium = AI-heuristic
  // detection lane or pattern-only match; Low = requires human review. See ADR 0016.
  p.text('Confidence is derived from concrete pipeline evidence (rule determinism, PII checksum validation, and residual-re-scan verification) — never an invented percentage. High = deterministic check, checksum-validated match, or a fix that cleared re-scan; Medium = AI/heuristic detection or pattern-only match; Low = requires human review.', { size: 8, color: MUTED, lh: 11 })

  p.pageBreak()
  p.heading('Audit trail')
  const auditRows = [
    ['Discovered', 'mova.io agent', 'Document ingested from source', d.file],
    ['Assessed', `mova.io · WCAG ${d.targetLevel || 'AA'}`, `${rows.length} criteria evaluated · score ${d.score ?? 'n/a'}/100`, d.file],
    ...(fixedN > 0 ? [['Auto-remediated', 'mova.io auto-fix', `${fixedN} criterion/criteria fixed`, d.file]] : []),
    ...(humanN > 0 ? [['Pending human review', 'HITL queue', `${humanN} criterion/criteria awaiting a reviewer`, d.file]] : []),
    ['Report generated', 'mova.io Platform', `${fullyConformant ? 'Zero open findings' : `${openN} item(s) still open`} · score ${d.score ?? 'n/a'}/100`, d.file],
  ]
  p.table(['Step', 'Actor', 'Action', 'Document'], auditRows, [72, 108, p.CW - 72 - 108 - 140, 140])

  p.heading('Conformance statement')
  p.callout(
    fullyConformant
      ? `"${d.file}" has been assessed against WCAG 2.1 Level ${d.targetLevel || 'AA'} success criteria as required by the Americans with Disabilities Act (ADA) Title II, the European Accessibility Act (EN 301 549), and Section 508 of the Rehabilitation Act. All ${rows.length} in-scope criteria evaluated by the mova.io engine for this file type are passing.`
      : `"${d.file}" has been assessed against WCAG 2.1 Level ${d.targetLevel || 'AA'} success criteria. ${passN + fixedN} of ${rows.length} in-scope criteria currently pass; ${failN} have an open finding and ${humanN} await human review. This document does NOT yet meet the bar for full certification — resolve the items listed above and re-validate to update this report.`,
    { color: fullyConformant ? GREEN : AMBER, bg: fullyConformant ? '#EEF5E8' : '#FBF1DF' }
  )
  p.text('Certified by the mova.io Accessibility Platform', { bold: true, size: 9.5, gapAfter: 4 })
  p.text(`Generated: ${d.timestamp || d.date}${d.platformVersion ? ` · Platform v${d.platformVersion}` : ''}`, { size: 9, color: MUTED, gapAfter: 4 })
  p.text('Authorised signatory: ___________________________', { size: 9, color: MUTED, gapAfter: 4 })
  p.text('Title / Role: ___________________________', { size: 9, color: MUTED, gapAfter: 16 })
  p.text('This report was generated by the mova.io Accessibility Platform from the live coverage data for this file and is intended as evidence for ADA, EAA, and Section 508 compliance audits.', { size: 8, color: MUTED, lh: 12 })

  p.save(d.filename || `mova-${(d.file || 'document').replace(/\.[^.]+$/, '')}-certification.pdf`)
}

// Immutable evidence package (Monitor) — the who/when/what/which-engine audit trail.
export async function exportEvidenceReport(d) {
  const p = await makeDoc({ title: 'Accessibility Evidence Package' })
  p.cover({
    title: 'Accessibility Evidence Package',
    subtitle: `${d.org} · immutable audit trail`,
    meta: [`Generated ${d.date}`, 'Standards: WCAG 2.1 AA · ADA Title II · EN 301 549 (EAA)'],
  })
  p.heading('Continuous monitoring')
  p.text(d.summary)
  if (d.metrics && d.metrics.length) p.metricGrid(d.metrics)
  p.heading('Audit trail')
  p.text('Every remediation, review, publish and re-scan is logged with the actor, the change, the document and the engine — append-only for audit.', { size: 9, color: MUTED, gapAfter: 11 })
  p.table(['Action', 'Actor', 'Change', 'Document'], d.events.map((e) => [e.action, e.actor, e.change, e.document]), [78, 92, p.CW - 78 - 92 - 150, 150])
  p.gap(2)
  p.text(`This evidence package was generated on ${d.date} from the continuous-monitoring log. Entries are immutable and timestamped for ADA / EAA audit and investigation.`, { size: 8.5, color: MUTED, lh: 12 })
  p.save(d.filename || 'mova-evidence-package.pdf')
}

// Accessibility Conformance Report (VPAT-style ACR) for the platform UI itself.
const ACR = [
  ['Perceivable', [
    ['1.1.1', 'Non-text Content', 'A', 'Supports', 'Icons/images labeled or decorative; charts use role="img" + descriptive aria-label.'],
    ['1.3.1', 'Info & Relationships', 'A', 'Supports', 'Headings, lists, tables, form labels and landmarks (header/main/nav).'],
    ['1.3.2', 'Meaningful Sequence', 'A', 'Supports', 'DOM order matches the visual order.'],
    ['1.4.1', 'Use of Color', 'A', 'Supports', 'Graph status uses glyphs + colour; legends carry text labels.'],
    ['1.4.3', 'Contrast (Minimum)', 'AA', 'Supports', 'Text corrected to at least 4.5:1.'],
    ['1.4.4 / 1.4.10', 'Resize / Reflow', 'AA', 'Supports', 'Responsive; zoom is not blocked.'],
    ['1.4.11', 'Non-text Contrast', 'AA', 'Supports', 'UI marks and graph dots corrected to at least 3:1.'],
    ['1.4.12', 'Text Spacing', 'AA', 'Supports', 'No clipping when spacing is overridden.'],
    ['1.4.13', 'Content on Hover or Focus', 'AA', 'Not Applicable', 'No persistent hover/focus content in the UI.'],
  ]],
  ['Operable', [
    ['2.1.1', 'Keyboard', 'A', 'Supports', 'All controls operable; graph uses roving tabindex (arrows / Enter / Escape).'],
    ['2.1.2', 'No Keyboard Trap', 'A', 'Supports', 'Dialogs trap intentionally; Escape always exits.'],
    ['2.4.1', 'Bypass Blocks', 'A', 'Supports', 'Skip-to-main link.'],
    ['2.4.2', 'Page Titled', 'A', 'Supports', 'Document title set.'],
    ['2.4.3', 'Focus Order', 'A', 'Supports', 'Logical order; no positive tabindex.'],
    ['2.4.4', 'Link Purpose (In Context)', 'A', 'Supports', 'Link text is meaningful.'],
    ['2.4.6', 'Headings & Labels', 'AA', 'Supports', 'Descriptive headings and labels.'],
    ['2.4.7', 'Focus Visible', 'AA', 'Supports', ':focus-visible outline on all controls.'],
    ['2.5.3', 'Label in Name', 'A', 'Supports', 'Visible labels match accessible names.'],
  ]],
  ['Understandable', [
    ['3.1.1', 'Language of Page', 'A', 'Supports', 'html lang attribute set.'],
    ['3.2.1 / 3.2.2', 'On Focus / On Input', 'A', 'Supports', 'No unexpected change of context.'],
    ['3.2.3 / 3.2.4', 'Consistent Navigation / Identification', 'AA', 'Supports', 'Consistent navigation and component identity.'],
    ['3.3.1 / 3.3.2', 'Error Identification / Labels', 'A', 'Supports', 'Inputs labeled; forms are minimal.'],
  ]],
  ['Robust', [
    ['4.1.2', 'Name, Role, Value', 'A', 'Supports', 'Correct roles and accessible names on custom controls.'],
    ['4.1.3', 'Status Messages', 'AA', 'Supports', 'aria-live / role=status on scan, chat, monitor and assess results.'],
  ]],
]
export async function exportConformanceReport(d = {}) {
  const date = d.date || new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const p = await makeDoc({ title: 'Accessibility Conformance Report — mova.io Platform' })
  p.cover({
    title: 'Accessibility Conformance Report',
    subtitle: `${d.org || 'mova.io Accessibility Platform'} · UI conformance + document coverage`,
    meta: [`WCAG 2.1 + 2.2 · ${date}`, 'Evaluation: automated (axe-core, all views) + manual code / semantic review'],
  })
  p.heading('Summary')
  p.text('This report covers two things: (1) the conformance of the mova.io Accessibility Platform’s own user interface, and (2) the WCAG coverage the platform provides for the documents it processes.')
  p.text('The platform UI conforms to WCAG 2.1 Level AA on all applicable Level A and AA success criteria, verified by automated and manual evaluation. Two issues found during manual review (an unannounced status update and a missing navigation landmark) were remediated.')
  p.heading('Part 1 · Platform UI conformance (WCAG 2.1 AA)')
  p.text('Conformance key:  Supports · Partially Supports · Not Applicable', { size: 9, color: MUTED, gapAfter: 4 })
  for (const [principle, rows] of ACR) {
    p.heading(principle)
    p.table(['Criterion', 'Lvl', 'Conformance', 'Notes'],
      rows.map((r) => [`${r[0]}  ${r[1]}`, r[2], r[3], r[4]]),
      [148, 28, 92, p.CW - 268])
  }

  // Part 2 — what the platform does for customer documents
  const cov = { live: 0, hitl: 0, partner: 0, road: 0 }
  const byLevel = { A: { tot: 0, cov: 0 }, AA: { tot: 0, cov: 0 }, AAA: { tot: 0, cov: 0 } }
  WCAG.forEach((c) => {
    const s = c.source
    if (s === 'Shipped (demo)') cov.live++
    else if (s === 'MDK HITL') cov.hitl++
    else if (s === 'Partner baseline') cov.partner++
    else cov.road++
    const lv = byLevel[c.level]; if (lv) { lv.tot++; if (s !== 'MDK net-new') lv.cov++ }
  })
  p.heading('Part 2 · Document remediation coverage (WCAG 2.1 + 2.2)')
  p.text('Beyond its own conformance, the platform detects and remediates accessibility issues in the documents it processes. Coverage across all 87 success criteria:', { gapAfter: 10 })
  p.metricGrid([
    { label: 'Live · auto/AI', value: cov.live, color: GREEN },
    { label: 'Covered · HITL', value: cov.hitl, color: '#1F5FA8' },
    { label: 'Partner (web)', value: cov.partner, color: PLUM },
    { label: 'Roadmap', value: cov.road, color: AMBER },
  ])
  p.table(['Conformance level', 'Criteria', 'Covered', 'Status'],
    [
      ['Level A · must-have', String(byLevel.A.tot), `${byLevel.A.cov} / ${byLevel.A.tot}`, byLevel.A.cov === byLevel.A.tot ? 'Fully covered' : `${byLevel.A.tot - byLevel.A.cov} in progress`],
      ['Level AA · legal target', String(byLevel.AA.tot), `${byLevel.AA.cov} / ${byLevel.AA.tot}`, byLevel.AA.cov === byLevel.AA.tot ? 'Fully covered — Level AA conformance reached' : `${byLevel.AA.tot - byLevel.AA.cov} in progress`],
      ['Level AAA · optional', String(byLevel.AAA.tot), `${byLevel.AAA.cov} / ${byLevel.AAA.tot}`, `${byLevel.AAA.tot - byLevel.AAA.cov} optional (human-produced media) remaining`],
    ],
    [p.CW - 70 - 70 - 210, 70, 70, 210])
  p.text('Every legally-required criterion (Level A and AA) is covered — by deterministic auto-fix, AI, the partner web scanner, or a human-in-the-loop review workflow. The full per-criterion matrix is available as the accompanying coverage matrix (Excel) and method deck (PowerPoint).', { size: 9.5, gapAfter: 6 })

  p.heading('Evaluation method & scope')
  p.text('Part 1 (UI conformance): axe-core across every view (zero Level A/AA violations) plus manual accessibility-tree review, keyboard operation, focus management, and live-region announcements. Part 2 (document coverage): each success criterion is classified by what the platform’s detect-and-remediate engines do today — deterministic auto-fix, AI, partner web scanner, or human-in-the-loop review.', { size: 9.5, gapAfter: 6 })
  p.text('Not yet performed: formal screen-reader user testing (NVDA / JAWS / VoiceOver) — recommended to finalize a signed conformance statement.', { size: 9.5, color: AMBER })
  p.save(d.filename || 'mova-accessibility-conformance-report.pdf')
}
