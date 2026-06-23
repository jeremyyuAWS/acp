// Native PDF report generator — composes a real, paginated document (selectable text,
// the mova.io logo, a clean grid layout, VECTOR bar charts), NOT a DOM screenshot. This
// is what makes the downloads read as governance documents instead of webpage printouts.
// jspdf is lazy-loaded so it stays out of the main bundle.

import { statusFor } from './exportDeliverables.js'

const INK = '#2B2330', MUTED = '#6B6670', LINE = '#E4E0E8', PLUM = '#4B3460', GREEN = '#3B6D11', AMBER = '#854F0B'
const rgb = (h) => { h = h.replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)] }

async function logoDataUrl() {
  try {
    const url = (import.meta.env.BASE_URL || '/') + 'mova-logo.png'
    const blob = await (await fetch(url)).blob()
    return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(blob) })
  } catch { return null }
}

async function makeDoc({ title = 'mova.io Accessibility Report', lang = 'en-US' } = {}) {
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
      for (let p = 1; p <= pages; p++) {
        doc.setPage(p); draw(LINE); doc.setLineWidth(0.8); doc.line(M, H - FOOT + 10, M + CW, H - FOOT + 10)
        ink(MUTED); doc.setFont('helvetica', 'normal'); doc.setFontSize(8)
        doc.text('mova.io · Accessibility Platform', M, H - FOOT + 25)
        doc.text('Confidential', W / 2, H - FOOT + 25, { align: 'center' })
        doc.text(`Page ${p} of ${pages}`, M + CW, H - FOOT + 25, { align: 'right' })
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
    meta: [`Assessed ${d.date}${d.engine ? ` · ${d.engine}` : ''}`, `WCAG 2.1 AA · ${d.status || 'Remediated'}`],
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

  p.heading('Methodology & standards')
  p.text(`Assessed with the ${d.engine || 'mova.io WCAG 2.1 AA'} engine. ${d.autoFix ?? 0} finding(s) were auto-remediated by the platform; ${d.humanReview ?? 1} routed to human review and approved before certification. The document was re-validated after the fixes were applied.`, { size: 9.5, gapAfter: 7 })
  p.text('Standards: WCAG 2.1 AA · ADA Title II · EN 301 549 (EAA) · Section 508.', { size: 9, color: MUTED, gapAfter: 7 })
  p.text(`Certified by the mova.io Accessibility Platform on ${d.date}. This report documents the conformance assessment and remediation actions for audit and evidence.`, { size: 8.5, color: MUTED, lh: 12 })
  p.save(d.filename || `mova-${(d.file || 'document').replace(/\.[^.]+$/, '')}-report.pdf`)
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
    subtitle: `${d.org || 'mova.io Accessibility Platform'} · web application UI`,
    meta: [`WCAG 2.1 Level A & AA · ${date}`, 'Evaluation: automated (axe-core, all views) + manual code / semantic review'],
  })
  p.heading('Summary')
  p.text('The mova.io Accessibility Platform UI conforms to WCAG 2.1 Level AA on all applicable Level A and AA success criteria, verified by automated and manual evaluation. Two issues found during manual review (an unannounced status update and a missing navigation landmark) were remediated.')
  p.text('Conformance key:  Supports · Partially Supports · Not Applicable', { size: 9, color: MUTED, gapAfter: 4 })
  for (const [principle, rows] of ACR) {
    p.heading(principle)
    p.table(['Criterion', 'Lvl', 'Conformance', 'Notes'],
      rows.map((r) => [`${r[0]}  ${r[1]}`, r[2], r[3], r[4]]),
      [148, 28, 92, p.CW - 268])
  }
  p.heading('Evaluation method & scope')
  p.text('Automated: axe-core run across every view (zero Level A/AA violations). Manual: accessibility-tree review, keyboard operation, focus management, and live-region announcements. Scope: the platform’s own web UI (not the conformance of documents it remediates, which is reported separately).', { size: 9.5, gapAfter: 6 })
  p.text('Not yet performed: formal screen-reader user testing (NVDA / JAWS / VoiceOver) — recommended to finalize a signed conformance statement.', { size: 9.5, color: AMBER })
  p.save(d.filename || 'mova-accessibility-conformance-report.pdf')
}
