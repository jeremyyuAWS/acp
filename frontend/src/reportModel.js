// SINGLE SOURCE OF TRUTH for the per-file WCAG certification report.
//
// This module builds a renderer-agnostic content MODEL (an ordered list of typed
// blocks) from the same coverage rows the FileDrawer shows on screen. Both the PDF
// renderer (pdfReport.js) and the HTML renderer (htmlReport.js) consume this one
// model, so the two exports can never drift: change the wording, the checklist, the
// audit trail or the conformance logic HERE and both downloads update together.
//
// A block is `{ k: <type>, ... }`. The PDF renderer maps each block onto a makeDoc
// primitive (heading/callout/bullets/text/metricGrid/donut/barChart/table); the HTML
// renderer maps each onto a semantic element. Text/callout/bullet blocks carry the
// exact option object the PDF primitive expects (size/color/bold/lh) so the PDF
// output is byte-for-byte what it was before this model was extracted — the HTML
// renderer reads the same options loosely (colour + emphasis; sizes are relative).

// Shared ink palette. Every colour used as TEXT here is dark enough to clear WCAG
// 1.4.3 (>= 4.5:1) on the white report background — the HTML report dogfoods the
// product, so it must itself pass contrast.
export const INK = '#2B2330', MUTED = '#6B6670', LINE = '#E4E0E8', PLUM = '#4B3460',
  GREEN = '#3B6D11', AMBER = '#854F0B', RED = '#A32D2D', BLUE = '#1F5FA8'

// A4 content width in pt (595.28 page − 2×50 margin). Table column widths are
// authored against this so the PDF lays out exactly as before; the HTML renderer
// turns the same widths into proportional columns.
export const CW = 495.28

const PRINCIPLE = { 1: 'Perceivable', 2: 'Operable', 3: 'Understandable', 4: 'Robust' }
const PRIN_CLR = { 1: BLUE, 2: GREEN, 3: AMBER, 4: PLUM }

const COV_OUT_TXT = { PASS: 'Pass', FAIL: 'Open finding', FIXED: 'Fixed · re-validate', HUMAN: 'Human review', UNCHECKED: 'Not auto-checked', WEB: 'Web-only (n/a)' }

