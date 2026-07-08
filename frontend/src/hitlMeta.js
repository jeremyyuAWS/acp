// HITL inbox metadata — the human-review "AI Work Inbox" (Phase 1).
//
// Why a finding lands in front of a person, keyed by WCAG success criterion. These are
// exactly the criteria whose fix ACP CANNOT safely auto-apply: it either needs a
// human-authored value (alt text, captions) or a human judgement call (contrast, link
// purpose). So the escalation reason shown to the reviewer is TRUE — the AI genuinely
// exhausted its automated options first — not decorative reassurance.
//
// Severity is derived from the criterion (real WCAG weight), not a fabricated %.

const RULE_META = {
  '1.1.1': { sev: 'high', reason: 'No faithful alt-text source in the document — a person must write a meaningful description.' },
  '1.2.1': { sev: 'high', reason: 'A media alternative (transcript) must be authored by a person.' },
  '1.2.2': { sev: 'high', reason: 'Captions must be authored or verified by a person.' },
  '1.2.3': { sev: 'high', reason: 'Audio description / full text alternative must be authored by a person.' },
  '1.2.5': { sev: 'high', reason: 'Audio description must be authored by a person.' },
  '1.4.3': { sev: 'medium', reason: 'A contrast fix changes visual design — needs a human judgement call before it ships.' },
  '1.4.6': { sev: 'medium', reason: 'Enhanced-contrast fix changes visual design — needs human sign-off.' },
  '2.4.4': { sev: 'medium', reason: 'Link-purpose rewrite needs human judgement to stay accurate.' },
  '2.4.9': { sev: 'medium', reason: 'Link-text rewrite needs human judgement to stay accurate.' },
  '3.3.2': { sev: 'medium', reason: 'A form-field label needs a person to name the field meaningfully.' },
  '3.1.1': { sev: 'low', reason: 'Language could not be set deterministically — confirm the document language.' },
}

const DEFAULT_META = { sev: 'medium', reason: 'The AI drafted a fix; a person must approve it before the document can be certified.' }

// hitl_queue rows carry rule_id like "1.1.1" (WCAG SC) — normalise defensively.
const scOf = (ruleId) => String(ruleId || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''

export const metaFor = (item) => RULE_META[scOf(item?.rule_id)] || DEFAULT_META

// Severity → display + ranking. Three honest tiers from real criteria (no fabricated 4th).
export const SEV = {
  high: { rank: 3, label: 'High', color: '#B43A2A', bg: '#FBE7E2', dot: '#D0492F' },
  medium: { rank: 2, label: 'Medium', color: '#8A5A00', bg: '#FBEECB', dot: '#C98A0A' },
  low: { rank: 1, label: 'Low', color: '#475569', bg: '#ECEEF1', dot: '#8A94A6' },
}

// Priority score: severity dominates, finding count breaks ties, older first within that.
export const priorityScore = (item) => {
  const sev = SEV[metaFor(item).sev] || SEV.medium
  return sev.rank * 1000 + Math.min(999, (item.finding_count || 1))
}

// The colour the bell shows: red if anything high is pending, amber if medium, else grey.
export const bellSeverity = (items) => {
  if (items.some((i) => metaFor(i).sev === 'high')) return 'high'
  if (items.some((i) => metaFor(i).sev === 'medium')) return 'medium'
  return items.length ? 'low' : 'none'
}

export const sevOf = (item) => metaFor(item).sev
export const reasonOf = (item) => metaFor(item).reason
// Group label for the inbox: by the human-readable rule name (issue type).
export const groupLabel = (item) => item.rule_name || `WCAG ${scOf(item.rule_id) || '—'}`
