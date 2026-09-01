// Clustering for the Remediate review queue — one row per DECISION, not one row per finding.
//
// The queue's row used to be a single finding, and in the observed production run that meant 265
// rows across 265 documents, largely for the same WCAG criterion. A queue that long does not get
// reviewed; it gets rubber-stamped. This module collapses like findings into a cluster the
// reviewer inspects once and decides once.
//
// The policy it implements is the PRD's Tier C (docs/prd-remediation-autonomy-and-review.md § 4):
//
//   ### Tier C — grouped approval
//
//   Use one review decision for a cluster only when the items share:
//
//   - criterion and document format;
//   - proposal strategy and model version;
//   - evidence type;
//   - normalized before/after pattern;
//   - risk class.
//
//   The reviewer sees representative examples, cluster size, exceptions, and the scope of the
//   decision. "Approve pattern" never applies outside the displayed cluster.
//
// What this module can honestly key on, and what it cannot: the queue item carries the criterion,
// the filename (hence the format) and the remediation lane. It does NOT carry a model version, an
// evidence type or a normalized before/after pattern — those are server-side policy facts the
// client is explicitly not supposed to compute ("the UI displays the decision and its basis; the
// client does not calculate eligibility"). So the key is criterion + lane. The lane stands in for
// "risk class and proposal strategy" as far as the client can see it — an auto-applied
// deterministic fix, an AI draft awaiting approval and a manual re-author are three different
// decisions even for the same criterion. When the server starts sending a policy cluster id, that
// becomes the key and this becomes the fallback.
//
// FORMAT IS DELIBERATELY *NOT* IN THE KEY, AND THAT IS A RELAXATION OF TIER C.
// Tier C lists document format among the conditions a group must share. Keying on it was tried
// (2026-09-01) and reverted at the product owner's direction: it split the large single-criterion
// runs this module exists to collapse — a 265-finding alt-text backlog spread over .docx, .pdf and
// .pptx became three queues to work instead of one — and the reviewer's decision on such a group is
// "is ACP's alt-text drafting trustworthy here", which is not obviously a per-format question.
//
// The compensating control is disclosure, the same one used for severity below: a cluster does not
// hide the formats it spans, it STATES them, on the row and again in the batch confirmation, so a
// reviewer approving across .docx and .pdf knows that is what they are doing. If a per-format
// decision is wanted, the by-document lens and the expand control both still reach the individual
// findings. Restoring the stricter behaviour is putting `fmtOf(finding?.file)` back in the key.
//
// Kept pure and React-free, in the house idiom of remediationInboxModel.js: the component renders
// whatever this returns and derives nothing itself.

import { laneOf, isResolved, issueLabel } from './remediationInboxModel.js'
import { scOf } from './fixSummary.js'

// The lanes a batch decision may reach. Mirrors the actionable set the inbox already uses for its
// per-rule "apply to all matching" action: approve an automatic fix, apply an AI draft, or
// re-check an edited file. Everything else is deliberately out — `manual` needs a person in the
// source app, `handoff` is a fix a reviewer already rejected, and `blocked` cannot be remediated
// as-is. A grouped approval must never quietly sweep those up.
export const CLUSTER_ACTIONABLE_LANES = new Set(['review', 'apply', 'recheck'])

// The document format, from the filename extension, lowercased. Mirrors RemediationInbox's own
// `fmtOf`. Two edge cases, both harmless and both deliberate: a name with no extension yields its
// whole basename (so `Report` and `Summary` never cluster with each other, which is the safe
// outcome when the format is unknown), and a finding with no filename at all yields ''.
const fmtOf = (file) => String(file || '').split('.').pop().toLowerCase()

// The criterion a finding is about, as a bare dotted SC ("1.1.1"), or '' when it cannot be
// determined. `scOf` is used rather than the inbox model's `normSc` because the two agree on every
// well-formed id but only `scOf` VALIDATES — it ends in `match(/^\d+\.\d+\.\d+/)`, so an axe rule
// name or an empty field comes back '' instead of being passed through as if it were a criterion.
// That validation is what makes "cannot be determined" a real answer below rather than a guess.
const criterionOf = (f) => scOf(f?.rule_id ?? f?.ruleId ?? f?.wcag)

