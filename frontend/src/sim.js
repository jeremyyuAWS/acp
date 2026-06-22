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
  'public-facing': ['#E6F1FB', '#185FA5'], 'PII': ['#E2EDFB', '#1F5FA8'],
  'legal-hold': ['#EEEDFE', '#3C3489'], 'high-traffic': ['#FAEEDA', '#854F0B'],
  'auto-fixable': ['#E1F5EE', '#0F6E56'], 'needs-review': ['#E6EFFB', '#2A5E9E'],
  'remediation-queued': ['#FAEEDA', '#854F0B'], 'certified': ['#E7F0DC', '#3B6D11'],
  'policy': ['#F1EFE8', '#5F5E5A'], 'financial': ['#F1EFE8', '#5F5E5A'], 'marketing': ['#F1EFE8', '#5F5E5A'],
}

export const DEPARTMENTS = [
  'Cardiology', 'Radiology', 'Oncology', 'Neurology', 'Patient Education',
  'Human Resources', 'Legal & Compliance', 'Research Administration', 'Finance', 'Communications',
]

// Demo personas — each authenticates via a different SSO method, is scoped to a
// subset of the estate (departments or just their own files), and is granted a
// different set of capabilities (RBAC `allow` = which tabs + settings they see).
export const PERSONAS = [
  { id: 'admin', name: 'Sam Devlin', role: 'Platform Admin', email: 'sam.devlin@utsouthwestern.edu', sso: 'Okta',
    scope: { label: 'Platform configuration · all sources', departments: 'all' },
    allow: ['overview', 'integrations', 'monitor', 'settings'] },
  { id: 'compliance', name: 'Alex Rivera', role: 'Compliance Officer', email: 'alex.rivera@utsouthwestern.edu', sso: 'Okta',
    scope: { label: 'Full estate · all 10 departments', departments: 'all' },
    allow: ['overview', 'discover', 'assess', 'remediate', 'publish', 'monitor', 'upload'] },
  { id: 'depthead', name: 'Marcus Chen', role: 'Department Head — Finance', email: 'marcus.chen@utsouthwestern.edu', sso: 'Microsoft',
    scope: { label: 'Finance, Legal, HR, Research & Comms — incl. confidential', departments: ['Finance', 'Legal & Compliance', 'Human Resources', 'Research Administration', 'Communications'] },
    allow: ['overview', 'assess', 'monitor'] },
  { id: 'enduser', name: 'Jordan Romero', role: 'End User — Patient Education', email: 'jordan.romero@utsouthwestern.edu', sso: 'Google',
    scope: { label: 'My documents only', owner: 'J. Romero' },
    allow: ['overview', 'monitor', 'upload'] },
]
let activeId = PERSONAS[1]
let activeDepts = null
let activeOwner = null
export function setPersona(p) {
  activeId = p || PERSONAS[1]
  const sc = activeId.scope || {}
  activeDepts = (sc.departments && sc.departments !== 'all') ? new Set(sc.departments) : null
  activeOwner = sc.owner || null
}
export const simIdentity = () => ({ email: activeId.email, name: activeId.name, role: activeId.role, scope: activeId.scope.label, allow: activeId.allow || [] })
const scoped = () => {
  let c = CORPUS
  if (activeDepts) c = c.filter((f) => activeDepts.has(f.department))
  if (activeOwner) c = c.filter((f) => f.owner === activeOwner)
  return c
}
export const simGetSources = () => {
  const present = new Set(scoped().map((f) => f.source))
  return SOURCES.filter((s) => present.has(s.id)).map((s) => ({ type: s.kind, name: s.name, id: s.id, files: s.files, access: s.access, dept: s.dept, agent: s.agent }))
}

