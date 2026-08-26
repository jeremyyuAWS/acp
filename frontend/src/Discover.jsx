import { useCallback, useEffect, useMemo, useState } from 'react'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import WindowedRows from './WindowedRows.jsx'
import FileDrawer from './FileDrawer.jsx'
import { retentionBucket, isAcceptable } from './retentionSignal.js'
import SegmentDrawer from './SegmentDrawer.jsx'
import FolderPicker from './FolderPicker.jsx'
import SitePicker from './SitePicker.jsx'
import DispositionRules from './DispositionRules.jsx'
import { Bars } from './charts.jsx'
import { DEPARTMENTS } from './sim.js'
import { dupeCountOf, duplicateFiles } from './dedupe.js'
import { scopeSentence, isNarrowScope } from './scanScope.js'
import DiscoveryResults from './DiscoveryResults.jsx'
import DiscoverInventoryExport from './DiscoverInventoryExport.jsx'
import DiscoveryCompleteness from './DiscoveryCompleteness.jsx'
import { acknowledgementSummary } from './discoveryRecommendations.js'
import { hasClassificationData, NO_CLASSIFICATION_TITLE, NO_CLASSIFICATION_BODY,
         NO_CLASSIFICATION_WHY } from './classificationData.js'
import { loadDiscoveryInventory, mergeLifecycle, inventoryOnlyRows } from './discoveryInventory.js'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import DiscoverCompleteSummary from './DiscoverCompleteSummary.jsx'
import EstateOnlyDrawer from './EstateOnlyDrawer.jsx'
import { getScanInventory, listScanDecisions, overrideLifecycleRecommendation,
         acknowledgeScan, unacknowledgeScan } from './api.js'
import { buildUnreadableWhy } from './unreadableWhy.js'

const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
// The bucket comes from retentionSignal now, not from parsing a label back into one. Reading a
// bucket off `label.startsWith('Archive')` meant the badge TEXT was load-bearing: rewording it
// silently re-bucketed every row, and there was no `unassessed` string to match on at all.
const RET_BUCKET = retentionBucket
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30', locked: '#9a948f', delete: '#1F5FA8', unassessed: '#9a948f' }
const RET_ORDER = ['keep', 'archive', 'retain']
const RET_BADGE = { keep: ['Keep', '#E7F0DC', '#3B6D11'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', '#FAEEDA', '#854F0B'], locked: ['🔒 Could not open', '#EEEDEA', '#5F5E5A'], delete: ['Delete', '#E2EDFB', '#1F5FA8'],
  // Grey, and it says the thing rather than implying it. No lifecycle rule matched and no age
  // or usage signal reached this screen, so there is no recommendation — which is what a real
  // estate looks like today, and what a hardcoded 'Keep' was hiding.
  unassessed: ['Not assessed', '#F1EFF3', '#5F5E5A'] }
const RISK_COLOR = { PII: '#1F5FA8', 'legal-hold': '#854F0B', 'high-traffic': '#A56814' }
const TYPE_COLOR = { PDF: '#C2410C', DOCX: '#2563EB', PPTX: '#D97706', XLSX: '#15803D', HTML: '#7A5C8E', VIDEO: '#9333EA', AUDIO: '#0891B2' }
const CLASS_TAGS = ['PII', 'legal-hold', 'public-facing', 'high-traffic']
const CLASS_COLOR = { PII: '#1F5FA8', 'legal-hold': '#854F0B', 'public-facing': '#D85A30', 'high-traffic': '#A56814' }
const OVERRIDE_ACTIONS = ['keep', 'archive', 'retain', 'delete']

const SH = ({ n, label, desc, id }) => (
  <div id={id} style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '28px 0 10px', paddingTop: 16, borderTop: '1px solid var(--line)' }}>
    <b style={{ fontSize: 13.5, color: 'var(--ink)', whiteSpace: 'nowrap' }}>{n ? `${n} · ` : ''}{label}</b>
    {desc && <span className="muted" style={{ fontSize: 12 }}>{desc}</span>}
  </div>
)

// Windowed row rendering (150-at-a-time scroll sentinel) — shared with SegmentDrawer.

// Combined exposure + risk chart: top-level exposure (public-facing vs internal),
// with "internal" expandable to reveal the sensitive-content flags it carries.
function ExposureRisk({ pub, internal, internalRisk, onPick }) {
  const [open, setOpen] = useState(false)
  const mx = Math.max(1, pub.value, internal.value)
  // A clickable row used to be div[role=button] wrapping the count <button> — nested
  // interactive controls (axe: nested-interactive, WCAG 4.1.2). Now the LABEL is the
  // real button (keyboard/AT entry point) and the row div keeps a plain onClick only
  // as a wider mouse target — no role, so it isn't a second interactive control.
  const row = (label, value, color, mxx, { indent = false, chev = null, onClick, onPickCount } = {}) => {
    const labelInner = <>{chev && <span className="expchev" aria-hidden="true">{chev}</span>}{label}</>
    const inner = (<>
      {onClick
        ? <button className="critlabel" style={{ fontSize: 13, textAlign: 'left', paddingLeft: indent ? 18 : 0,
                                                 background: 'none', border: 'none', font: 'inherit', color: 'inherit', cursor: 'pointer' }}
                  onClick={(e) => { e.stopPropagation(); onClick(e) }}
                  aria-expanded={chev ? open : undefined}>{labelInner}</button>
        : <span className="critlabel" style={{ fontSize: 13, textAlign: 'left', paddingLeft: indent ? 18 : 0 }}>{labelInner}</span>}
      <span className="track"><i style={{ width: `${(value / mxx) * 100}%`, background: color, transition: 'width .9s ease' }} /></span>
      {onPickCount
        ? <button className="critn" style={{ cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted', background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit' }} onClick={(e) => { e.stopPropagation(); onPickCount() }} title="View these files">{value}</button>
        : <span className="critn">{value}</span>}
    </>)
    return onClick
      ? <div className="critrow pickrow" style={{ gridTemplateColumns: '150px 1fr 34px', width: '100%' }} onClick={onClick}>{inner}</div>
      : <div className="critrow" style={{ gridTemplateColumns: '150px 1fr 34px' }}>{inner}</div>
  }
  return (
    <div>
      {row(pub.label, pub.value, pub.color, mx, { onClick: () => onPick?.('public-facing'), onPickCount: () => onPick?.('public-facing') })}
      {row(internal.label, internal.value, internal.color, mx, { chev: open ? '▾' : '▸', onClick: () => setOpen((o) => !o), onPickCount: () => onPick?.('internal') })}
      {open && internalRisk.map((r) => <div key={r.label}>{row(r.label, r.value, r.color, internal.value, { indent: true, onClick: () => onPick?.(r.label) })}</div>)}
    </div>
  )
}