/**
 * The cluster key a finding shares with the findings that are the SAME DECISION, or null when it
 * has none and must be reviewed on its own.
 *
 * `${sc}|${laneKey}` — e.g. "1.1.1|apply".
 *
 * FORMAT IS NOT IN THE KEY — see the header. A cluster may therefore span .docx and .pdf, and each
 * row reports the formats it covers (`formats`) so that breadth is visible rather than implied.
 *
 * SEVERITY IS DELIBERATELY NOT IN THE KEY. Including it would fragment exactly the large clusters
 * this module exists to create — a run of 265 alt-text findings would shatter into CRITICAL /
 * SERIOUS / unrated shards that are, as remediation, the identical decision. Instead every cluster
 * row reports its severity MIX (`severities`), so the reviewer sees that a group of 40 contains 3
 * criticals before deciding, rather than the fact being hidden by an average.
 *
 * Returns null when the criterion cannot be determined. A finding with no criterion must never be
 * clustered with another one: the criterion is the whole basis of "these are the same decision",
 * and without it the only honest grouping is a group of one.
 */
export function clusterKeyOf(finding) {
  const sc = criterionOf(finding)
  if (!sc) return null
  return `${sc}|${laneOf(finding).key}`
}

// Severity display order for the mix a cluster row reports. Mirrors the inbox model's sort ranking
// (which is module-private there); unknown labels sort after the known ones and UNRATED sorts last,
// so iterating the returned object always reads worst-first.
const SEV_ORDER = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']
const sevRank = (s) => (s === 'UNRATED' ? 9 : (SEV_ORDER.indexOf(s) >= 0 ? SEV_ORDER.indexOf(s) : 8))

// A finding's severity bucket. A null/absent severity is counted, under 'UNRATED', rather than
// dropped — "5 of these 40 are unrated" is something the reviewer needs to see, and silently
// omitting them would make the mix's counts fail to sum to the cluster size.
const sevOf = (f) => String(f?.severity || '').trim().toUpperCase() || 'UNRATED'

/**
 * Collapse a queue into cluster rows.
 *
 * `findings` arrives ALREADY FILTERED AND SORTED by the caller (the tab filter and sortQueue have
 * run); this preserves that order rather than imposing one of its own. A cluster appears at the
 * position of its FIRST member — the same stable, order-preserving grouping `groupByDocument` does,
 * so whatever the caller sorted by still drives the top of the list.
 *
 * `opts.minSize` (default 2) is the smallest group that earns a cluster row. A group below it emits
 * one `single` row per member instead: a "cluster" of one is a lie in the reviewer's face — it
 * promises a decision that covers a pattern and then covers one finding — and it costs a row of
 * chrome to say nothing.
 *
 * Returns an array of rows, each `{ type: 'cluster', ... }` or `{ type: 'single', key, finding }`.
 */
export function clusterRows(findings, decisions = {}, opts = {}) {
  const list = Array.isArray(findings) ? findings : []
  if (list.length === 0) return []
  const minSize = Number.isFinite(opts?.minSize) ? opts.minSize : 2

  // Pass 1 — bucket by key, recording first appearance so the output order is the input order.
  // Unkeyable findings (no criterion) take their place in the order as singles immediately.
  const order = []
  const map = new Map()
  for (const f of list) {
    const key = clusterKeyOf(f)
    if (key == null) { order.push({ single: f }); continue }
    if (!map.has(key)) { map.set(key, []); order.push({ key }) }
    map.get(key).push(f)
  }

  // Pass 2 — emit. Only now is the group size known, so only now can an undersized group be
  // demoted to singles.
  const rows = []
  for (const entry of order) {
    if (entry.single) { rows.push(singleRow(entry.single)); continue }
    const items = map.get(entry.key)
    if (items.length < minSize) { for (const f of items) rows.push(singleRow(f)); continue }
    rows.push(clusterRow(entry.key, items, decisions))
  }
  return rows
}

// A finding reviewed on its own. Its key is namespaced so it can never collide with a cluster key
// (which always contains two '|' separators and never this prefix) — React keys and the call
// site's row lookups depend on that.
function singleRow(finding) {
  return { type: 'single', key: `single:${finding?.id}`, finding }
}