// Formats span documents, web, AND time-based media (video/audio) — the full
// reach of WCAG 2.1. The estate simulates all of them; the Upload tab is kept to
// what the partner tech can process live today (PDF / Office / web).
const TYPES = ['pdf', 'docx', 'pptx', 'xlsx', 'html', 'video', 'audio']
const EXT = { video: 'mp4', audio: 'mp3' }
const ENG = { docx: '.net/office', pptx: '.net/office', xlsx: '.net/office', pdf: 'python/pdf', html: 'axe/web', video: 'media/asr+caption', audio: 'media/asr' }
const NAMES = {
  pdf: ['patient-handbook', 'care-pathway', 'discharge-instructions', 'clinical-guideline', 'consent-form', 'annual-summary'],
  docx: ['policy', 'procedure', 'protocol', 'sop', 'charter', 'guidelines'],
  pptx: ['town-hall', 'training-deck', 'grand-rounds', 'orientation'],
  xlsx: ['metrics-tracker', 'roster', 'budget', 'schedule'],
  html: ['intranet-page', 'public-page', 'faq', 'news-post'],
  video: ['patient-explainer', 'training-video', 'town-hall-recording', 'procedure-walkthrough', 'welcome-message'],
  audio: ['podcast-episode', 'wellness-segment', 'ivr-prompt', 'audio-guide'],
}
const SRC_FOR = { pdf: ['box', 'gdrive', 'sharepoint'], docx: ['sharepoint', 'confluence'], pptx: ['gdrive', 'box'], xlsx: ['box', 'sharepoint'], html: ['cms'], video: ['gdrive', 'box', 'cms'], audio: ['box', 'cms'] }
const ISS_POOL = {
  pdf: [['pdf.tagged', 'SC_1_3_1', 'SERIOUS'], ['pdf.alt-text', 'SC_1_1_1', 'CRITICAL'], ['pdf.document-language', 'SC_3_1_1', 'MODERATE'], ['pdf.reading-order', 'SC_1_3_2', 'MODERATE']],
  docx: [['DOCX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['DOCX-TITLE-001', 'SC_2_4_2', 'SERIOUS'], ['DOCX-TABLE-001', 'SC_1_3_1', 'SERIOUS'], ['DOCX-LINK-001', 'SC_2_4_4', 'MODERATE']],
  pptx: [['PPTX-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['PPTX-TITLE-001', 'SC_2_4_2', 'SERIOUS'], ['PPTX-ORDER-001', 'SC_1_3_2', 'MODERATE']],
  xlsx: [['XLSX-ALT-001', 'SC_1_1_1', 'MODERATE'], ['XLSX-HEADER-001', 'SC_1_3_1', 'MODERATE'], ['XLSX-SHEET-001', 'SC_2_4_2', 'MINOR']],
  html: [['WEB-ALT-001', 'SC_1_1_1', 'CRITICAL'], ['WEB-CONTRAST-001', 'SC_1_4_3', 'SERIOUS'], ['WEB-LABEL-001', 'SC_1_3_1', 'MODERATE'], ['WEB-LANG-001', 'SC_3_1_1', 'MINOR']],
  video: [['VIDEO-CAPTIONS-001', 'SC_1_2_2', 'CRITICAL'], ['VIDEO-AUDIODESC-001', 'SC_1_2_5', 'SERIOUS'], ['VIDEO-TRANSCRIPT-001', 'SC_1_2_3', 'MODERATE']],
  audio: [['AUDIO-TRANSCRIPT-001', 'SC_1_2_1', 'CRITICAL'], ['AUDIO-CAPTION-001', 'SC_1_2_2', 'MODERATE']],
}
const DEPT_TAGS = {
  'Patient Education': ['public-facing', 'high-traffic'], 'Communications': ['public-facing', 'high-traffic', 'marketing'],
  'Human Resources': ['PII', 'policy'], 'Legal & Compliance': ['legal-hold', 'policy'], 'Finance': ['financial'],
  'Research Administration': ['PII', 'policy'], 'Cardiology': ['PII'], 'Radiology': ['PII'], 'Oncology': ['PII'], 'Neurology': ['PII'],
}
const STATUS_CYCLE = ['issues', 'certifiable', 'issues', 'uncertain', 'issues', 'certifiable', 'issues', 'certifiable', 'issues', 'error']
const DEPT_COUNTS = [19, 17, 15, 22, 18, 16, 20, 15, 17, 16]
const slug = (d) => d.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const iss = (rows) => rows.map(([ruleId, wcag, severity]) => ({ ruleId, rule_id: ruleId, wcag, severity }))

// Human-readable specifics for each finding — what the engine actually saw
// (counts, where), the user impact, and how it's fixed. Deterministic by seed.
const FIND = {
  SC_1_1_1: (s) => { const total = 2 + s % 6, miss = 1 + s % Math.min(total, 3); return { detail: `${total} images · ${miss} missing alt text`, impact: 'Screen-reader users can’t perceive these images at all.', fix: 'AI generates descriptive alt text for each, then re-validates.', auto: true, level: 'A' } },
  SC_1_3_1: (s) => { const t = 1 + s % 4, bad = 1 + s % t; return { detail: `${t} table${t > 1 ? 's' : ''} · ${bad} missing header cells`, impact: 'Table data loses meaning without programmatic headers.', fix: 'Mark the header row / column so structure is announced.', auto: true, level: 'A' } },
  SC_1_3_2: (s) => { const p = 1 + s % 5; return { detail: `Reading order differs from the visual layout on ${p} page${p > 1 ? 's' : ''}`, impact: 'Screen readers announce the content out of sequence.', fix: 'Re-tag the reading order to match the visual flow.', auto: true, level: 'A' } },
  SC_2_4_2: () => ({ detail: 'Document title is empty', impact: 'Users can’t identify the document in their assistive tech.', fix: 'Set a descriptive document title.', auto: true, level: 'A' }),
  SC_2_4_4: (s) => { const t = 4 + s % 10, bad = 1 + s % 4; return { detail: `${t} links · ${bad} with non-descriptive text (e.g. “click here”)`, impact: 'A list of links read aloud becomes meaningless out of context.', fix: 'Rewrite the ambiguous link text — needs human judgement.', auto: false, level: 'A' } },
  SC_3_1_1: () => ({ detail: 'Document language is not declared', impact: 'Screen readers may read the text with the wrong pronunciation engine.', fix: 'Set the document language attribute.', auto: true, level: 'A' }),
  SC_1_4_3: (s) => { const t = 6 + s % 12, bad = 2 + s % 6; return { detail: `${bad} of ${t} text elements fall below the 4.5:1 contrast minimum`, impact: 'Low-vision users can’t read low-contrast text.', fix: 'Adjust colours to meet 4.5:1 — needs a design review.', auto: false, level: 'AA' } },
  SC_2_1_1: (s) => { const n = 1 + s % 4; return { detail: `${n} interactive element${n > 1 ? 's' : ''} not reachable by keyboard`, impact: 'Keyboard-only users can’t operate these controls.', fix: 'Add proper focus handling — needs a developer.', auto: false, level: 'A' } },
  // time-based media (video / audio)
  SC_1_2_2: (s) => { const m = 2 + s % 12, sec = (s * 7) % 60; return { detail: `No synchronized captions (${m}:${String(sec).padStart(2, '0')} of media)`, impact: 'Deaf / hard-of-hearing users can’t follow the spoken content.', fix: 'AI drafts captions (speech-to-text); a human reviews timing & accuracy.', auto: false, level: 'A' } },
  SC_1_2_5: () => ({ detail: 'No audio-description track for the visual content', impact: 'Blind users miss information shown only on screen.', fix: 'Script + record an audio description — human produced.', auto: false, level: 'AA' }),
  SC_1_2_3: () => ({ detail: 'No audio description or full text alternative', impact: 'Blind users miss the visual-only information in the video.', fix: 'Provide an audio description or a complete text alternative.', auto: false, level: 'A' }),
  SC_1_2_1: () => ({ detail: 'No text transcript provided', impact: 'Deaf / hard-of-hearing users can’t access the audio at all.', fix: 'AI drafts a transcript from speech-to-text; a human verifies.', auto: false, level: 'A' }),
  // AAA criteria — derived from the AA/A failures below (anything failing 4.5:1 also fails
  // the enhanced 7:1; ambiguous link text also fails link-purpose-link-only). These give the
  // AAA conformance target real teeth in the Assess runner.
  SC_1_4_6: () => ({ detail: 'Text contrast is below the enhanced 7:1 (AAA) threshold', impact: 'Readers with low vision benefit from the higher 7:1 ratio.', fix: 'Raise contrast to 7:1 for AAA — needs a design review.', auto: false, level: 'AAA' }),
  SC_2_4_9: () => ({ detail: 'Some link text is not fully self-describing on its own (link-only)', impact: 'AAA requires the link purpose from the link text alone.', fix: 'Rewrite links to be self-describing without surrounding context.', auto: false, level: 'AAA' }),
}
const findingDetail = (is, seed) => (FIND[is.wcag] ? FIND[is.wcag](seed) : {})

// --- Simulated document metadata + prescriptive recommendation engine -------
// Every file gets realistic crawl metadata (age, traffic, size, superseded
// detection); recommendFor() turns that + the findings into a single
// next-best-action with an effort estimate and rationale.
const REF_DAY = Date.parse('2026-06-18T00:00:00Z')
const AGE_DAYS = [4, 9, 16, 27, 41, 73, 119, 188, 274, 401, 612, 900, 1340, 2010]
// Owners carry a seniority so remediation can be prioritized by business
// importance (executive-owned + public-facing documents matter most).
const OWNERS = [
  { n: 'A. Chen', sr: 'Executive' }, { n: 'M. Okafor', sr: 'Director' }, { n: 'L. Nguyen', sr: 'Director' },
  { n: 'S. Patel', sr: 'Manager' }, { n: 'D. Weiss', sr: 'Manager' },
  { n: 'J. Romero', sr: 'Staff' }, { n: 'R. Haddad', sr: 'Staff' }, { n: 'K. Brooks', sr: 'Staff' },
]
export const SENIORITY_ORDER = ['Executive', 'Director', 'Manager', 'Staff']
const ASSIST_MIN = { CRITICAL: 12, SERIOUS: 8, MODERATE: 5, MINOR: 3 }
const dateStr = (days) => new Date(REF_DAY - days * 86400000).toISOString().slice(0, 10)
const fmtAge = (days) => days < 45 ? `${days}d ago` : days < 600 ? `${Math.round(days / 30)} mo ago` : `${(days / 365).toFixed(1)} yr ago`

// Fixability is about the rule, not the severity: alt text, language, titles,
// headings and reading order are mechanical (auto); contrast and link-purpose
// are judgement calls (human). Legal-hold docs are never auto-edited.
const NEEDS_HUMAN_WCAG = new Set(['SC_1_4_3', 'SC_2_4_4'])
// Time-based media — captions, audio description, transcripts. AI can draft them
// (ASR), but a human always finalizes; never silently auto-applied.
const MEDIA_WCAG = new Set(['SC_1_2_1', 'SC_1_2_2', 'SC_1_2_3', 'SC_1_2_5'])
function recommendFor(f) {
  const issues = f.issues || []; const n = issues.length
  const hasCritical = issues.some((x) => x.severity === 'CRITICAL')
  const mediaFinding = issues.some((x) => MEDIA_WCAG.has(x.wcag))
  const hardFinding = issues.some((x) => NEEDS_HUMAN_WCAG.has(x.wcag))
  const legalHold = (f.tags || []).includes('legal-hold')
  const sensitive = (f.tags || []).some((t) => t === 'PII' || t === 'legal-hold')
  const publicDoc = (f.tags || []).some((t) => t === 'public-facing' || t === 'high-traffic')
  const stale = f.ageDays >= 540; const lowTraffic = f.views90d < 60
  const manualMin = n ? n * 35 + 20 : 40
  const sav = (eta) => Math.max(0, Math.round((1 - eta / manualMin) * 100))

  if (f.status === 'error') {
    const eta = f.type === 'pdf' ? 45 : 30
    return { action: 'manual', mode: 'manual', confidence: null, etaMin: eta, manualMin: eta, rationale: 'File is unreadable — the engine can’t parse it. A human must re-author or re-export the source before it can be assessed.' }
  }

  if (f.status === 'certifiable') {
    if (f.superseded || (stale && lowTraffic))
      return { action: 'archive', mode: 'auto', confidence: 84, etaMin: 2, rationale: `Compliant, but ${f.superseded ? 'a newer version exists' : `last edited ${fmtAge(f.ageDays)} with ${f.views90d} views/90d`} — archive to shrink the audited estate.` }
    return { action: 'keep', mode: 'monitor', confidence: 99, etaMin: 0, rationale: `Certifiable at ${f.score}/100 with ${f.views90d} views/90d. Keep published under continuous monitoring for drift.` }
  }

  if (f.superseded)
    return { action: 'archive', mode: 'auto', confidence: 88, etaMin: 2, rationale: `Superseded by a newer version and only ${f.views90d} views/90d — archiving avoids ~${manualMin} min of remediation on a dead document.` }
  if (stale && lowTraffic && !sensitive)
    return { action: 'archive', mode: 'auto', confidence: 78, etaMin: 2, rationale: `${n} finding${n === 1 ? '' : 's'}, but last edited ${fmtAge(f.ageDays)} with ${f.views90d} views/90d — not worth ${manualMin} min of remediation.` }

  if (f.status === 'uncertain') {
    const eta = 8 + (f.skipped_rules || 0) * 4
    return { action: 'review', mode: 'assisted', confidence: 66, etaMin: eta, manualMin, savingsPct: sav(eta), rationale: `${f.skipped_rules} rule(s) couldn’t be auto-evaluated — a reviewer confirms before this can be certified.` }
  }

  // Escalate to a human only when the fix needs judgement (contrast / link), the
  // content is legally frozen, or a critical finding sits on a public, high-traffic
  // page. Everything else is mechanical and safe to auto-remediate + re-validate.
  const escalate = mediaFinding || hardFinding || legalHold || (hasCritical && publicDoc)
  if (!escalate) {
    const eta = Math.max(1, Math.round(n * (f.type === 'pdf' ? 1.6 : 1.0)))
    return { action: 'auto', mode: 'auto', confidence: 90 + (n % 9), etaMin: eta, manualMin, savingsPct: sav(eta), rationale: `All ${n} finding${n === 1 ? '' : 's'} are mechanical (alt text, headings, language, titles) — fixed automatically and re-validated. No human needed.` }
  }
  const eta = issues.reduce((a, x) => a + (ASSIST_MIN[x.severity] || 5), 0) + 6
  const reason = mediaFinding ? 'Captions / audio description are AI-drafted, then finalized by a human' : hardFinding ? 'A contrast / link-purpose finding needs a human judgement call' : legalHold ? 'Legal-hold content is never auto-edited' : 'A critical finding on a public, high-traffic page'
  return { action: 'assisted', mode: 'assisted', confidence: 70 + (n % 14), etaMin: eta, manualMin, savingsPct: sav(eta), rationale: `${reason} — a human approves the AI fix before publish.` }
}

function genCorpus() {
  const out = []; const seen = new Set(); let i = 0
  DEPARTMENTS.forEach((dept, di) => {
    const count = DEPT_COUNTS[di] || 5
    for (let j = 0; j < count; j++) {
      const type = TYPES[(di + j) % TYPES.length]
      const opts = SRC_FOR[type]; const source = opts[(di + j) % opts.length]
      const ext = EXT[type] || type
      const base = `${slug(dept)}-${NAMES[type][j % NAMES[type].length]}`
      let file = `${base}.${ext}`; let k = 2
      while (seen.has(file)) { file = `${base}-${k++}.${ext}` }
      seen.add(file)
      // "Unanalysable" ⟺ "could not open": every document the engine can't score is one
      // it couldn't read, so the could-not-open count always equals the unanalysable
      // bucket (Deva: no 9-vs-25 mismatch between the estate bar and the status donut).
      const cycle = STATUS_CYCLE[i % STATUS_CYCLE.length]
      const status = (i % 21 === 5 || cycle === 'error') ? 'error' : cycle
      const locked = status === 'error'
      const openIssue = locked ? (i % 2 ? 'password-protected' : 'unsupported / corrupt — could not open') : null
      // Keep scores consistent with status so every chart agrees: only 'certifiable'
      // docs reach the 90–100 band (status 'certifiable' ⟺ score ≥ 90), 'error' ⟺ no
      // score (unreadable), and 'uncertain'/'issues' stay in the 50–89 / below-50 bands.
      const score = status === 'certifiable' ? 100 : status === 'error' ? null : status === 'uncertain' ? 82 + (i % 6) : 48 + ((i * 13) % 38)
      const pool = ISS_POOL[type]
      const issues = status === 'issues' ? iss(pool.slice(0, 2 + (i % 2) + (i % 3 === 0 ? 1 : 0))) : status === 'uncertain' ? iss(pool.slice(0, 1)) : []
      issues.forEach((is, idx) => Object.assign(is, findingDetail(is, i * 7 + idx * 3)))
      // AAA findings are implied by their A/AA counterparts (fail 4.5:1 ⇒ fail 7:1; vague
      // link text ⇒ fail link-only), so the AAA conformance target is genuinely stricter.
      if (issues.some((x) => x.wcag === 'SC_1_4_3')) { const e = { ruleId: 'AAA-CONTRAST-7', rule_id: 'AAA-CONTRAST-7', wcag: 'SC_1_4_6', severity: 'MINOR' }; issues.push(Object.assign(e, findingDetail(e, i * 9))) }
      if (issues.some((x) => x.wcag === 'SC_2_4_4')) { const e = { ruleId: 'AAA-LINK-ONLY', rule_id: 'AAA-LINK-ONLY', wcag: 'SC_2_4_9', severity: 'MINOR' }; issues.push(Object.assign(e, findingDetail(e, i * 11))) }
      const stTag = status === 'certifiable' ? ['certified'] : status === 'uncertain' ? ['needs-review'] : status === 'issues' ? (i % 2 ? ['auto-fixable'] : ['remediation-queued']) : ['needs-review']
      const tags = [...new Set([...(DEPT_TAGS[dept] || []), ...stTag])].slice(0, 4)
      const ageDays = AGE_DAYS[(i * 5 + j) % AGE_DAYS.length]
      const hiTraffic = tags.includes('high-traffic') || tags.includes('public-facing')
      // "Superseded" = an older copy a newer version replaced. Such a document is, by
      // definition, no longer in active use, and a public/high-traffic page is never
      // archived as superseded (Deva: don't archive a doc with 237 views). So a
      // superseded doc is always quiet — we give it low views, never a high count.
      const superseded = ageDays >= 600 && i % 3 === 0 && !hiTraffic && status !== 'error'
      const views90d = superseded ? 6 + ((i * 17) % 45) : hiTraffic ? 380 + ((i * 137) % 8200) : 3 + ((i * 53) % 240)
      const isMedia = type === 'video' || type === 'audio'
      const pages = type === 'pdf' ? 6 + ((i * 11) % 52) : type === 'docx' ? 2 + ((i * 7) % 32) : type === 'pptx' ? 9 + ((i * 5) % 40) : null
      const sheets = type === 'xlsx' ? 1 + (i % 6) : null
      const durMin = type === 'video' ? 2 + ((i * 3) % 18) : type === 'audio' ? 8 + ((i * 5) % 42) : null
      const duration = isMedia ? `${durMin}:${String((i * 7) % 60).padStart(2, '0')}` : null
      const sizeKB = type === 'video' ? 24000 + durMin * 9500 : type === 'audio' ? 1400 + durMin * 950
        : type === 'pdf' ? 120 + pages * 38 : type === 'pptx' ? 800 + pages * 140 : type === 'xlsx' ? 24 + sheets * 60 : type === 'html' ? 18 + ((i * 9) % 90) : 30 + pages * 16
      const ownerObj = OWNERS[(i + di) % OWNERS.length]
      const f = {
        file, source, sourceName: SRC[source].name, department: dept, dept, type, owner: ownerObj.n, seniority: ownerObj.sr,
        status, score, compliant: status === 'certifiable', skipped_rules: status === 'uncertain' ? 2 : 0,
        engine: ENG[type], tags, issues,
        ageDays, modified: dateStr(ageDays), modifiedAge: fmtAge(ageDays), lastAccessed: dateStr(Math.max(1, Math.round(ageDays / 2.5))),
        views90d, pages, sheets, duration, sizeKB, superseded, locked, openIssue,
      }
      f.rec = recommendFor(f)
      out.push(f)
      i++
    }
  })
  return out
}
export const CORPUS = genCorpus()
export { recommendFor, fmtAge }

// Roll the per-file recommendations up into an estate-level action plan with
// total effort, automation rate, and effort saved vs. fully-manual remediation.
// The single source of truth for "documents that need a remediation action" — used by
// the plan summary, the Remediate list, the Overview "need remediation" stat & funnel,
// and the chat. Includes manual rebuild (a human re-authors it) so every surface agrees.
export const REMEDIATION_ACTIONS = ['auto', 'assisted', 'review', 'manual']
export const remediableCount = (files) => files.filter((f) => f.rec && REMEDIATION_ACTIONS.includes(f.rec.action)).length
const REMEDIATE_ACTIONS = REMEDIATION_ACTIONS
export function recommendationSummary(files) {
  const by = {}
  let remediateMin = 0, manualMin = 0
  files.forEach((f) => {
    const r = f.rec; if (!r) return
    const b = (by[r.action] = by[r.action] || { action: r.action, n: 0, min: 0 })
    b.n += 1; b.min += r.etaMin || 0
    if (REMEDIATE_ACTIONS.includes(r.action)) { remediateMin += r.etaMin || 0; manualMin += r.manualMin || 0 }
  })
  const order = ['auto', 'assisted', 'review', 'archive', 'keep', 'manual']
  const buckets = order.filter((a) => by[a]).map((a) => by[a])
  const autoN = by.auto?.n || 0
  const remN = REMEDIATE_ACTIONS.reduce((a, k) => a + (by[k]?.n || 0), 0)
  return { buckets, remediateMin, manualMin, savedMin: Math.max(0, manualMin - remediateMin), autoPct: remN ? Math.round((autoN / remN) * 100) : 0, remediableDocs: remN }
}

// Simulated continuous-monitoring state for the Monitor & Report tab. Alerts are
// deterministic and reference real corpus docs so the demo feels live.
const MON_ALERTS = [
  ['regression', 'high', 'Score dropped 100 → 82 after a Jun 14 edit — re-queued for remediation', (c) => c.find((f) => f.status === 'certifiable' && f.views90d > 1000)?.file || 'benefits-guide.pdf', '4h ago'],
  ['new-doc', 'info', 'New document detected in a watched source — auto-scanned within the hour', (c) => c.find((f) => f.sourceName)?.file || 'hr-policy-2026.docx', '6h ago'],
  ['threshold', 'med', 'Contrast regression on a public-facing page crossed the 1.4.3 threshold', (c) => c.find((f) => f.type === 'html' && f.issues.length)?.file || 'public-page.html', '11h ago'],
  ['drift', 'med', 'Alt-text removed on figure 2 during a content update — flagged', (c) => c.find((f) => f.type === 'pdf' && f.issues.length)?.file || 'care-pathway.pdf', '1d ago'],
  ['recerted', 'info', 'Auto-remediated and re-certified at 100/100 after re-scan', (c) => c.find((f) => f.status === 'issues' && (f.tags || []).includes('auto-fixable'))?.file || 'onboarding.pdf', '1d ago'],
]
// Per-source watch state for the Monitor tab — what's being polled, how often,
// and what's changed since the last sweep. Deterministic from the source list.
const WATCH_CADENCE = ['live', 'hourly', 'daily', 'weekly']
const WATCH_POLLED = ['just now', '1m ago', '3m ago', '8m ago', '14m ago', '22m ago']
const WATCH_NEXT = ['streaming', 'in 41m', 'in 18h', 'in 6d']
export function sourceWatch(sources, files) {
  const byName = {}; (files || []).forEach((f) => { (byName[f.sourceName] = byName[f.sourceName] || []).push(f) })
  return (sources || []).map((s, i) => {
    const docs = s.files || (byName[s.name] || []).length
    const ci = i % WATCH_CADENCE.length
    return {
      name: s.name, kind: s.type, id: s.id, docs,
      cadence: WATCH_CADENCE[ci], next: WATCH_NEXT[ci], polled: WATCH_POLLED[i % WATCH_POLLED.length],
      newFiles: (i * 3 + 2) % 5, changed: (i * 2 + 1) % 4, status: 'watching',
    }
  })
}

export function monitoringState(files) {
  const docs = files.length || CORPUS.length
  const sources = new Set(files.map((f) => f.sourceName)).size || 6
  const sum = recommendationSummary(files)
  return {
    enabled: true, cadence: 'weekly', nextRescan: 'in 6 days', lastRescan: '2 days ago',
    watchedDocs: docs, watchedSources: sources, coveragePct: 98, slaPct: 96,
    publicDaily: files.filter((f) => (f.tags || []).includes('public-facing')).length,
    backlogMin: sum.remediateMin, autoPct: sum.autoPct, backlogDocs: sum.remediableDocs,
    alerts: MON_ALERTS.map(([kind, sev, text, pick, when]) => ({ kind, sev, text, doc: pick(files.length ? files : CORPUS), when })),
    rules: [
      'Alert if a published document drops > 5 points on re-scan',
      'Re-scan public-facing & high-traffic documents daily',
      'New file in a watched source → scan within 1 hour',
      'Notify the document owner on any critical (Level A) regression',
      'Auto-remediate + re-certify when a fix is high-confidence',
    ],
  }
}

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

const SCANS = {}
const JOBS = {}
let seq = 0

export function simStartScan(sourceId) {
  const jid = 'simjob' + (++seq)
  const base = scoped()
  const files = sourceId === 'all' || sourceId === 'local' ? base : base.filter((f) => f.source === sourceId)
  const n = files.length
  const blocked = files.filter((f) => f.locked).length
  const sid = 'scan-' + jid
  const set = (p) => { JOBS[jid] = { phase: 'queued', files_found: 0, files_done: 0, blocked: 0, current: null, done: false, scan_id: null, ...JOBS[jid], ...p } }
  set({})
  const steps = [() => set({ phase: 'connecting' }), () => set({ phase: 'discovering', files_found: n, blocked })]
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
export const simGetScan = (sid) => SCANS[sid] || buildScan('all', scoped())
export const simListScans = () => {
  const cur = buildScan('all', scoped()).run
  const n = scoped().length
  const r = (frac) => Math.max(1, Math.round(n * frac))
  return [
    { id: 'scan-cur', completed_at: cur.completed_at, source: 'all', avg_score: cur.avg_score, files: cur.files, certifiable: cur.certifiable, uncertain: cur.uncertain, error: cur.error },
    { id: 'h3', completed_at: '2026-06-10T09:00:00', avg_score: 74, files: r(0.96) },
    { id: 'h2', completed_at: '2026-06-03T09:00:00', avg_score: 68, files: r(0.91) },
    { id: 'h1', completed_at: '2026-05-27T09:00:00', avg_score: 61, files: r(0.84) },
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
  scoped().forEach((f) => f.issues.forEach((i) => { findings[i.ruleId] = (findings[i.ruleId] || 0) + 1 }))
  const out = {}
  for (const [fmt, defs] of Object.entries(RULE_DEFS)) {
    out[fmt] = defs.map(([id, title, wcag, severity]) => ({ id, title, wcag, severity, level: AA.has(wcag) ? 'AA' : 'A', enabled: true, findings: findings[id] || 0 }))
  }
  return out
}