// decisions/setDecisions default to a local, throwaway useState when the caller doesn't
// pass them (matches every other optional-prop default in this file) -- App.jsx DOES pass
// its own persisted decisions state (time-travel's save/hydrate effects), which is what
// makes decide()/undoDec() below actually survive a reload instead of resetting on every
// visit to this tab, and is also what feeds the campaign "resolved" counts (ADR 0003
// Phase 4) real data instead of always reading 0.
// `me` arrived with Upload, which folded in here when v2 dropped its top-level
// tab. Both OPTIONAL: every existing caller and test constructs Discover without them, and the
// ad-hoc panel simply does not render when `me` is absent rather than throwing.
export default function Discover({ sources, files, busy, onScan, hasDriveToken = false, delegations = {}, onAdvance, progress = null, scanPct = 0, scanId = null, scope = null, decisions: decisionsProp, setDecisions: setDecisionsProp, me = null,
  hasSPToken = false, runAt = null, run = null, scanList = null, rawFiles = null, onStop = null }) {
  // discoverRunTime resolves the snapshot instant from run.discovered_at / completed_at, and this
  // component is given neither — Discover takes scanId and scope, not the run. The pieces it needs
  // are assembled here rather than threading the whole run object through a new prop; the resolver
  // falls back to the newest per-file inventory stamp when both are absent, which is the case for
  // every run listed before scan_runs.discovered_at existed.
  const runForExport = { id: scanId, discovered_at: run?.discovered_at ?? null, completed_at: run?.completed_at ?? null }
  const [sel, setSel] = useState(null)
  const [estOnlyFile, setEstOnlyFile] = useState(null)
  const [showPicker, setShowPicker] = useState(false)   // Drive folder picker modal (Choose folder to scan)
  const [showSites, setShowSites] = useState(false)     // SharePoint site picker modal
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })
  // Cross-department search + facet filters — a match auto-expands ITS department
  // (search intent implies "show me", not "let me click to reveal") without disturbing
  // which departments the user had manually opened/closed before typing.
  const sf = useSearchFilter('discover')
  const [localDecisions, setLocalDecisions] = useState({})
  const decisions = decisionsProp ?? localDecisions
  const setDecisions = setDecisionsProp ?? setLocalDecisions
  const [classState, setClassState] = useState({})
  const [editAct, setEditAct] = useState(null)
  const [seg, setSeg] = useState(null)
  // Document Location — a VIEW filter over the discovered files (PRD §4.1). It narrows what is
  // shown by source drive / folder / path; it does NOT restrict discovery, and it does not touch
  // any stored setting. Document TYPE is no longer a Discover concern — that decision moved to
  // Assess (AssessScope), so Discover shows the whole discovered estate.
  const [loc, setLoc] = useState({ source: 'all', path: '' })
  // Discovery-results acknowledgement (design board DiscoverResults, DX-07) and the per-file
  // "assess anyway" overrides it summarises. Both live here rather than inside DiscoveryResults so
  // the acknowledgement can GATE the Assess button at the foot of this tab — an acknowledgement
  // that does not gate anything is a checkbox, not a control.
  // Initialize from the persisted run.acknowledged so a page reload restores the prior decision.
  const [ackRecs, setAckRecs] = useState(() => !!(run?.acknowledged))
  const [assessAnyway, setAssessAnyway] = useState([])
  // The per-file lifecycle columns the recommendation surface is made of. They are NOT on
  // `GET /scans/{id}` (it reads file_records, which has no such columns) — they live on
  // scan_inventory, behind `GET /scans/{id}/inventory`. So Discover reads that route itself.
  //
  // `null` covers three states that must all render the same way: not asked yet, still loading,
  // and the read failed. None of them is evidence that no file was tagged, so all three leave the
  // file rows un-merged and the whole recommendation surface ABSENT. A failed read that fell back
  // to "0 tagged for archive review" would be indistinguishable from a clean estate.
  const [inv, setInv] = useState(null)
  useEffect(() => {
    let live = true
    setInv(null)      // a new scan invalidates the previous read the instant the id changes
    if (!scanId) return undefined
    loadDiscoveryInventory(scanId, getScanInventory).then((r) => { if (live) setInv(r) })
    return () => { live = false }
  }, [scanId])
  // Re-reads the same paginated inventory this effect loads. Exposed so a mutation that lands on
  // scan_inventory server-side (a lifecycle override, currently the only one) can bring its own
  // result back onto screen without a full page reload.
  const reloadInventory = useCallback(() => {
    if (!scanId) return
    loadDiscoveryInventory(scanId, getScanInventory).then((r) => setInv(r))
  }, [scanId])
  // Persist the acknowledgement decision to the backend (PRD §EX-10). Optimistic local state
  // update so the Assess gate responds immediately; the server write is best-effort and
  // a failure only means a page reload would reset the checkbox (no data is lost).
  const handleAcknowledge = useCallback(async (checked) => {
    setAckRecs(checked)
    if (!scanId) return
    try {
      if (checked) await acknowledgeScan(scanId)
      else await unacknowledgeScan(scanId)
    } catch { /* non-fatal — local state is already updated */ }
  }, [scanId])

  // Lifecycle rules #8: POST the override, then reload the inventory so the recorded reason
  // reaches this screen the same way every other lifecycle fact does — through the same
  // all-or-nothing paginated read, never patched into local state (a locally-patched row would
  // outrun the server on a failed write and there would be no way to tell the two apart).
  const overrideRecommendation = useCallback(async (file, reason) => {
    if (!scanId) return false
    try {
      await overrideLifecycleRecommendation(scanId, file, reason)
      reloadInventory()
      return true
    } catch {
      return false
    }
  }, [scanId, reloadInventory])
  // Un-merged when the read has not completed — mergeLifecycle passes `files` straight through.
  const estateFiles = useMemo(() => mergeLifecycle(files, inv), [files, inv])
  // Images, videos, and unsupported formats discovery listed but never opened — not assessable.
  // Returns [] when the inventory read is incomplete or missing (same guard as mergeLifecycle).
  const nonAssessable = useMemo(() => inventoryOnlyRows(files, inv), [files, inv])

  // WHY the unreadable files could not be read. The reason is recorded per file in the scan's
  // decision log (`scan.file_error`) and was reachable only one drawer at a time; the aggregate
  // breakdown on this screen read its reason off the file ROW, where the backend puts nothing, so
  // it said "no reason was recorded" over a scan that had recorded every one.
  //
  // Same three-states-render-the-same rule as `inv` above: not asked, loading and failed all leave
  // this null, and a null `reasonOf` restores exactly the previous behaviour — the buckets fall
  // back to "not recorded", which is the honest answer while nothing has been read.
  const [errLog, setErrLog] = useState(null)
  useEffect(() => {
    let live = true
    setErrLog(null)
    if (!scanId) return undefined
    listScanDecisions(scanId).then((rows) => { if (live) setErrLog(Array.isArray(rows) ? rows : null) })
    return () => { live = false }
  }, [scanId])
  const why = useMemo(
    () => (errLog ? buildUnreadableWhy(errLog, estateFiles) : null),
    [errLog, estateFiles],
  )

  // The folder portion of a file's path, when it carries one — real scans name files by path
  // (`HR/policies/leave.docx`), SIM by bare filename. Empty string when there is no folder.
  const folderOf = (f) => {
    const p = f.folder || f.path || f.file || ''
    const i = String(p).lastIndexOf('/')
    return i > 0 ? String(p).slice(0, i) : ''
  }
  const sourceNames = [...new Set(files.map((f) => f.sourceName).filter(Boolean))].sort()
  const locMatch = (f) => {
    if (loc.source !== 'all' && f.sourceName !== loc.source) return false
    const q = loc.path.trim().toLowerCase()
    if (q) {
      const hay = `${f.sourceName || ''} ${folderOf(f)} ${f.file || ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  }
  const locActive = loc.source !== 'all' || !!loc.path.trim()
  // Everything downstream (the charts, the department list, the search bar) reads the
  // location-filtered view, so a narrowed location narrows the whole Discover surface coherently.
  const visibleFiles = locActive ? files.filter(locMatch) : files
  const hiddenByLoc = files.length - visibleFiles.length
  // `files` is `file_records` (App.jsx's scan?.files), which ADR 0020 leaves empty until Assess
  // actually opens each document — it is NOT what Discover found. Before Assess ever runs, or
  // mid-run, files.length reads as 0-or-partial while the estate genuinely holds scope.inventory
  // .discovered documents (found live 2026-08-22: a fresh Discover-only scan showed "0 documents
  // discovered" here while the very same screen's own breakdown, sourced from scope.inventory,
  // correctly said 170). Falls back to files.length so a scan predating scope.inventory — nothing
  // recorded the estate size any other way — still shows its historical count instead of 0.
  const discoveredCount = scope?.inventory?.discovered ?? files.length
  // Stated against the raw discovered count — the estate line describes discovery, which the
  // location view filter never restricts.
  const scopeLine = scopeSentence(scope, discoveredCount)
  const ownerOf = (f) => delegations[f.owner] || f.owner
  const isDelegated = (f) => !!delegations[f.owner]

  const groups = {}
  visibleFiles.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  // Real scans never set f.locked (SIM-only flag) — a file the engine could not
  // open surfaces as status 'error' with no score. Both are the same bucket to a
  // reviewer: "we could not read this one".
  const isUnreadable = (f) => f.locked || f.status === 'error'
  const lockedCount = visibleFiles.filter(isUnreadable).length

  const PLUM = '#7a5c8e'
  const tagsOf = (f) => classState[f.file]?.tags ?? classTags(f).filter((t) => CLASS_TAGS.includes(t))
  const byType = Object.entries(visibleFiles.reduce((m, f) => { const k = (f.type || '').toUpperCase(); m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: TYPE_COLOR[label] || PLUM }))
  const internalDocs = visibleFiles.filter((f) => !tagsOf(f).includes('public-facing'))
  const exposurePub = { label: 'public-facing · high-traffic', value: visibleFiles.length - internalDocs.length, color: '#D85A30' }
  const exposureInternal = { label: 'internal', value: internalDocs.length, color: '#9a948f' }
  const internalRisk = ['PII', 'legal-hold', 'high-traffic'].map((t) => ({ label: t, value: internalDocs.filter((f) => tagsOf(f).includes(t)).length, color: RISK_COLOR[t] })).filter((d) => d.value)

  // DID CLASSIFICATION REACH THIS SCREEN AT ALL? False on every real scan today: file_records
  // carries no department and no tags, and get_scan projects that table alone. False means the
  // triage surface is OMITTED, not zeroed — see classificationData.js.
  //
  // Checked against `rawFiles` (the PRE-annotation records App.jsx passes straight from
  // get_scan), never against `files` (POST-annotation). ontology.annotate() back-fills
  // department/tags from a filename guess on every file that lacks them — real files always
  // lack them, so annotate() ALWAYS gives every real file a non-empty department, and checking
  // the annotated array made this read "classified" on every real scan (found live 2026-08-21:
  // the "How this works" copy and the exposure chart claimed a Deep-scan classification that
  // never ran). `rawFiles` defaults to `files` so a caller that never learned about this
  // distinction — every existing test — keeps today's behavior exactly.
  const classified = hasClassificationData(rawFiles ?? files)
  const isConfirmed = (f) => !!classState[f.file]?.confirmed
  const toggleTag = (f, t) => setClassState((s) => { const cur = s[f.file]?.tags ?? tagsOf(f); const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]; return { ...s, [f.file]: { tags: next, confirmed: false } } })
  const confirmClass = (f) => setClassState((s) => ({ ...s, [f.file]: { tags: tagsOf(f), confirmed: true } }))
  const classConfirmed = files.filter(isConfirmed).length

  const dupeCount = dupeCountOf(files)

  // ONLY ROWS WITH A REAL RECOMMENDATION count toward "needs a decision". `!f.locked` used to be
  // the whole filter, which is why an all-'unassessed' estate (no disposition rules configured —
  // the common case for a real deployment) could still leave Assess reachable: RET_BUCKET was
  // hardcoded 'keep', so every row silently HAD a recommendation to bulk-accept. Now that a row can
  // genuinely have none, gating on isAcceptable is what keeps that path open rather than trading
  // one defect (a fabricated Keep) for a worse one (Discover permanently blocking Assess whenever
  // nothing was configured to make a recommendation).
  const actionable = files.filter(isAcceptable)
  const effAction = (f) => { const d = decisions[f.file]; return d?.state === 'override' ? d.action : RET_BUCKET(f) }
  const decide = (f, dec) => { setDecisions((s) => ({ ...s, [f.file]: dec })); setEditAct(null) }
  const undoDec = (f) => setDecisions((s) => { const n = { ...s }; delete n[f.file]; return n })
  const dcount = (st) => actionable.filter((f) => decisions[f.file]?.state === st).length

  // Facets for the shared bar. tag/status read live component state (classState,
  // decisions), so the chips track the user's classification work as it happens.
  const SF_FACETS = [
    { key: 'tag', label: 'Tag', get: (f) => tagsOf(f) },
    { key: 'type', label: 'Type', get: (f) => (f.type || '').toUpperCase() },
    { key: 'status', label: 'Status', get: (f) => (f.locked ? ['locked'] : [isConfirmed(f) ? 'classified' : 'unclassified', decisions[f.file] ? 'decided' : 'undecided']) },
    { key: 'source', label: 'Source', get: (f) => f.sourceName },
  ]
  const sfMatch = matchesFilters(sf, SF_FACETS, (f) => f.file)
  const pendingActions = actionable.length - dcount('accepted') - dcount('override')
  // BULK ACCEPT SKIPS ROWS WITH NOTHING TO ACCEPT. This is where the hardcoded `Keep` did the most
  // damage: one click recorded an accepted lifecycle decision for every document in the estate, on a
  // recommendation nobody produced, and the resulting audit trail is indistinguishable from a
  // reviewer who actually looked. Silent bulk sign-off over an unmeasured default is worse than the
  // wrong badge that produced it.
  // `actionable` is already isAcceptable-filtered, so this is `actionable` under a name that
  // reads correctly at each call site — kept separate rather than aliased so a future change to
  // one is not silently a change to the other's meaning.
  const acceptable = () => actionable
  const acceptAll = () => setDecisions((s) => { const n = { ...s }; acceptable().forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })
  // What the acknowledgement covers — null when the lifecycle rule pass did not reach this screen
  // or matched nothing, in which case there is nothing to acknowledge and nothing to gate.
  const recsToAck = acknowledgementSummary(estateFiles, assessAnyway)
  const needsAck = !!recsToAck && !ackRecs

  // Inventory/Classify/Action are no longer formally separated tabs — one dept-grouped
  // list shows the file, its classification tags (colorful pills), and its lifecycle
  // action together, so a reviewer tags AND decides in the same row instead of hopping
  // between sections.
  const compBar = (fs) => {
    const c = { keep: 0, archive: 0, retain: 0 }; fs.forEach((f) => { const a = effAction(f); if (c[a] != null) c[a] += 1 })
    return <span className="deptbar" aria-hidden="true">{RET_ORDER.map((k) => c[k] ? <i key={k} style={{ width: `${(c[k] / fs.length) * 100}%`, background: RET_COLOR[k] }} title={`${c[k]} ${k}`} /> : null)}</span>
  }
  const deptNote = (fs) => {
    const tot = fs.filter((f) => !f.locked).length
    const classified = fs.filter(isConfirmed).length
    const decided = fs.filter((f) => decisions[f.file] && !f.locked).length
    return `${classified}/${tot} classified · ${decided}/${tot} decided`
  }

  const deptList = () => deptOrder.map((d) => {
    const deptFiles = groups[d]
    const fs = sf.active ? deptFiles.filter(sfMatch) : deptFiles
    if (sf.active && !fs.length) return null   // hide departments with no match while filtering
    const isOpen = sf.active ? true : open.has(d)
    return (
      <div className="deptcard" key={d}>
        <button className="deptheader" onClick={() => toggle(d)} aria-expanded={isOpen} disabled={sf.active}>
          <span className="deptchev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
          <span className="deptname">{d}</span>
          <span className="muted deptcount">
            {sf.active ? `${fs.length} of ${deptFiles.length} match` : `${fs.length} docs · `}
            {!sf.active && <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{deptNote(fs)}</b>}
          </span>
          {!sf.active && compBar(fs)}
        </button>
        {isOpen && (
          <div className="depttable">
            <WindowedRows items={fs} renderRow={(f) => {
              const meta = (
                <div className="filemeta">
                  <span className="srcpill">{f.sourceName}</span>
                  {f.locked
                    ? <span className="lockflag">🔒 {f.openIssue}</span>
                    : <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}
                        {isDelegated(f) && <span className="badge" style={{ marginLeft: 6, background: '#E7F0DC', color: '#3B6D11', fontSize: 10 }}>delegated → {ownerOf(f)}</span>}
                      </span>}
                </div>
              )
              return (
                <div className="drow" key={f.file}>
                  <div className="dmain">
                    <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                    {meta}
                  </div>
                  {f.locked && (() => {
                    const [l, bg, fg] = RET_BADGE.locked
                    return <span className="badge" style={{ background: bg, color: fg }}>{l}</span>
                  })()}
                  {!f.locked && (() => {
                    const a = effAction(f); const [l, bg, fg] = RET_BADGE[a]; const dec = decisions[f.file]
                    const bothPending = !isConfirmed(f) && !dec
                    return (
                      <div className="drowdecide">
                        <div className="classctl">
                          <span className="classchips">
                            {CLASS_TAGS.map((t) => { const on = tagsOf(f).includes(t); return (
                              <button key={t} className={on ? 'classchip on' : 'classchip'} style={on ? { background: CLASS_COLOR[t] + '22', color: CLASS_COLOR[t], borderColor: CLASS_COLOR[t] + '55' } : undefined} aria-pressed={on} onClick={() => toggleTag(f, t)} title={on ? `Remove ${t}` : `Add ${t}`}>{on ? '✓ ' : '+ '}{t}</button>
                            ) })}
                            {f.superseded && <span className="classchip on" style={{ background: '#EEEDFE', color: '#3C3489', borderColor: '#cdc9f0', cursor: 'default' }}>superseded</span>}
                          </span>
                          {isConfirmed(f) && <span className="dectag ok">✓ classified</span>}
                        </div>
                        <div className="actctl">
                          <span className="badge" style={{ background: bg, color: fg, borderLeft: `3px solid ${RET_COLOR[a]}` }} title={f.rec?.rationale || ''}>{l}</span>
                          {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                          {dec?.state === 'override' && <span className="dectag ov">changed</span>}
                          {editAct === f.file ? (
                            <span className="modchips">
                              {OVERRIDE_ACTIONS.map((a2) => <button key={a2} className="modchip" style={{ color: RET_COLOR[a2] }} onClick={() => decide(f, a2 === RET_BUCKET(f) ? { state: 'accepted' } : { state: 'override', action: a2 })}>{RET_BADGE[a2][0]}</button>)}
                              <button className="modchip cancel" onClick={() => setEditAct(null)}>cancel</button>
                            </span>
                          ) : !dec ? (
                            <span className="decctl">
                              {/* NO ACCEPT CONTROL WITHOUT A RECOMMENDATION. Accepting `Not assessed`
                                  would record a human decision over nothing — and it is that record,
                                  not the badge, which a later audit reads as "a person reviewed this
                                  and agreed". Setting one is still offered: a reviewer who knows the
                                  answer can supply it, which is the opposite of rubber-stamping a
                                  default. */}
                              {!isAcceptable(f)
                                ? <button className="decbtn ed" title="No recommendation was produced for this document — set one"
                                          onClick={() => setEditAct(f.file)}>set action</button>
                                : bothPending
                                  ? <button className="decbtn ok wide" title="Confirm classification & accept action" onClick={() => { confirmClass(f); decide(f, { state: 'accepted' }) }}>✓ accept both</button>
                                  : <button className="decbtn ok" title="Accept recommendation" onClick={() => decide(f, { state: 'accepted' })}>✓</button>}
                              {isAcceptable(f) && <button className="decbtn ed" title="Change action" onClick={() => setEditAct(f.file)}>✎</button>}
                              {!isConfirmed(f) && !bothPending && <button className="decbtn ok wide" title="Confirm classification" onClick={() => confirmClass(f)}>tags ✓</button>}
                            </span>
                          ) : <button className="decbtn undo" title="Undo action" onClick={() => undoDec(f)}>↺</button>}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )
            }} />
          </div>
        )}
      </div>
    )
  })

  return (
    <>
      {/* REMOVED: the "1 · Choose what to assess · criteria and file types, before you scan" panel.
          Discover asks ONE question — WHERE to inventory. Which document types and which WCAG
          criteria are Assess's question, and AssessSetup now owns both on the Assess tab, so this
          asked the same thing twice with two answers.

          Worse, it asked at the wrong stage. Criteria and formats do not scope DISCOVERY at all —
          discovery is metadata-only (ADR 0020) and lists every file regardless — so "before you
          scan" invited a reader to believe a criterion choice here narrowed what got listed. That
          is the same Discover/Assess conflation #532 began removing and #549 fixed in the wizard
          hint, still live on the tab itself.

          The FILE is left in place, but be clear about its state: ScanScope.jsx is now mounted
          NOWHERE. It is not behind Platform settings — scopeStep.test.js pins that Settings must
          not carry it, precisely so one setting never has two editors. Deleting it is a separate
          decision from removing this panel, so it is flagged rather than taken here, and
          scopeStep.test.js records the orphan so it cannot be mistaken for live code. */}

      {/* The per-user twin of the scope step (ADR 0035 stage 2): the org scope above is the mandate
          (owner-only); here any signed-in reviewer widens it for their OWN scans. Collapsed by default
          so it does not compete with the primary scope step; kept beside it so scope is reasoned about
          in one place. Widen-only, enforced server-side. */}
      {/* REMOVED: the per-user scope panel that widened which WCAG criteria a reviewer's own scans
          would be assessed against.

          Same conflation as the org-level picker taken off this tab earlier today, and it was the
          first thing on the page. Discover asks ONE question — WHERE to inventory. Which criteria
          apply is Assess's question, and AssessSetup owns it there. Discovery is metadata-only
          (ADR 0020) and lists every file whatever the criteria say, so a criterion choice here
          never changed what got listed.

          The component is kept and mounted nowhere, per the standing rule in CLAUDE.md; the orphan
          is recorded in discoverScopePanelsRemoved.test.jsx so it cannot be read as unfinished. */}

      {/* The estate-coverage funnel is NOT on this tab any more. It partitioned the estate a second
          time, directly above a panel that partitions it — and its stages ran discovered →
          assessable → REMEDIABLE, which is the reading this file already rejected a few hundred
          lines down: "Rubric scores and remediation state used to appear here, which read as 'the
          scan already assessed and remediated your documents' — it does neither."

          It is not retired. EstateCoverage still mounts on Overview, which is where a cross-stage
          funnel belongs, so nothing was lost from the product — only from the tab that answers one
          question. The one figure it contributed that DiscoveryResults lacked, the eligible
          PERCENTAGE, moved onto the headline tile beside the count. */}

      {/* Discovery-specific progress panel — only while a scan is running on this tab.
          Replaces the shared .scanprog banner (suppressed by App.jsx when view==='discover')
          so the Discover tab stays scoped to inventory. No assessment workers, WCAG content,
          or findings appear here. */}
      <DiscoverRunProgress progress={progress} busy={busy} onStop={onStop} onContinue={onAdvance} sources={sources} inv={inv} />

      {/* Completion summary: immutable snapshot of what was found, with the "Continue" CTA.
          Appears only after discovery finishes — DiscoverRunProgress hides itself at that point. */}
      {!busy && run?.discovered_at && (
        <DiscoverCompleteSummary
          discoveredCount={discoveredCount}
          assessableCount={Math.max(0, discoveredCount - nonAssessable.length - lockedCount)}
          nonAssessableCount={nonAssessable.length}
          lockedCount={lockedCount}
          lifecycleRulesCount={inv?.rows
            ? new Set(inv.rows.map((r) => r.lifecycle_rule_id).filter(Boolean)).size
            : null}
          onAdvance={onAdvance}
          pendingActions={pendingActions}
          needsAck={needsAck}
        />
      )}

      <div className="estatebar">
        <div>
          <b>{discoveredCount} documents</b> discovered across {sources.length} sources · {Object.keys(groups).length} departments
          {busy && (
            <span className="muted" style={{ marginLeft: 8, fontSize: 12, fontStyle: 'italic' }}>
              Counts are provisional until discovery completes
            </span>
          )}
          {/* WHAT the count counts. "N documents discovered" alone is what let a one-folder scan
              reporting 1 and a whole-Drive scan reporting 8 look like the same measurement of a
              shrinking estate (see scanScope.js). Rendered for every recorded scope, not only
              the narrow ones — a caveat that appears only sometimes teaches a reader to read its
              absence as "whole estate", and it is absent on every pre-existing scan. */}
          {scopeLine && (
            <div className={isNarrowScope(scope) ? 'scopewarn' : 'muted'} style={{ marginTop: 3, fontSize: 12.5 }}
                 role={isNarrowScope(scope) ? 'status' : undefined}>
              {isNarrowScope(scope) ? '⚠ ' : ''}{scopeLine}
              {scope?.kind === 'folder' && hasDriveToken && !busy && (
                <> <button className="linklike" onClick={() => onScan('drive')}
                           title="Re-run discovery with no folder restriction, across your whole Drive">
                  Scan my whole Drive instead
                </button></>
              )}
            </div>
          )}
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata, proposes a classification &amp; a lifecycle action — you confirm or override{lockedCount ? <> · <span className="lockwarn">🔒 {lockedCount} could not be opened (password-protected / unsupported)</span></> : null}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {hasDriveToken && (
            <button className="ghost" disabled={busy} onClick={() => setShowPicker(true)}
                    title="Browse your Google Drive and scan just one folder (and its subfolders)">
              Choose folder to scan…
            </button>
          )}
          {/* Gated on the SharePoint token for the same reason the Drive button is gated on its
              own: offering a picker that cannot authenticate produces an error where a missing
              button would have produced an obvious next step (connect the source). */}
          {hasSPToken && (
            <button className="ghost" disabled={busy} onClick={() => setShowSites(true)}
                    title="Choose a SharePoint site — every document library on it is scanned">
              Choose SharePoint site…
            </button>
          )}
          <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
        </div>
      </div>

      {showPicker && (
        <FolderPicker
          onScan={(folder) => { setShowPicker(false); onScan('drive', folder) }}
          onClose={() => setShowPicker(false)} />
      )}

      {/* The site id travels as `folder`, which is what the backend reads it as — _list treats
          `folder` as the site for source='sharepoint' (#156). One parameter, not two. */}
      {showSites && (
        <SitePicker
          onScan={(siteId) => { setShowSites(false); onScan('sharepoint', siteId) }}
          onClose={() => setShowSites(false)} />
      )}

      {/* REMOVED on request: the ad-hoc single-file panel that wrapped the Upload component.

          Its summary text and the JSX tag are deliberately not quoted here. v2Simplification's
          case reads this file RAW, and a comment quoting what it removed matches its own
          protected explanation — the fifth time that shape has failed on correct code tonight.

          Be clear about what that costs, because it was the ONLY mount of Upload in the app:
          ad-hoc single-file assessment is gone from the product, not merely tidied off this
          screen. Upload folded in here when v2 dropped its top-level tab (#151), so there is no
          other route to it.

          Upload.jsx and its tests are deliberately NOT deleted — restoring this is one commit, and
          deleting a working capability is a bigger decision than removing a panel. It is now
          mounted nowhere; discoverUploadRemoved.test.jsx records that so it cannot be mistaken for
          live code. */}

      {/* Deva #3 — define archival/deletion rules right here in Discover. The rules run at discovery
          time and mark matched files as candidates; Assess excludes them by default. */}
      <DispositionRules />

      {/* Discovery results (approved board `DiscoverResults.dc.html`): what the run found, what it
          could not read, which files a lifecycle rule recommended for review and which rule said
          so, the acknowledgement that gates Assess, and the reconciliation that shows every
          discovered file landing in exactly one bucket. Sections whose data has not reached this
          screen render NOTHING — never a zero. */}
      {/* IS THIS THE WHOLE ESTATE? ABOVE the results, not below them.
          
          It sat under the export first, reasoning that a reader should meet the caveat before the
          download button. That was the wrong reader: the one who matters reads the COUNTS, and by
          the time a caveat appears beneath them they have already believed the numbers. A caveat
          under the figure it qualifies is decoration.

          Self-guarding: it renders nothing when it has nothing to say. A panel appearing on every
          run to announce "this might be incomplete" would be true of all software, useful to
          nobody, and would train the reader to skip the box that one day carries a real signal. */}
      <DiscoveryCompleteness run={run} scanList={scanList}
                             onRelist={() => onScan && onScan(run?.source === 'sharepoint' ? 'sharepoint' : 'drive')} />

      <DiscoveryResults files={estateFiles} inventory={scope?.inventory || null} invRows={inv?.rows ?? null} scopeLine={scopeLine} runAt={runAt}
                        reasonOf={why ? why.reasonOf : undefined}
                        reasonSampleOf={why ? why.sampleOf : null}
                        reasonFetchLikely={why ? why.fetchLikely : null}
                        acknowledged={ackRecs} onAcknowledge={handleAcknowledge}
                        overrides={assessAnyway} onOverridesChange={setAssessAnyway}
                        onOverrideRecommendation={overrideRecommendation}
                        actor={me?.email || me?.name || null} scanId={scanId} />

      {/* TAKE THE INVENTORY OUT OF ACP, DATED. Metadata-only CSV/JSON for the compliance reader,
          with the snapshot instant on every row — a count is a fact about a boundary at an
          instant, and a CSV outlives the screen that explained it.

          It self-guards: no inventory to export renders nothing, and it says "not recorded"
          rather than inventing a date for a run the backend never stamped. */}
      <DiscoverInventoryExport scanId={scanId} run={runForExport}
                               inventory={scope?.inventory || null} />

      {files.length === 0 ? (
        <p className="muted" style={{ marginTop: 20 }}>No documents yet — run a scan from Sources.</p>
      ) : (() => {
        const totalWidth = files.length || 1
        return (
        <>
          <SH id="disc-documents" label="Documents"
              desc={classified
                ? 'grouped by department · click to expand · tag &amp; decide right in the row'
                : 'click to expand · every discovered file, listed'} />

          {/* Document Location — a view filter over source drive / folder / path (PRD §4.1). It
              narrows only what is shown here; discovery still found every file above, and no
              stored setting changes. Document type is chosen in Assess, not here. */}
          <div className="doclocbar" role="group" aria-label="Document location filter">
            <span className="muted doclocbar-lbl">Document location</span>
            <select aria-label="Filter by source" value={loc.source}
                    onChange={(e) => setLoc((s) => ({ ...s, source: e.target.value }))}>
              <option value="all">All sources</option>
              {sourceNames.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <input type="text" aria-label="Filter by folder or path" placeholder="folder or path…"
                   value={loc.path} onChange={(e) => setLoc((s) => ({ ...s, path: e.target.value }))} />
            {locActive && (
              <>
                <span className="muted doclocbar-count" role="status">
                  {visibleFiles.length} of {files.length} shown{hiddenByLoc ? ` · ${hiddenByLoc} hidden by location` : ''}
                </span>
                <button className="linklike" onClick={() => setLoc({ source: 'all', path: '' })}>Clear</button>
              </>
            )}
          </div>

          <SearchFilterBar ctl={sf} items={visibleFiles} facets={SF_FACETS}
                           placeholder="Search all departments by filename…" noun="documents" />

          <div className="typelegend">
            <span className="muted" style={{ fontSize: 12, marginRight: 2 }}>document types · click to view:</span>
            {byType.map((t) => (
              <button key={t.label} className="typekey" onClick={() => setSeg({ title: `${t.label} documents`, subtitle: `${t.value} of ${files.length} · across all departments`, files: files.filter((f) => (f.type || '').toUpperCase() === t.label) })}>
                <i style={{ background: t.color }} aria-hidden="true" />{t.label}<span className="muted"> · {t.value}</span>
              </button>
            ))}
          </div>

          {/* Discovery facts only. Rubric scores and remediation state used to appear here,
              which read as "the scan already assessed and remediated your documents" — it
              does neither. Those belong to the Assess and Remediate steps that own them. */}
          <div className="filesplit" role="region" aria-label="File breakdown">
            <div className="filesplit-item">
              <span className="filesplit-n" style={{ color: 'var(--ink)' }}>{files.length}</span>
              <span className="filesplit-lbl">total scanned</span>
              <div className="filesplit-bar"><i style={{ width: '100%', background: '#7a5c8e' }} /></div>
            </div>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: dupeCount ? 'pointer' : 'default' }}
                    disabled={!dupeCount}
                    onClick={() => dupeCount && setSeg({ title: 'Duplicate uploads', subtitle: `${dupeCount} extra copies of another document`, files: duplicateFiles(files) })}>
              <span className="filesplit-n" style={{ color: '#854F0B' }}>{dupeCount}</span>
              <span className="filesplit-lbl">duplicates</span>
              <div className="filesplit-bar"><i style={{ width: `${(dupeCount / totalWidth) * 100}%`, background: '#854F0B' }} /></div>
            </button>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: lockedCount ? 'pointer' : 'default' }}
                    disabled={!lockedCount}
                    onClick={() => lockedCount && setSeg({ title: 'Password-protected / unreadable', subtitle: `${lockedCount} files the engine could not open`, files: files.filter(isUnreadable) })}>
              <span className="filesplit-n" style={{ color: '#75706A' }}>{lockedCount}</span>{/* ≥4.5:1 on white (was #9a948f · 3.0) */}
              <span className="filesplit-lbl">🔒 unreadable</span>
              <div className="filesplit-bar"><i style={{ width: `${(lockedCount / totalWidth) * 100}%`, background: '#9a948f' }} /></div>
            </button>
          </div>

          <div style={{ fontSize: 12.5, color: 'var(--ink)', background: '#F1EFF3', border: '1px solid var(--line)',
                        borderRadius: 8, padding: '9px 12px', margin: '0 0 12px', lineHeight: 1.5 }}>
            {/* The claims here have to match what actually reached the screen. This box used to
                state that department and exposure "are inferred from the file name" — nothing does
                that for a real file, and the box sat above a grouping that had put the whole estate
                in one Unassigned bucket. A help text explaining a mechanism that does not run is
                worse than none: it sends a reader looking for the naming convention that would
                make it work. */}
            {classified ? (
              <>
                <b>How this works:</b> <strong>document type</strong> comes from the file format ·
                <strong> department</strong> &amp; <strong>exposure</strong> come from the classification
                on each document · <strong>sensitive-data</strong> flags come from the scan (Deep scan) —
                confirm or correct any tag below, your edits win over the agent's guess. Each row also
                carries the agent's recommended{' '}
                <strong>lifecycle action</strong> (keep / archive / retain / delete) — accept it, override it, or use
                <strong> ✓ accept both</strong> to sign off on the tags &amp; the action in one click.
              </>
            ) : (
              <>
                <b>How this works:</b> <strong>document type</strong> comes from the file format ·
                every discovered file is listed below with the metadata discovery recorded. Each row
                carries the agent's recommended <strong>lifecycle action</strong> (keep / archive /
                retain / delete) — accept it or override it. Department and sensitivity are not
                collected yet, so there is nothing to confirm on this estate.
              </>
            )}
          </div>
          <div className="chartrow">
            {/* THE EXPOSURE CHART IS ABSENT, NOT ZEROED, when nothing classified this estate.
                Rendered unclassified it read "100% internal" with every risk flag at zero — each
                number true, and the reading false. "0 legal-hold" states that this estate holds no
                documents under legal hold, which is a finding nobody obtained, on the screen a
                compliance reader opens precisely to find them. Same rule as hasLifecycleData. */}
            {!classified ? (
              <section className="panel">
                <h2>By exposure &amp; risk</h2>
                <p style={{ fontSize: 13, fontWeight: 650, margin: '10px 0 4px' }}>
                  {NO_CLASSIFICATION_TITLE}
                </p>
                <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.55 }}>
                  {NO_CLASSIFICATION_BODY}
                </p>
                <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', lineHeight: 1.5 }}>
                  {NO_CLASSIFICATION_WHY}
                </p>
              </section>
            ) : (
            <section className="panel"><h2>By exposure &amp; risk <span className="muted" style={{ fontWeight: 400 }}>· expand internal to see its risk flags</span></h2>
              <ExposureRisk pub={exposurePub} internal={exposureInternal} internalRisk={internalRisk} onPick={(tag) => {
                const filtered = tag === 'public-facing'
                  ? visibleFiles.filter((f) => tagsOf(f).includes('public-facing'))
                  : tag === 'internal'
                    ? visibleFiles.filter((f) => !tagsOf(f).includes('public-facing'))
                    : visibleFiles.filter((f) => !tagsOf(f).includes('public-facing') && tagsOf(f).includes(tag))
                setSeg({ title: `${tag} documents`, subtitle: `${filtered.length} file${filtered.length !== 1 ? 's' : ''}`, files: filtered })
              }} />
              <p className="muted ppfoot">Public-facing pages (also your high-traffic content) are the top legal-exposure surface under ADA / EAA. The {exposureInternal.value} internal documents carry the PII &amp; legal-hold content that matters most if mishandled.</p>
            </section>
            )}
            <section className="panel"><h2>By document type</h2><Bars items={byType} cols="70px 1fr 30px" /></section>
          </div>
          <div className="hitlbar">
            <span className="muted">Human-in-the-loop ·{' '}
              <b style={{ color: 'var(--ink)' }}>{classConfirmed}</b> of {files.length} classified ·{' '}
              <b style={{ color: 'var(--ink)' }}>{dcount('accepted')}</b> accepted · <b style={{ color: 'var(--ink)' }}>{dcount('override')}</b> changed
            </span>
          </div>
          {locActive && visibleFiles.length === 0
            ? <p className="muted" style={{ marginTop: 14 }}>No documents match this location filter. <button className="linklike" onClick={() => setLoc({ source: 'all', path: '' })}>Clear the filter</button> to see all {files.length}.</p>
            : deptList()}
        </>
        )
      })()}

      {(files.length > 0 || nonAssessable.length > 0) && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12,
                      margin: '20px 0 4px', paddingTop: 14, borderTop: '1px solid var(--line)' }}>
          {pendingActions > 0 ? (
            <>
              <span className="muted" style={{ fontSize: 13 }}>{pendingActions} action{pendingActions === 1 ? '' : 's'} pending</span>
              {/* Absent when there is nothing to accept, rather than a button that silently does
                  nothing. Its count is stated so the number a reviewer signs off on is the number
                  they can see, not the estate size. */}
              {acceptable().length > 0 && (
                <button className="ghost" onClick={acceptAll}>
                  ✓ Accept all {acceptable().length.toLocaleString()} recommendation{acceptable().length === 1 ? '' : 's'}
                </button>
              )}
            </>
          ) : (
            <span className="muted" style={{ fontSize: 13, color: '#3B6D11' }}>✓ All recommendations decided — done here? Continue →</span>
          )}
          {/* DX-07 — the discovery-results acknowledgement GATES Assess. Only ever a gate when
              there is something to acknowledge: with no lifecycle recommendations on screen
              `recsToAck` is null and this button behaves exactly as it did before. */}
          {needsAck && (
            <span className="muted" style={{ fontSize: 13 }} role="status">
              Approve the {recsToAck.total.toLocaleString()} discovery recommendation{recsToAck.total === 1 ? '' : 's'} above to continue
            </span>
          )}
          {/* `data-advance` is a STABLE hook. Two tests found this control by its label, so a copy
              change broke them for no reason connected to what they assert — they care that the
              advance control is gated, not what it is called this week. */}
          <button data-advance="assess" onClick={() => onAdvance?.()} disabled={pendingActions > 0 || needsAck}
                  title={pendingActions > 0
                    ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending — accept or override each row, or use "Accept all recommendations"`
                    : needsAck
                      ? `${recsToAck.total} discovery recommendation${recsToAck.total === 1 ? '' : 's'} need your approval — tick "I approve these recommendations" in Discovery results`
                      : undefined}>
            Continue to Assess →
          </button>
        </div>
      )}

      {/* Files discovery listed but never opened: images, videos, unsupported formats. Kept in the
          estate count but carry no WCAG assessment — shown here so the user can browse the whole
          discovered estate, not just the assessable subset. Absent when inv is still loading. */}
      {nonAssessable.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
            <b style={{ color: 'var(--ink)' }}>{nonAssessable.length.toLocaleString()}</b> other
            file{nonAssessable.length === 1 ? '' : 's'} discovered — images, videos, and unsupported
            formats listed by discovery but not opened for WCAG assessment. Click any to see details.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', maxHeight: 200, overflow: 'auto' }}>
            {nonAssessable.map((f) => (
              <button key={f.file} className="linklike" style={{ fontSize: 12 }}
                      onClick={() => setEstOnlyFile(f)}>
                {f.file}
              </button>
            ))}
          </div>
        </div>
      )}

      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); f._estateOnly ? setEstOnlyFile(f) : setSel(f) }} />}
      {sel && <FileDrawer file={sel} context="discover" onClose={() => setSel(null)} overrideOwner={ownerOf(sel)} delegatedFrom={isDelegated(sel) ? sel.owner : null} scanId={scanId} />}
      {estOnlyFile && <EstateOnlyDrawer file={estOnlyFile} onClose={() => setEstOnlyFile(null)} />}
    </>
  )
}