function clusterRow(key, items, decisions) {
  const lane = laneOf(items[0])
  const unresolved = items.filter((f) => !isResolved(f, decisions))

  // The member the reviewer will actually be shown: the first UNRESOLVED one in display order, so
  // as decisions accumulate the representative walks forward through the cluster instead of
  // stranding the pane on a finding that has already been decided. When every member is resolved
  // there is nothing left to advance to, so it falls back to the first member — never null, so the
  // call site never has to render a cluster with no example.
  const rep = unresolved.length ? unresolved[0] : items[0]

  // Distinct documents, in first-appearance order. Findings with no filename contribute no
  // document rather than an empty-string one, so `fileCount` stays an honest answer to "how many
  // documents does this one decision touch?" — the number that makes 265 rows into 1.
  const files = []
  const seen = new Set()
  for (const f of items) {
    const name = f?.file || ''
    if (!name || seen.has(name)) continue
    seen.add(name)
    files.push(name)
  }

  // The distinct formats the group spans, in first-appearance order. Since format is no longer part
  // of the key (see the header) this is the fact that keeps the breadth of a batch visible: a row
  // covering .docx and .pdf says so rather than showing whichever one happened to sort first.
  const formats = []
  const seenFmt = new Set()
  for (const f of items) {
    const x = fmtOf(f?.file)
    if (!x || seenFmt.has(x)) continue
    seenFmt.add(x)
    formats.push(x)
  }

  // The severity mix, worst-first, non-zero keys only.
  const tally = new Map()
  for (const f of items) {
    const s = sevOf(f)
    tally.set(s, (tally.get(s) || 0) + 1)
  }
  const severities = {}
  for (const s of [...tally.keys()].sort((a, b) => sevRank(a) - sevRank(b))) severities[s] = tally.get(s)

  return {
    type: 'cluster',
    key,
    sc: criterionOf(items[0]),
    // Every distinct format in the group, worst-case first-appearance order. Plural because the
    // key no longer constrains it: a cluster CAN span formats, and the row must say so.
    formats,
    laneKey: lane.key,
    lane,
    // The representative's wording, not the first member's — the reviewer should read the phrasing
    // of the one they are about to look at. The two differ the moment anything is decided.
    issue: issueLabel(rep),
    items,
    unresolved,
    files,
    severities,
    representativeId: rep?.id,
    resolvedCount: items.length - unresolved.length,
    count: items.length,
    fileCount: files.length,
  }
}

/**
 * The exact set of findings one grouped decision may reach: members that are BOTH unresolved AND in
 * an actionable lane. A `single` row, or a cluster whose lane is not actionable, reaches nothing.
 *
 * This is the scope of "Approve pattern", and the PRD is unambiguous that it "never applies outside
 * the displayed cluster" — so it is derived from the row's own members and nothing wider. A manual
 * edit, a rejected fix handed back to a person, a blocked finding and anything already decided must
 * never appear here: sweeping a decision over those is precisely the rubber-stamping this whole
 * module exists to prevent, and it would be invisible afterwards.
 *
 * Re-evaluated against the `decisions` passed in, not the snapshot the row was built with, so a
 * batch armed before an individual approval does not re-decide it.
 */
export function batchTargetsOf(row, decisions = {}) {
  if (!row || row.type !== 'cluster') return []
  if (!CLUSTER_ACTIONABLE_LANES.has(row.laneKey)) return []
  // Every member shares the row's lane by construction (the lane is in the key), so the per-member
  // lane test below is redundant — and kept anyway, so the guarantee holds for a row assembled by
  // hand or by a future keying scheme that does not put the lane in the key.
  return row.items.filter((f) => !isResolved(f, decisions) && CLUSTER_ACTIONABLE_LANES.has(laneOf(f).key))
}

/** The row containing a given finding id — cluster or single — or null. The call site needs this
 *  to keep the selected finding and the highlighted row in agreement across a re-cluster. */
export function clusterOfFinding(rows, findingId) {
  for (const row of (Array.isArray(rows) ? rows : [])) {
    if (row?.type === 'single') { if (row.finding?.id === findingId) return row }
    else if (row?.items?.some((f) => f?.id === findingId)) return row
  }
  return null
}
