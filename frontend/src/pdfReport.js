// Native PDF report generator — composes a real, paginated document (selectable text,
// the mova.io logo, a clean grid layout, VECTOR bar charts), NOT a DOM screenshot. This
// is what makes the downloads read as governance documents instead of webpage printouts.
// jspdf is lazy-loaded so it stays out of the main bundle.

const INK = '#2B2330', MUTED = '#6B6670', LINE = '#E4E0E8', PLUM = '#4B3460', GREEN = '#3B6D11', AMBER = '#854F0B'
const rgb = (h) => { h = h.replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)] }

async function logoDataUrl() {
  try {
    const url = (import.meta.env.BASE_URL || '/') + 'mova-logo.png'
    const blob = await (await fetch(url)).blob()
    return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(blob) })
  } catch { return null }
}

async function makeDoc() {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF('p', 'pt', 'a4')
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

// Quarterly governance report (Overview).
export async function exportGovernanceReport(d) {
  const p = await makeDoc()
  p.cover({
    title: 'Quarterly Accessibility Governance Report',
    subtitle: `${d.org} · ${d.quarter} · WCAG 2.1 AA`,
    meta: [`Prepared for leadership · ${d.date}`, `Scope: ${d.scope || 'full document estate'}`],
  })
  p.heading('Executive summary')
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
  if (d.deptScores && d.deptScores.length) {
    p.heading('Performance by department')
    p.barChart(d.deptScores, { labelW: 160, max: 100, suffix: ' / 100' })
  }
  if (d.ontology && d.ontology.classified) {
    p.heading('Business ontology')
    p.text(`Ontology v${d.ontology.ver ?? 1} is active. ${d.ontology.classified} of ${Number(d.total).toLocaleString()} documents are classified by your organization's own rules — ${d.ontology.crit} Critical and ${d.ontology.high} High elevated in the remediation queue ahead of generic severity.`)
  }
  if (d.topViolations && d.topViolations.length) {
    p.heading('Top barriers')
    p.text(d.topViolations.map((v, i) => `${i + 1}.  ${v.label} — ${v.value} document${v.value === 1 ? '' : 's'}`).join('\n'), { lh: 15 })
  }
  p.save(d.filename || 'mova-quarterly-governance-report.pdf')
}

// Per-document conformance report (Upload).
export async function exportDocumentReport(d) {
  const p = await makeDoc()
  p.cover({
    title: 'Accessibility Conformance Report',
    subtitle: d.file,
    meta: [`Assessed ${d.date}${d.engine ? ` · ${d.engine}` : ''}`, `Result: ${d.score} / 100 · ${d.status}`],
  })
  p.heading('Result')
  p.metricGrid([
    { label: 'Score', value: `${d.score}/100`, color: d.score >= 90 ? GREEN : AMBER },
    { label: 'Findings', value: d.findings.length },
    { label: 'Auto-fixable', value: d.autoFix ?? 0, color: GREEN },
    { label: 'WCAG target', value: '2.1 AA' },
  ])
  p.heading('Findings')
  if (d.findings.length) p.table(['WCAG criterion', 'Severity', 'Detail'], d.findings.map((f) => [f.wcag, (f.sev || '').toLowerCase(), f.detail]), [120, 70, p.CW - 190])
  else p.text('No accessibility findings — the document meets WCAG 2.1 AA.', { color: GREEN })
  p.heading('Remediation')
  p.text(d.remediation || 'Mechanical fixes (alt text, headings, language, document title, table headers) are applied automatically and re-validated; judgment items (captions, link text, contrast) are routed to human review before publish.')
  p.gap(2)
  p.text(`Certified by the mova.io Accessibility Platform on ${d.date}. This report documents the conformance assessment and remediation actions for audit and evidence.`, { size: 8.5, color: MUTED, lh: 12 })
  p.save(d.filename || `mova-${(d.file || 'document').replace(/\.[^.]+$/, '')}-report.pdf`)
}