// ── Certification-report evidence maps (curated content; no fabricated data) ──
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
export const VERIFY_GUIDE = {
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
const CAT_ORDER = ['Images', 'Headings & Titles', 'Tables & Structure', 'Links', 'Contrast', 'Language', 'Forms', 'Keyboard', 'Audio & Video', 'Other']

// Build the certification report model from the same `d` the PDF export received.
// Returns { docTitle, filename, lang, targetLevel, fullyConformant, footerVersion,
// footerGenerated, cover, blocks }.
export function buildFileCertificationModel(d) {
  const rows = d.rows || []
  const level = d.targetLevel || 'AA'
  // W4 — documented human dispositions of otherwise dead-end criteria (disposition.js). An
  // ATTESTED criterion stays in scope but is resolved by a human (no longer terminal-unchecked);
  // an OUT_OF_SCOPE criterion leaves the certification denominator, with its reason on the record.
  // Everything below degrades to the prior behaviour when no row carries a disposition.
  const disposed = rows.filter((r) => r.disposition && r.disposition.kind)
  const attestedRows = disposed.filter((r) => r.disposition.kind === 'attested')
  const outOfScopeRows = disposed.filter((r) => r.disposition.kind === 'out_of_scope')
  const outOfScopeSet = new Set(outOfScopeRows.map((r) => r.id))
  const passN = rows.filter((r) => r.outcome === 'PASS').length
  const fixedN = rows.filter((r) => r.outcome === 'FIXED').length
  const failN = rows.filter((r) => r.outcome === 'FAIL' && !outOfScopeSet.has(r.id)).length
  const humanN = rows.filter((r) => r.outcome === 'HUMAN' && !outOfScopeSet.has(r.id)).length
  const attestedN = attestedRows.length
  // Out-of-scope and attested criteria are no longer counted as "not auto-checked".
  const uncheckedN = rows.filter((r) => r.outcome === 'UNCHECKED' && !r.disposition).length
  // The certification denominator excludes out-of-scope criteria (they left the scope on purpose).
  const inScopeN = rows.length - outOfScopeSet.size
  const openN = failN + humanN
  const fullyConformant = inScopeN > 0 && openN === 0
  const generated = d.timestamp || d.date
  const tone = (good) => good
    ? { color: GREEN, bg: '#EEF5E8' }
    : { color: AMBER, bg: '#FBF1DF' }

  const blocks = []
  const H = (text) => blocks.push({ k: 'heading', text })
  const T = (text, o) => blocks.push({ k: 'text', text, o: o || {} })

  // ── Executive summary ──
  H('Executive summary')
  blocks.push({
    k: 'callout',
    text: fullyConformant
      ? `"${d.file}" meets all ${inScopeN} in-scope WCAG 2.1 Level ${level} criteria evaluated for this file type — no open findings remain.`
      : `"${d.file}" scored ${d.score ?? 'n/a'}/100 against WCAG 2.1 Level ${level} and is ${openN > 0 ? 'NOT yet fully certified' : 'conditionally certified'}: ${openN} of ${inScopeN} in-scope criteria still need attention.`,
    o: tone(fullyConformant),
  })
  blocks.push({
    k: 'bullets',
    items: [
      `${passN + fixedN} of ${inScopeN} in-scope criteria pass${fixedN ? ` — ${fixedN} auto-fixed, pending re-validation` : ''}`,
      failN ? `${failN} open finding${failN !== 1 ? 's' : ''} to resolve` : null,
      humanN ? `${humanN} criteri${humanN !== 1 ? 'a' : 'on'} need a human reviewer before certification` : null,
      attestedN ? `${attestedN} criteri${attestedN !== 1 ? 'a' : 'on'} manually attested by a human (verified out-of-band) — see Dispositions` : null,
      outOfScopeSet.size ? `${outOfScopeSet.size} criteri${outOfScopeSet.size !== 1 ? 'a' : 'on'} recorded out of scope for this engagement — see Dispositions` : null,
      uncheckedN ? `${uncheckedN} criteri${uncheckedN !== 1 ? 'a' : 'on'} not auto-checked for this file type — reported, not assumed passing` : null,
      fullyConformant ? 'Ready to certify and publish.' : 'Next step: resolve the open items below, then re-validate.',
    ].filter(Boolean),
    o: {},
  })
  T('Per-criterion outcomes match the platform’s WCAG coverage table for this file — pass is claimed only where the engine evaluated the criterion; unevaluated criteria are reported as such.', { size: 8.5, color: MUTED, lh: 12 })

  // ── Result ──
  H('Result')
  blocks.push({
    k: 'metricGrid',
    cards: [
      { label: 'Score', value: d.score != null ? `${d.score}/100` : 'n/a', color: fullyConformant ? GREEN : AMBER },
      { label: 'Pass', value: passN + fixedN, color: GREEN },
      { label: 'Open findings', value: failN, color: failN ? RED : GREEN },
      { label: 'Human review', value: humanN, color: humanN ? AMBER : GREEN },
    ],
  })

  // ── Coverage at a glance ──
  H('Coverage at a glance')
  blocks.push({
    k: 'donut',
    items: [
      { label: 'Pass', value: passN, color: GREEN },
      { label: 'Fixed · re-validate', value: fixedN, color: '#5C9B2E' },
      { label: 'Open finding', value: failN, color: RED },
      { label: 'Human review', value: humanN, color: AMBER },
      { label: 'Not auto-checked', value: uncheckedN, color: '#B6B0BC' },
    ],
  })

  // ── What ACP changed — the remediation log (auto-fixed criteria) ──
  if (fixedN > 0) {
    H('What ACP changed')
    T(`${fixedN} criteri${fixedN !== 1 ? 'a were' : 'on was'} remediated automatically, then re-validated against every engine before certification.`, { size: 9, color: MUTED, gapAfter: 8 })
    blocks.push({
      k: 'bullets',
      items: rows.filter((r) => r.outcome === 'FIXED').map((r) => {
        const n = r.count || 1
        return `${r.id} — ${CHANGE_LABEL[r.id] || `${r.plain || r.name} fixed`}${n > 1 ? ` (${n} occurrence${n !== 1 ? 's' : ''})` : ''}`
      }),
      o: {},
    })
    T('Automated fixes cover deterministic criteria (alt-text placeholders, language, titles, headers, contrast). Content needing human judgement is listed under “Human review”.', { size: 8.5, color: MUTED, lh: 12 })
  }

  // ── Before → After — the exact original text/markup vs. the remediated version for
  // every fix that verifiably cleared on the post-fix re-scan. Server returns these only
  // for a genuinely remediated file, so nothing here is illustrative — every pair is what
  // actually changed. Rendered as monospace before/after bands by both the PDF and HTML. ──
  const diffs = (d.diffs || []).filter((x) => x && (x.before != null || x.after != null))
  if (diffs.length) {
    const nameOf = (sc) => (rows.find((r) => r.id === sc)?.plain) || (rows.find((r) => r.id === sc)?.name) || CHANGE_LABEL[sc] || 'Remediated finding'
    const MAX = 24
    blocks.push({ k: 'pageBreak' })
    H('Before → After — what changed')
    T('The exact original text or markup and the remediated version of every fix ACP applied and then re-validated on this file. Truncated where long; the fixed copy is the source of truth.', { size: 9, color: MUTED, gapAfter: 10 })
    blocks.push({ k: 'beforeAfter', items: diffs.slice(0, MAX).map((x) => ({
      label: `${x.rule_id} · ${nameOf(x.rule_id)}`,
      note: x.note || '',
      before: x.before,
      after: x.after,
    })) })
    if (diffs.length > MAX) T(`+ ${diffs.length - MAX} more remediated change(s) not shown here — see the full coverage table and the remediated file.`, { size: 8.5, color: MUTED, lh: 12 })
  }

  // ── Manual attestations & dispositions (W4) — the documented resolution of criteria that
  // automated checks could not decide. Each carries the reason a human recorded, so the record
  // shows HOW a criterion outside ACP's automated reach was resolved, never a silent wave-through. ──
  if (disposed.length) {
    H('Manual attestations & dispositions')
    T(`${disposed.length} criteri${disposed.length !== 1 ? 'a were' : 'on was'} resolved outside ACP's automated checks — ${attestedN} manually attested (verified out-of-band) and ${outOfScopeSet.size} recorded as out of scope for this engagement. Each is documented below with the reason on record.`, { size: 9, color: MUTED, gapAfter: 8 })
    blocks.push({
      k: 'table',
      headers: ['WCAG', 'Criterion', 'Disposition', 'Reason'],
      caption: 'Manual attestations and out-of-scope dispositions',
      rows: disposed.map((r) => [
        r.id, r.plain || r.name,
        r.disposition.kind === 'attested' ? 'Manually attested' : 'Out of scope',
        `${r.disposition.reason}${r.disposition.actor ? ` — ${r.disposition.actor}` : ''}`,
      ]),
      widths: [52, 150, 100, CW - 52 - 150 - 100],
    })
    T('A manual attestation is a human’s recorded verification, not an ACP-certified automated pass; an out-of-scope criterion is excluded from the in-scope conformance denominator above. Both are immutable decisions in the audit trail.', { size: 8.5, color: MUTED, lh: 12 })
  }

  // ── Compliance checklist — grouped by what a reviewer actually cares about ──
  H('Compliance checklist')
  const catAgg = {}
  rows.forEach((r) => {
    const c = CAT_OF(r.id); const o = r.outcome.toLowerCase()
    ;(catAgg[c] || (catAgg[c] = {})); catAgg[c][o] = (catAgg[c][o] || 0) + 1
  })
  blocks.push({
    k: 'table',
    headers: ['Area', 'Status'],
    caption: 'Compliance checklist by area',
    rows: CAT_ORDER.filter((c) => catAgg[c]).map((c) => {
      const a = catAgg[c]
      const status = a.fail ? '✗ Open finding' : a.human ? '◐ Human review' : (a.unchecked && !a.pass && !a.fixed) ? '— Not auto-checked' : '✓ Pass'
      return [c, status]
    }),
    widths: [CW - 170, 170],
  })

  // ── Open items — must resolve before full certification ──
  if (openN > 0) {
    blocks.push({ k: 'pageBreak' })
    const open = rows.filter((r) => r.outcome === 'FAIL' || r.outcome === 'HUMAN')
      .sort((a, b) => (a.outcome === 'FAIL' ? 0 : 1) - (b.outcome === 'FAIL' ? 0 : 1))
    const prinCount = {}
    open.forEach((r) => { const k = r.id.match(/^(\d)/)?.[1]; if (PRINCIPLE[k]) prinCount[k] = (prinCount[k] || 0) + 1 })
    const prinItems = Object.keys(PRINCIPLE).filter((k) => prinCount[k]).map((k) => ({ label: PRINCIPLE[k], value: prinCount[k], color: PRIN_CLR[k] }))
    if (prinItems.length) {
      H('Open items by WCAG principle')
      T('The four WCAG principles — content must be Perceivable, Operable, Understandable, and Robust.', { size: 9, color: MUTED, gapAfter: 11 })
      blocks.push({ k: 'barChart', items: prinItems, o: { labelW: 150 } })
    }
    H('Open items — must resolve before full certification')
    blocks.push({
      k: 'table',
      headers: ['WCAG', 'Criterion', 'Status', 'Finding'],
      caption: 'Open items to resolve before full certification',
      rows: open.map((r) => [r.id, r.plain || r.name, COV_OUT_TXT[r.outcome],
        r.outcome === 'FAIL' ? (r.fileIssues || []).map((i) => i.detail).filter(Boolean).slice(0, 2).join('; ') || `${r.count} finding(s)` : 'Needs a person to verify — routes through HITL review'
      ]),
      widths: [55, 130, 90, CW - 55 - 130 - 90],
    })
  }

  // ── Human review — teach WHY + exactly HOW to verify ──
  const humanRows = rows.filter((r) => r.outcome === 'HUMAN')
  if (humanRows.length) {
    blocks.push({ k: 'pageBreak' })
    H('Human review — how to verify')
    T('These criteria need a person to confirm compliance. For each: why automated checks can’t decide it, and exactly how to check.', { size: 9, color: MUTED, gapAfter: 10 })
    humanRows.forEach((r) => {
      const g = HUMAN_GUIDE[r.id] || DEFAULT_HUMAN
      T(`${r.id} · ${r.plain || r.name}`, { bold: true, size: 11, gapAfter: 3 })
      T(`Why a human: ${g.why}`, { size: 9.5, lh: 13, gapAfter: 3 })
      blocks.push({ k: 'bullets', items: g.how, o: { size: 9.5 } })
      T(`Estimated time: ~${g.min} min`, { size: 9, color: MUTED, gapAfter: 11 })
    })
  }

  // ── Manual verification guide — independently confirm on macOS & Windows ──
  const _ext = (d.file || '').split('.').pop().toLowerCase()
  const _vg = VERIFY_GUIDE[_ext] || VERIFY_GUIDE.html
  blocks.push({ k: 'pageBreak' })
  H('Manual verification guide')
  T(`Independently confirm this ${_vg.app} document’s accessibility — no ACP account needed. Steps for macOS and Windows, plus a screen-reader pass.`, { size: 9, color: MUTED, gapAfter: 10 })
  T('macOS', { bold: true, size: 10.5, gapAfter: 3 }); blocks.push({ k: 'bullets', items: _vg.mac, o: { size: 9.5 } })
  T('Windows', { bold: true, size: 10.5, gapAfter: 3 }); blocks.push({ k: 'bullets', items: _vg.win, o: { size: 9.5 } })
  T('Screen-reader pass', { bold: true, size: 10.5, gapAfter: 3 }); blocks.push({ k: 'bullets', items: _vg.sr, o: { size: 9.5 } })
  T('Confirm each of:', { bold: true, size: 10.5, gapAfter: 3 }); blocks.push({ k: 'bullets', items: _vg.checks.map((c) => `☐ ${c}`), o: { size: 9.5 } })

  // ── Full WCAG coverage ──
  blocks.push({ k: 'pageBreak' })
  H('Full WCAG coverage')
  T(`Every criterion applicable to a document, at the ${level} certification target. ${uncheckedN > 0 ? `${uncheckedN} criteria are not yet automated for this file type and are reported as unchecked, not passing.` : ''}`, { size: 9, color: MUTED, gapAfter: 8 })
  blocks.push({
    k: 'table',
    headers: ['WCAG', 'Criterion', 'Level', 'Fix approach', 'Outcome', 'Confidence'],
    caption: `Full WCAG coverage at the ${level} certification target`,
    rows: rows.map((r) => [r.id, r.plain || r.name, r.level, (r.fix || '').replace(/[⚡✎✋]\s*/, ''),
      r.disposition ? (r.disposition.kind === 'attested' ? 'Attested (human)' : 'Out of scope') : COV_OUT_TXT[r.outcome],
      r.disposition ? (r.disposition.kind === 'attested' ? 'Human' : '—') : r.confidence ? r.confidence.level.label : '—']),
    widths: [52, CW - 52 - 44 - 84 - 82 - 62, 44, 84, 82, 62],
  })
  // Confidence is evidence-based, never a fabricated % (ADR 0016): High = a deterministic
  // rule check, a checksum-validated PII match, or a fix that cleared re-scan; Medium = an
  // AI/heuristic detection lane or a pattern-only match; Low = requires human review.
  T('Confidence is derived from concrete pipeline evidence (rule determinism, PII checksum validation, and residual-re-scan verification) — never an invented percentage. High = deterministic check, checksum-validated match, or a fix that cleared re-scan; Medium = AI/heuristic detection or pattern-only match; Low = requires human review.', { size: 8, color: MUTED, lh: 11 })

  // ── Audit trail ──
  blocks.push({ k: 'pageBreak' })
  H('Audit trail')
  const auditRows = [
    ['Discovered', 'mova.io agent', 'Document ingested from source', d.file],
    ['Assessed', `mova.io · WCAG ${level}`, `${rows.length} criteria evaluated · score ${d.score ?? 'n/a'}/100`, d.file],
    ...(fixedN > 0 ? [['Auto-remediated', 'mova.io auto-fix', `${fixedN} criterion/criteria fixed`, d.file]] : []),
    ...(humanN > 0 ? [['Pending human review', 'HITL queue', `${humanN} criterion/criteria awaiting a reviewer`, d.file]] : []),
    ...(attestedN > 0 ? [['Manually attested', 'human disposition', `${attestedN} criterion/criteria verified out-of-band`, d.file]] : []),
    ...(outOfScopeSet.size > 0 ? [['Marked out of scope', 'human disposition', `${outOfScopeSet.size} criterion/criteria excluded with a recorded reason`, d.file]] : []),
    ['Report generated', 'mova.io Platform', `${fullyConformant ? 'Zero open findings' : `${openN} item(s) still open`} · score ${d.score ?? 'n/a'}/100`, d.file],
  ]
  blocks.push({ k: 'table', headers: ['Step', 'Actor', 'Action', 'Document'], caption: 'Audit trail', rows: auditRows, widths: [72, 108, CW - 72 - 108 - 140, 140] })

  // ── Conformance statement ──
  H('Conformance statement')
  blocks.push({
    k: 'callout',
    text: fullyConformant
      ? `"${d.file}" has been assessed against WCAG 2.1 Level ${level} success criteria as required by the Americans with Disabilities Act (ADA) Title II, the European Accessibility Act (EN 301 549), and Section 508 of the Rehabilitation Act. All ${inScopeN} in-scope criteria evaluated by the mova.io engine for this file type are passing${attestedN ? ` (including ${attestedN} resolved by recorded human attestation)` : ''}.${outOfScopeSet.size ? ` ${outOfScopeSet.size} criteri${outOfScopeSet.size !== 1 ? 'a were' : 'on was'} recorded out of scope for this engagement.` : ''}`
      : `"${d.file}" has been assessed against WCAG 2.1 Level ${level} success criteria. ${passN + fixedN} of ${inScopeN} in-scope criteria currently pass; ${failN} have an open finding and ${humanN} await human review. This document does NOT yet meet the bar for full certification — resolve the items listed above and re-validate to update this report.`,
    o: tone(fullyConformant),
  })
  T('Certified by the mova.io Accessibility Platform', { bold: true, size: 9.5, gapAfter: 4 })
  T(`Generated: ${generated}${d.platformVersion ? ` · Platform v${d.platformVersion}` : ''}`, { size: 9, color: MUTED, gapAfter: 4 })
  T('Authorised signatory: ___________________________', { size: 9, color: MUTED, gapAfter: 4 })
  T('Title / Role: ___________________________', { size: 9, color: MUTED, gapAfter: 16 })
  T('This report was generated by the mova.io Accessibility Platform from the live coverage data for this file and is intended as evidence for ADA, EAA, and Section 508 compliance audits.', { size: 8, color: MUTED, lh: 12 })

  return {
    docTitle: `Accessibility Certification — ${d.file}`,
    filename: d.filename || `mova-${(d.file || 'document').replace(/\.[^.]+$/, '')}-certification`,
    lang: d.lang || 'en-US',
    targetLevel: level,
    fullyConformant,
    footerVersion: d.platformVersion,
    footerGenerated: generated,
    cover: {
      title: 'Accessibility Certification',
      subtitle: d.file,
      meta: [
        `Generated ${generated}${d.engine ? ` · ${d.engine}` : ''}`,
        `WCAG 2.1 Level ${level}${d.sourceName ? ` · ${d.sourceName}` : ''}${d.department ? ` · ${d.department}` : ''}`,
      ],
      ring: d.score != null ? { score: d.score, color: fullyConformant ? GREEN : AMBER } : null,
    },
    blocks,
  }
}

// ── Remediation report ────────────────────────────────────────────────────────────────────
//
// The deliverable a reviewer signs: WHAT was changed, WHEN, and a checkbox per item so a human
// can confirm each one in the real application. Distinct from the certification report, which
// states conformance — this states WORK DONE and asks someone to verify it.
//
// TIMESTAMPS ARE NOT INVENTED. `remediation_diff` carries no time column at all
// (scan_id, file, rule_id, seq, before, after, note); the clock lives in
// `applied_fixes.created_at` and `file_records.remediated_at`. So an item is stamped only when
// applied_fixes holds a row for that (file, criterion). Everything else reads "time not
// recorded" rather than borrowing the document's timestamp and implying a precision we do not
// have — a signed remediation record is exactly the wrong place to round up.
// This module has NO imports on purpose — it is the pure model layer, and pdfReport.js owns the
// catalog lookups and passes them in. So the SC parse is inlined rather than imported from
// coreStats, and criterion names arrive as `scNames` from the caller.
const _sc = (w) => ((String(w || '')).replace(/^SC_/, '').replace(/_/g, '.').match(/\d+\.\d+\.\d+/) || [])[0]
const _fmtOf = (f) => (String(f || '').split('.').pop() || '').toLowerCase()
const _base = (p) => String(p || '').split('/').filter(Boolean).pop() || ''
const _dir = (p) => { const s = String(p || '').split('/').filter(Boolean); return s.length > 1 ? s.slice(0, -1).join('/') : '' }
const _when = (iso) => {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString(undefined,
    { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// files        the scan's file rows (needs .file and .remediated_at)
// diffsByFile  { [file]: [{ rule_id, before, after, note }] } — the evidence
// appliedFixes [{ file, rule_id, created_at }] — the clock. May be empty (SIM, or a scan whose
//              fixes predate the table); absence degrades to "time not recorded", never a guess.
// cappedAt     the server's row limit, when the caller hit it, so the report can SAY it is
//              partial instead of presenting a truncated list as complete.
// scNames      { [sc]: 'Non-text Content' } — supplied by the caller, which owns the catalog.
export function buildRemediationModel({ files = [], diffsByFile = {}, appliedFixes = [],
                                        level = 'AA', org = '', generatedAt = null,
                                        scanId = null, reviewByFile = {}, cappedAt = null,
                                        scNames = {} } = {}) {
  const stamp = {}
  for (const f of appliedFixes || []) {
    const k = `${f.file} ${_sc(f.rule_id)}`
    // Earliest wins. A criterion fixed across nineteen images was DONE when the first write
    // landed; the API returns newest-first, which would otherwise report the last one.
    if (!stamp[k] || String(f.created_at) < String(stamp[k])) stamp[k] = f.created_at
  }

  const documents = []
  for (const rec of files) {
    const diffs = diffsByFile[rec.file] || []
    if (!diffs.length && !rec.remediated_at) continue     // nothing was done to this document
    const seen = new Set()
    const items = []
    for (const d of diffs) {
      const sc = _sc(d.rule_id)
      if (!sc || seen.has(sc)) continue                   // one checkbox per criterion, not per image
      seen.add(sc)
      const at = stamp[`${rec.file} ${sc}`] || null
      items.push({
        sc,
        category: CAT_OF(sc),
        name: scNames[sc] || d.rule_id,
        note: d.note || null,
        before: d.before,
        after: d.after,
        at: _when(at),
        atIso: at,
      })
    }
    items.sort((a, b) => (CAT_ORDER.indexOf(a.category) - CAT_ORDER.indexOf(b.category)) || a.sc.localeCompare(b.sc))
    documents.push({
      file: rec.file,
      name: _base(rec.file),
      dir: _dir(rec.file),
      fmt: _fmtOf(rec.file),
      remediatedAt: _when(rec.remediated_at),
      awaiting: reviewByFile[rec.file] || 0,
      items,
    })
  }
  documents.sort((a, b) => a.name.localeCompare(b.name))

  const totalItems = documents.reduce((n, d) => n + d.items.length, 0)
  const stamped = documents.reduce((n, d) => n + d.items.filter((i) => i.at).length, 0)
  // Only the formats actually present get a "how to verify" section. A report on three PDFs has
  // no business explaining PowerPoint.
  const formats = [...new Set(documents.map((d) => d.fmt))].filter((f) => VERIFY_GUIDE[f]).sort()

  return {
    org, level, scanId,
    generatedAt: _when(generatedAt) || _when(new Date().toISOString()),
    documents,
    formats,
    totals: {
      documents: documents.length,
      items: totalItems,
      stamped,
      unstamped: totalItems - stamped,
      awaiting: documents.reduce((n, d) => n + d.awaiting, 0),
      criteria: new Set(documents.flatMap((d) => d.items.map((i) => i.sc))).size,
    },
    // Said out loud in the PDF, never swallowed: a truncated list that looks complete is worse
    // than one that admits it is truncated.
    partial: cappedAt != null && (appliedFixes || []).length >= cappedAt ? cappedAt : null,
  }
}
