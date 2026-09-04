import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { subscribeJobs } from './jobsFeed.js'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import WindowedRows from './WindowedRows.jsx'
import FileDrawer from './FileDrawer.jsx'
import { retentionBucket, isAcceptable } from './retentionSignal.js'
import SegmentDrawer from './SegmentDrawer.jsx'
import SitePicker from './SitePicker.jsx'
import DispositionRules from './DispositionRules.jsx'
import { Bars } from './charts.jsx'
import { DEPARTMENTS } from './sim.js'
import { dupeCountOf, duplicateFiles } from './dedupe.js'
import { scopeSentence, isNarrowScope } from './scanScope.js'
import DiscoveryResults from './DiscoveryResults.jsx'
import DiscoverInventoryExport from './DiscoverInventoryExport.jsx'
import { snapshotTrust, snapshotTrustMessage } from './discoverySnapshotTrust.js'
import { assessmentEligible } from './estateFunnel.js'
import { loadDiscoveryInventory, mergeLifecycle, inventoryOnlyRows } from './discoveryInventory.js'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import EstateOnlyDrawer from './EstateOnlyDrawer.jsx'
import { getScanInventory, listScanDecisions, overrideLifecycleRecommendation,
         acknowledgeScan, unacknowledgeScan, checkReadiness, getQueueJob, setWorkers,
         getSourceStatus, getWorkerReplicas, setWorkerReplicas, getQueueEstimate } from './api.js'
import { useWorkerCapacity } from './workerCapacityStore.js'
import { buildUnreadableWhy } from './unreadableWhy.js'
import { discoveryFailureReason } from './discoveryFailureReason.js'
import ProcessingStatusPanel from './ProcessingStatusPanel.jsx'
import DiscoverQueueCard from './DiscoverQueueCard.jsx'
import { deriveDiscoverProcessingState } from './discoverProcessingState.js'
import WorkerAvailability from './WorkerAvailability.jsx'
import FolderActivity from './FolderActivity.jsx'
import QueueJobDetails from './QueueJobDetails.jsx'
import DiscoveryQueuedPlaceholder from './DiscoveryQueuedPlaceholder.jsx'
import AccordionSection from './AccordionSection.jsx'
import LastSuccessfulScanSummary from './LastSuccessfulScanSummary.jsx'
import DiscoveryLifecycleResults from './DiscoveryLifecycleResults.jsx'
import DiscoveryLifecycleEstateSummary from './DiscoveryLifecycleEstateSummary.jsx'

const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
// The bucket comes from retentionSignal now, not from parsing a label back into one. Reading a
// bucket off `label.startsWith('Archive')` meant the badge TEXT was load-bearing: rewording it
// silently re-bucketed every row, and there was no `unassessed` string to match on at all.
const RET_BUCKET = retentionBucket
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30', locked: '#9a948f', delete: 'var(--info-fg)', unassessed: '#9a948f' }
const RET_ORDER = ['keep', 'archive', 'retain']
const RET_BADGE = { keep: ['Keep', 'var(--success-bg)', 'var(--success-fg)'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', 'var(--warn-bg)', 'var(--warn-fg)'], locked: ['🔒 Could not open', '#EEEDEA', '#5F5E5A'], delete: ['Delete', 'var(--info-bg)', 'var(--info-fg)'],
  // Grey, and it says the thing rather than implying it. No lifecycle rule matched and no age
  // or usage signal reached this screen, so there is no recommendation — which is what a real
  // estate looks like today, and what a hardcoded 'Keep' was hiding.
  unassessed: ['Not assessed', '#F1EFF3', '#5F5E5A'] }
const RISK_COLOR = { PII: 'var(--info-fg)', 'legal-hold': 'var(--warn-fg)', 'high-traffic': '#A56814' }
const TYPE_COLOR = { PDF: '#C2410C', DOCX: '#2563EB', PPTX: '#D97706', XLSX: '#15803D', HTML: '#7A5C8E', VIDEO: '#9333EA', AUDIO: '#0891B2' }
const CLASS_TAGS = ['PII', 'legal-hold', 'public-facing', 'high-traffic']
const CLASS_COLOR = { PII: 'var(--info-fg)', 'legal-hold': 'var(--warn-fg)', 'public-facing': '#D85A30', 'high-traffic': '#A56814' }
const OVERRIDE_ACTIONS = ['keep', 'archive', 'retain', 'delete']
// Source freshness badge text/color, from a /source-status row. 'unchanged'/'untracked' render
// nothing — same convention the Release Center and Monitor already use, so a normal, unremarkable
// file doesn't get a badge just for being fine. 'unavailable' branches on the server's `error`
// code (PRD's "Deleted at source" / "Authorization required" vs a generic unreachable source) —
// data the endpoint has always returned but no surface has read until now.
export function sourceFreshnessBadge(row) {
  if (!row) return null
  // PRD Phase 3's fuller sync-state vocabulary — ACP's own side of the round trip, layered by
  // the backend (source_staleness.classify_sync_state) on top of the four states below.
  if (row.state === 'importing') return { label: 'importing…', color: 'var(--info-fg)', title: 'ACP is still importing this file from the source' }
  if (row.state === 'import_failed') return { label: 'import failed', color: '#8A1F1F', title: 'ACP could not import this file from the source' }
  if (row.state === 'conflict') return { label: '⚠ conflict', color: '#8A1F1F', title: 'The source changed and ACP holds an unpublished fix — both sides changed since the scan' }
  if (row.state === 'acp_newer') return { label: 'ACP version newer', color: 'var(--success-fg)', title: "ACP's fixed version is newer than the current source file" }
  if (row.state === 'publish_pending') return { label: 'publish pending', color: 'var(--warn-fg)', title: 'A fixed version is ready but has not been published back to the source yet' }
  if (row.state === 'stale') return { label: '⚠ source changed', color: '#8A1F1F', title: 'The source file in Drive changed after this scan' }
  if (row.state !== 'unavailable') return null
  if (row.error === 'not_found') return { label: 'deleted at source', color: '#8A1F1F', title: 'The source file in Drive no longer exists' }
  if (row.error === 'forbidden') return { label: 'authorization required', color: 'var(--warn-fg)', title: 'ACP no longer has permission to read this file in Drive' }
  return { label: 'source unreachable', color: '#5F5E5A', title: 'ACP could not read the source now (moved, deleted, or access lost)' }
}

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
// Discovery-related job types (QueuePanel.jsx's own JOBLABEL keys) — used to count "compatible
// jobs ahead" honestly: this owner's OTHER queued discovery-lane jobs, not a literal priority
// position (see discoverProcessingState.js's own comment on why a fixed "#N in queue" is fragile).
const DISCOVERY_JOB_TYPES = new Set(['scan_discover', 'scan_batch', 'scan_finalize', 'scan_file', 'scan'])

export default function Discover({ sources, files, busy, onScan, hasDriveToken = false, delegations = {}, onAdvance, progress = null, preflightDegraded = null, preflightCapacityState = null, scanPct = 0, scanId = null, activeScanId = null, jobId = null, scope = null, decisions: decisionsProp, setDecisions: setDecisionsProp, me = null,
  hasSPToken = false, runAt = null, run = null, scanList = null,
  // `rawFiles` — the PRE-annotation records straight from get_scan, before ontology.annotate()
  // back-fills a department from a filename guess. Unread since the classification surface was
  // removed (2026-09-02); kept in the signature, and kept passed by App, because any restored
  // classification claim MUST be checked against these and not against `files`. Checking the
  // annotated array is the 2026-08-21 defect: annotate() gives every real file a department, so
  // the check read "classified" on every real scan.
  rawFiles = null, onStop = null, onViewMonitor = null,
  onOpenSource = null, pendingScanLoad = false }) {
  // discoverRunTime resolves the snapshot instant from run.discovered_at / completed_at, and this
  // component is given neither — Discover takes scanId and scope, not the run. The pieces it needs
  // are assembled here rather than threading the whole run object through a new prop; the resolver
  // falls back to the newest per-file inventory stamp when both are absent, which is the case for
  // every run listed before scan_runs.discovered_at existed.
  const runForExport = { id: scanId, discovered_at: run?.discovered_at ?? null, completed_at: run?.completed_at ?? null }
  const [sel, setSel] = useState(null)
  const [estOnlyFile, setEstOnlyFile] = useState(null)
  const [showSites, setShowSites] = useState(false)     // SharePoint site picker modal
  // The queued-placeholder's own reveal toggle (stakeholder screenshot review): "View previous
  // run" un-hides the still-loaded previous scan's results rather than hiding them outright.
  // Reset whenever a new scan starts (`busy` flips true) — NOT keyed to `scanId`, which (like
  // `scope`/`files`) does not change to the new scan's id until it settles, same staleness this
  // whole placeholder exists to name rather than hide.
  const [showPreviousResults, setShowPreviousResults] = useState(false)
  useEffect(() => { if (busy) setShowPreviousResults(false) }, [busy, activeScanId])
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
  // The per-file lifecycle columns the recommendation surface is made of. They are NOT on
  // `GET /scans/{id}` (it reads file_records, which has no such columns) — they live on
  // scan_inventory, behind `GET /scans/{id}/inventory`. So Discover reads that route itself.
  //
  // `null` covers three states that must all render the same way: not asked yet, still loading,
  // and the read failed. None of them is evidence that no file was tagged, so all three leave the
  // file rows un-merged and the whole recommendation surface ABSENT. A failed read that fell back
  // to "0 tagged for archive review" would be indistinguishable from a clean estate.
  // Scan-infra readiness — checked once on mount and again whenever a scan just finished, so the
  // warning reflects current state before the NEXT "Re-scan all sources" click. Never blocks the
  // button; a worker outage on 2026-08-26 left a queued job silently unclaimed with no signal
  // until the run "finished" showing 0 documents ~45s later. This surfaces that BEFORE the click
  // instead of after. `null` means "not checked yet or the probe itself failed" — render nothing,
  // since an inconclusive read is not evidence of a problem.
  const [readiness, setReadiness] = useState(null)
  useEffect(() => {
    let live = true
    checkReadiness().then((r) => { if (live) setReadiness(r) })
    return () => { live = false }
  }, [busy])
  // Worker-assignment signal (PRD "Live Discover Journey", Phase 1): GET /jobs/{id} carries a
  // real claim timestamp (jobs.locked_at) — the same one AssessRunner already polls for its own
  // job — that nothing on Discover read before.
  //
  // Originally polled only for the pre-listing window (job queued, nothing found yet), stopping
  // the instant progress.phase left 'queued' — correct for jobClaimed/assignedSecsAgo below,
  // which deriveDiscoverProcessingState only ever reads inside its `phase === 'queued'` branch.
  // But the "Processing details" expandable row (QueueJobDetails.jsx, stakeholder review) reads
  // the SAME job's attempts/max_attempts/id for as long as this scan is busy, not just before the
  // first listing tick — so gating the whole effect on phase silently wiped that data the moment
  // discovery actually started, which is exactly when someone would go looking for it. Polls for
  // the entire busy window instead; the two now-stale-during-'discovering' fields simply go
  // unused past that point, same as before, since their one reader never looks past 'queued'.
  const [discoverJobInfo, setDiscoverJobInfo] = useState(null)
  useEffect(() => {
    if (!busy || !jobId) { setDiscoverJobInfo(null); return undefined }
    let live = true
    const load = () => getQueueJob(jobId).then((d) => { if (live) setDiscoverJobInfo(d) }).catch(() => {})
    load()
    const id = setInterval(load, 3000)
    return () => { live = false; clearInterval(id) }
  }, [busy, jobId])
  // Queue-context facts for the same pre-listing window (stakeholder review, 2026-08-28): "N
  // compatible jobs ahead" and worker-pool size, the same GET /jobs data WorkerAvailability
  // polls elsewhere, read here too since this effect needs it merged with the job-specific claim
  // signal above into one card. compatibleJobsAhead counts this owner's OTHER queued
  // discovery-lane jobs — real, but not a promise of exact order (see DISCOVERY_JOB_TYPES above).
  const [queueSnap, setQueueSnap] = useState(null)   // {compatibleJobsAhead, workersTotal, workersOnline}
  useEffect(() => {
    setQueueSnap(null)
    const phase = progress?.phase ?? null
    if (!busy || (phase && phase !== 'queued')) return undefined
    // Shared subscription, not a private timer (jobsFeed.js). Every other consumer asking for
    // the same query rides the same request instead of adding five more pool acquisitions.
    // `meta.fetchedAt`, not Date.now(). The feed shares one GET /jobs and deliberately keeps its
    // payload across unmount so a remount draws immediately — which is only safe because it hands
    // every subscriber the REAL time of the fetch that produced that payload. Its own header says
    // "Mounting must not make old data look new"; stamping Date.now() here defeated exactly that,
    // at the ONE surface that displays freshness. A mount onto a warm cache rendered "Queue
    // updated 0s ago" for a payload 45s old and already flagged stale.
    return subscribeJobs('queued', (d, meta) => {
      const ahead = (d.jobs || []).filter((j) => DISCOVERY_JOB_TYPES.has(j.type) && j.id !== jobId).length
      setQueueSnap({ compatibleJobsAhead: ahead, workersTotal: d.workers ?? null,
                     workersOnline: !!d.worker_tier_alive,
                     polledAt: meta?.fetchedAt ?? Date.now() })
    }, { intervalMs: 5000 })
  }, [busy, jobId, progress?.phase])
  // The actual "estimated pickup: X–Y minutes" range (GET /scans/{id}/queue-estimate), on top of
  // queueSnap's own compatibleJobsAhead/workersTotal facts above — same pre-listing window, same
  // gating. Scoped by kind server-side (Store.queue_estimate groups job types into discover/
  // assess/remediate), so this never confuses a queued Assess or Remediate job elsewhere for a
  // Discover one. Omitted (stays null) until there is enough recent-completion history for an
  // honest range — deriveDiscoverProcessingState reads that absence as pickupUnavailable, same
  // as before this existed, rather than showing a guess.
  const [pickupEstimate, setPickupEstimate] = useState(null)
  // TWO IDENTITIES, and this is the one place that wants the ACTIVE one.
  //
  // `scanId` is the DISPLAYED run — the inventory on screen, which is the PREVIOUS scan for the
  // whole time a new one is in flight (App only replaces it when pollScanJob resolves, i.e. when
  // the scan finishes). Every other consumer in this file legitimately wants that: the inventory
  // loader, getSourceStatus, acknowledgeScan, the export.
  //
  // The pickup estimate does not. It answers "when will the work I just submitted start", which
  // is a question about the job that was just accepted. Using `scanId` asked it about a run that
  // had already finished — which is what production recorded on 2026-08-30: the estimate request
  // named scan 5e78b8d2cb75 while the worker had claimed the job for ad94e943e0f2.
  //
  // So this reads `activeScanId` (App's liveScanId, set from the submission's own response
  // alongside jobId) and does NOT fall back to `scanId`. A fallback is what produced the bug:
  // when nothing is live there is no pickup to estimate, and the honest answer is no request at
  // all rather than an estimate for somebody else's finished run.
  useEffect(() => {
    setPickupEstimate(null)
    const phase = progress?.phase ?? null
    if (!busy || (phase && phase !== 'queued') || !activeScanId) return undefined
    let live = true
    const load = () => getQueueEstimate(activeScanId, 'discover').then((d) => {
      // Guards a late response from a PREVIOUS activeScanId: the effect re-runs when the id
      // changes and the old closure's `live` is already false, so scan A's reply cannot land on
      // scan B's panel. Start B while A is still resolving and B keeps its own estimate.
      if (live) setPickupEstimate(d)
    }).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => { live = false; clearInterval(id) }
  }, [busy, activeScanId, progress?.phase])
  // "How many workers are available to pick up scan jobs" — the same GET /jobs signal
  // AssessRunner's worker strip already polls (workers/alive/suggested), shown here so this
  // question is answered directly on Discover instead of only inside a "Preparing capacity"
  // banner. Polled the whole time this tab is mounted, not just while busy — the point is to
  // tell a user BEFORE they click "Re-scan" whether anything would pick the job up, not only to
  // narrate a run already in flight.
  const [workerSnap, setWorkerSnap] = useState(null)
  const [workerBusy, setWorkerBusy] = useState(false)
  const [workerMsg, setWorkerMsg] = useState(null)
  const workerMsgTimer = useRef(null)
  useEffect(() => {
    return subscribeJobs(null, (d) => {
      setWorkerSnap({ workers: d.workers ?? 0, alive: !!d.worker_tier_alive,
                      suggested: d.suggested_workers ?? 4, runtime_mode: d.runtime_mode ?? 'auto',
                      oldestQueuedCreatedAt: d.oldest_queued?.created_at ?? null,
                      workerHeartbeatAgeS: d.worker_heartbeat_age_s ?? null })
    }, { intervalMs: 10000 })
  }, [])
  useEffect(() => () => clearTimeout(workerMsgTimer.current), [])
  const adjustWorkers = (delta) => {
    if (!workerSnap || workerBusy) return
    const next = (delta === 1 && workerSnap.workers === 0)
      ? (workerSnap.suggested ?? 4)
      : Math.max(0, Math.min(16, workerSnap.workers + delta))
    if (next === workerSnap.workers) return
    const count = Math.abs(next - workerSnap.workers)
    const noun = count === 1 ? 'worker' : 'workers'
    clearTimeout(workerMsgTimer.current)
    setWorkerMsg(next > workerSnap.workers ? `Starting ${count} ${noun}…` : `Stopping ${count} ${noun}…`)
    setWorkerBusy(true)
    const prev = workerSnap.workers
    setWorkerSnap((s) => ({ ...s, workers: next }))   // optimistic
    setWorkers(next)
      .then((d) => {
        const actual = d.workers ?? next
        setWorkerSnap((s) => ({ ...s, workers: actual }))
        setWorkerMsg(actual > 0 ? `${actual} ${actual === 1 ? 'worker' : 'workers'} active` : 'Workers stopped')
      })
      .catch(() => {
        setWorkerSnap((s) => ({ ...s, workers: prev }))
        setWorkerMsg('Failed to update — try again')
      })
      .finally(() => {
        setWorkerBusy(false)
        workerMsgTimer.current = setTimeout(() => setWorkerMsg(null), 3500)
      })
  }
  // Azure Container App warm-replica visibility (GET /control/workers/replicas) — fetched only
  // once the worker tier reports 'distributed' (externally managed), since that's the only mode
  // where this data means anything. Visible to every signed-in user (the endpoint is open, not
  // admin-gated — see api/routes/control.py); only the adjust handler passed to
  // WorkerAvailability is conditioned on me?.is_admin below, matching PATCH's own admin gate.
  // A one-shot fetch on becoming externally-managed is enough — unlike workerSnap (workers
  // picking up jobs right now), this rarely changes and isn't worth polling every few seconds.
  // TOPOLOGY, not health. `runtime_mode === 'distributed'` answers "does this deployment run a
  // separate worker tier that Azure manages?" — a configuration fact that does not change when
  // workers fall over. `alive` answers "is that tier heartbeating right now?" — a health fact.
  //
  // These were one condition, and the `&& alive` made Azure observation switch off exactly when
  // it was most needed: workers absent, starting, or unhealthy is precisely when a user needs to
  // know whether Azure has replicas provisioned, how many are draining, and what the revision
  // health is. Gating the evidence on the thing the evidence is meant to explain leaves the UI
  // silent in the one situation it exists for.
  //
  // Azure reads are read-only and permission-gated server-side (see WorkerAvailability.jsx), so
  // nothing here depends on the worker tier being reachable. `alive` stays available for the
  // signals that genuinely are about health — it just no longer decides whether we LOOK.
  const workerTierIsExternal = workerSnap?.runtime_mode === 'distributed'
  const [replicas, setReplicas] = useState(null)
  const [replicasBusy, setReplicasBusy] = useState(false)
  const [replicasMsg, setReplicasMsg] = useState(null)
  const replicasMsgTimer = useRef(null)
  useEffect(() => {
    if (!workerTierIsExternal) return undefined
    let live = true
    getWorkerReplicas().then((d) => { if (live) setReplicas(d) }).catch(() => {})
    return () => { live = false }
  }, [workerTierIsExternal])
  useEffect(() => () => clearTimeout(replicasMsgTimer.current), [])
  const adjustReplicas = (delta) => {
    if (!replicas?.configured || replicasBusy) return
    const next = Math.max(1, Math.min(5, replicas.min_replicas + delta))
    if (next === replicas.min_replicas) return
    clearTimeout(replicasMsgTimer.current)
    setReplicasMsg(next > replicas.min_replicas ? 'Requesting more warm replicas…' : 'Reducing warm replicas…')
    setReplicasBusy(true)
    const prev = replicas.min_replicas
    setReplicas((r) => ({ ...r, min_replicas: next }))   // optimistic
    setWorkerReplicas(next)
      .then((d) => {
        setReplicas(d)
        setReplicasMsg(`Warm replicas set to ${d.min_replicas}`)
      })
      .catch(() => {
        setReplicas((r) => ({ ...r, min_replicas: prev }))
        setReplicasMsg('Failed to update — try again')
      })
      .finally(() => {
        setReplicasBusy(false)
        replicasMsgTimer.current = setTimeout(() => setReplicasMsg(null), 3500)
      })
  }
  // Azure capacity EVIDENCE (GET /control/workers/capacity) — current replica count and recent
  // CPU/memory, as opposed to `replicas` above's CONFIGURED min/max. Unlike that one-shot fetch,
  // this genuinely changes over time (Azure scaling up/down, load shifting), so it stays fresh
  // via a shared 30s poller (workerCapacityStore.js) — one poller reference-counted across every
  // mounted consumer, including QueuePanel.jsx's own capacity strip, rather than each maintaining
  // an independent setInterval and doubling the Azure Monitor API calls whenever both are
  // mounted at once. Read-only, no admin gate anywhere (see WorkerAvailability.jsx).
  const capacity = useWorkerCapacity(workerTierIsExternal)
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
  // Source freshness (PRD Phase 3 — sync states): the same /source-status the Release Center and
  // Monitor already surface, now on Discover too, where the PRD's own inventory spec asks for it.
  // Best-effort like those two: an empty map on any failure means no badges, never a false claim.
  const [srcStatus, setSrcStatus] = useState({})
  useEffect(() => {
    let live = true
    if (!scanId) { setSrcStatus({}); return undefined }
    getSourceStatus(scanId)
      .then((s) => {
        if (!live) return
        const byFile = {}
        ;(s?.files || []).forEach((r) => { byFile[r.file] = r })
        setSrcStatus(byFile)
      })
      .catch(() => { if (live) setSrcStatus({}) })
    return () => { live = false }
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
  const lifecycleCandidateRows = useMemo(() => (Array.isArray(estateFiles) ? estateFiles : []).filter((file) =>
    file?.lifecycle_status === 'Archive Candidate' || file?.lifecycle_status === 'Delete Candidate'
  ), [estateFiles])
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
  const failureReason = useMemo(() => discoveryFailureReason(errLog), [errLog])

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
  // App keeps the previous run's inventory until the active run settles. Live progress does
  // not make that inventory current: preserve the separation through every active phase.
  const showQueuedPlaceholder = busy
    || (!busy && run?.status === 'queued')
  const hidePreviousInventory = showQueuedPlaceholder && !showPreviousResults
  // Stated against the raw discovered count — the estate line describes discovery, which the
  // location view filter never restricts.
  const scopeLine = scopeSentence(scope, discoveredCount)
  // Self-heals a scan whose persisted scope.inventory.discovered is a stale/wrong 0 — root
  // cause fixed backend-side (2026-08-28: the durable Discover job used to flip scan_runs.status
  // to 'discovered' before add_inventory() and the scope.inventory summary were actually
  // written, so a reader in that window persisted "0 files inventoried" permanently even though
  // the fix later closed the window for every NEW scan). A scan that already reached
  // 'discovered' status with that bad snapshot before the fix deployed keeps reading it forever
  // — a page refresh alone cannot repair data already written. Only applied here, for the
  // COMPLETE-scan card: `discoveredCount`'s own `??` fallback above must stay untouched for the
  // live-run/scopeLine uses right above it, where files.length is the unreliable one (file_records
  // stays empty pre-Assess — see that fallback's own comment). Once a scan is genuinely
  // '!busy'/'discovered', though, file_records has already been backfilled from scan_inventory
  // (ADR 0020's get_scan fallback), so files.length is real ground truth here — `||`, not `??`,
  // so it also overrides an explicit-but-wrong 0, not just a missing value.
  const completionDiscoveredCount = discoveredCount || files.length
  // SSE progress is browser-memory state and is absent after a refresh. Reconstruct only the
  // terminal checklist facts from the durable scan record so the completed card remains visible
  // when the user returns to Discover. No timing, rate, or live-connection state is inferred.
  const completedDiscoveryProgress = !busy && (run?.discovered_at || run?.status === 'discovered')
    ? {
        phase: 'done',
        files_found: completionDiscoveredCount,
        folders_found: scope?.folders_walked ?? null,
        rules_enabled: scope?.lifecycle_rules_enabled ?? null,
        lifecycle_matches: (Number(scope?.lifecycle_archive) || 0)
          + (Number(scope?.lifecycle_delete) || 0)
          + (Number(scope?.lifecycle_tagged) || 0),
      }
    : null
  const discoveryProgressForCard = progress ?? completedDiscoveryProgress
  // Live-activity rate for the discovering/lifecycle stage (stakeholder review, 2026-08-28):
  // a "recent discovery rate" derived client-side from real (count, timestamp) poll samples —
  // not a backend field. progress.files_found is the true live counter here (the Redis job
  // state _listing_progress ticks, per queuedProgress.js), not `discoveredCount` above
  // (scope-derived, which App.jsx only refreshes once the scan SETTLES and stays stale for the
  // whole busy run). Keeps a short rolling window rather than a two-point instantaneous delta
  // so the rate doesn't swing between 0 and a spike on noisy ticks, and withholds a reading
  // entirely until the window spans a meaningful interval — no first-tick guess.
  const liveDiscoveredCount = progress?.files_found ?? discoveredCount
  const [filesPerSec, setFilesPerSec] = useState(null)
  const [inventoryChangedSecsAgo, setInventoryChangedSecsAgo] = useState(null)
  const rateSamplesRef = useRef([])       // [{count, t}], oldest first, capped at 4
  const lastChangeAtRef = useRef(null)    // ms timestamp the count last increased
  useEffect(() => {
    const phase = progress?.phase ?? null
    const inDiscoveringStage = busy && phase && phase !== 'queued'
    if (!inDiscoveringStage || liveDiscoveredCount == null) {
      rateSamplesRef.current = []; lastChangeAtRef.current = null
      setFilesPerSec(null); setInventoryChangedSecsAgo(null)
      return undefined
    }
    const now = Date.now()
    const samples = rateSamplesRef.current
    const prevCount = samples.length ? samples[samples.length - 1].count : null
    if (prevCount == null || liveDiscoveredCount !== prevCount) {
      if (prevCount == null || liveDiscoveredCount > prevCount) lastChangeAtRef.current = now
      rateSamplesRef.current = [...samples, { count: liveDiscoveredCount, t: now }].slice(-4)
    }
    const win = rateSamplesRef.current
    if (win.length >= 2 && win[win.length - 1].t - win[0].t >= 1000) {
      const rate = (win[win.length - 1].count - win[0].count) / ((win[win.length - 1].t - win[0].t) / 1000)
      setFilesPerSec(rate >= 0 ? rate : null)
    } else {
      setFilesPerSec(null)
    }
    setInventoryChangedSecsAgo(lastChangeAtRef.current != null ? (now - lastChangeAtRef.current) / 1000 : null)
    return undefined
  }, [busy, progress?.phase, liveDiscoveredCount])
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

  // THE CLASSIFICATION TRIAGE SURFACE IS GONE FROM THIS SCREEN. The exposure-and-risk chart, the
  // per-department grouping and the "not classified yet" caveat that stood in for the chart on an
  // unclassified estate were all removed on 2026-09-02 (PRD "ACP Discover and Overview
  // Simplification"). Discover reports the inventory; classification is not part of it.
  //
  // That takes the honesty problem with it rather than leaving it unsolved. The caveat existed
  // because the chart, rendered over an unclassified estate, read "100% internal" with every risk
  // flag at zero — each number true and the reading false ("0 legal-hold" asserts a finding nobody
  // obtained). With no chart there is no false reading to correct, so there is no claim to make.
  // classificationData.js and its tests stay; the check is simply not asked here any more.
  // discoverClassificationAbsent.test.jsx pins both halves.
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
              const fresh = f.locked ? null : sourceFreshnessBadge(srcStatus[f.file])
              const meta = (
                <div className="filemeta">
                  <span className="srcpill">{f.sourceName}</span>
                  {f.locked
                    ? <span className="lockflag">🔒 {f.openIssue}</span>
                    : <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}
                        {isDelegated(f) && <span className="badge" style={{ marginLeft: 6, background: 'var(--success-bg)', color: 'var(--success-fg)', fontSize: 10 }}>delegated → {ownerOf(f)}</span>}
                        {fresh && <span title={fresh.title} style={{ marginLeft: 6, fontWeight: 600, color: fresh.color }}>{fresh.label}</span>}
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
      {!busy && (run?.discovered_at || run?.status === 'discovered') && (
        <DiscoverInventoryExport compact scanId={scanId} run={runForExport}
                                 inventory={scope?.inventory || null} rows={inv?.rows ?? null} />
      )}
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
      {/* progress.freshness (set per-tick by App.jsx's poll loops, including 'reconnecting' when
          the live SSE push has died) takes priority over run.freshness — the latter is a snapshot
          from the last GET /scans/{id} the outer `scan` state holds, which during an active run
          can be the PREVIOUS scan's terminal value until this one settles. */}
      {/* The queue/assignment card below owns status until listing starts. */}
      {!(busy && ['queued', 'preparing', 'submitting'].includes(progress?.phase)) && <DiscoverRunProgress progress={discoveryProgressForCard} busy={busy} onStop={onStop} onContinue={onAdvance} sources={sources} inv={inv} preflightDegraded={preflightDegraded} freshness={progress?.freshness ?? run?.freshness ?? null} runStartedAt={run?.started_at ?? null} />}

      {(() => {
        const jobClaimed = !!(discoverJobInfo && discoverJobInfo.status && discoverJobInfo.status !== 'queued')
        const queuedNotClaimed = busy && progress?.phase === 'queued' && !jobClaimed
        // The consolidated "DISCOVERY · Queued" card (stakeholder UX review, 2026-08-30) replaces
        // WorkerAvailability + ProcessingStatusPanel for JUST this one window — the three separate,
        // sometimes-contradicting pieces they used to show here ("Loading…"/"Waiting for a
        // worker"/a plain worker strip, fixed individually in #988/#993/#1027) are now one card.
        // Every OTHER state (claimed, actively discovering, idle) still renders through the
        // existing two components below, unchanged — this card has nothing to add once a worker
        // has actually claimed the job and Discover's own live counts/folder activity take over.
        if (queuedNotClaimed) {
          return (
            <DiscoverQueueCard
              compatibleJobsAhead={queueSnap?.compatibleJobsAhead ?? null}
              workersTotal={queueSnap?.workersTotal ?? null}
              workersOnline={queueSnap?.workersOnline ?? null}
              queueUpdatedSecsAgo={queueSnap?.polledAt ? (Date.now() - queueSnap.polledAt) / 1000 : null}
              submittedSecsAgo={discoverJobInfo?.created_at && Number.isFinite(Date.parse(discoverJobInfo.created_at)) ? Math.max(0, (Date.now() - Date.parse(discoverJobInfo.created_at)) / 1000) : (progress?.started_at && Number.isFinite(Date.parse(progress.started_at)) ? Math.max(0, (Date.now() - Date.parse(progress.started_at)) / 1000) : null)}
              pickupEstimate={pickupEstimate}
              capacity={capacity}
              replicas={replicas}
              onStop={onStop}
              onViewMonitor={onViewMonitor}
            />
          )
        }
        return (
          <>
            {/* "How many workers are available to pick up scan jobs" — answered directly,
                ambiently, not only inferred from a capacity banner mid-run. Polled the whole time
                this tab is mounted (see the effect above), so it also answers the question
                BEFORE a scan is even started. */}
            <WorkerAvailability snap={workerSnap}
                                replicas={replicas}
                                capacity={capacity} />

            {/* PRD "Processing status" — the Discover instance of the same panel Assess uses
                (#922), reusing the exact signals this tab already computes for its own
                terminal-status banners below (failureReason from #919, the same capacity signal
                the "Preparing Discovery capacity" notice reads) rather than a second, possibly-
                diverging notion of the same thing. Additive, not a replacement for those banners
                yet — same rollout shape as Assess's own panel. */}
            <ProcessingStatusPanel
              derived={deriveDiscoverProcessingState({
                busy, phase: progress?.phase ?? null, freshness: progress?.freshness ?? run?.freshness ?? null,
                runStatus: run?.status ?? null, failureReason, capacityState: preflightCapacityState,
                discoveredCount: liveDiscoveredCount, elapsedSecs: progress?.elapsed ?? null,
                jobClaimed,
                assignedSecsAgo: discoverJobInfo?.locked_at
                  ? (Date.now() - Date.parse(discoverJobInfo.locked_at)) / 1000 : null,
                compatibleJobsAhead: queueSnap?.compatibleJobsAhead ?? null,
                workersTotal: queueSnap?.workersTotal ?? null,
                workersOnline: queueSnap?.workersOnline ?? null,
                pickupEstimate,
                submittedSecsAgo: progress?.started_at
                  ? (Date.now() - Date.parse(progress.started_at)) / 1000 : null,
                foldersFound: progress?.folders_found ?? null,
                filesPerSec, inventoryChangedSecsAgo,
                hasFolderActivity: !!(progress?.active_folders?.length || progress?.recent_folders?.length),
                workerHeartbeatAgeS: workerSnap?.workerHeartbeatAgeS ?? null,
              })}
              onRerun={() => onScan('all')}
              onViewMonitor={onViewMonitor}
            />
          </>
        )
      })()}

      {/* "Processing details" expandable row (stakeholder review): attempt count against its real
          ceiling, and a truncated job id, for the whole busy window — not just the pre-listing
          queued phase discoverJobInfo originally stopped polling after (see that effect's own
          comment above for why it now keeps going). Renders nothing on its own when there's
          nothing real to show yet (jobId not assigned, or attempts/max_attempts genuinely absent
          — SIM mode's getQueueJob fixture doesn't track them). */}
      {busy && <QueueJobDetails jobId={jobId} attempts={discoverJobInfo?.attempts ?? null}
                                maxAttempts={discoverJobInfo?.max_attempts ?? null} />}

      {/* Folder-level detail underneath the aggregate counts above (#929's backend slice) — which
          folders the BFS is fetching right now, and the last few that finished. Renders nothing
          on its own when there's nothing to show (the flat Drive-query path, a scan not yet
          discovering) — see FolderActivity.jsx's own header comment for why this stops short of
          the full tree view. */}
      <FolderActivity active={progress?.active_folders} recent={progress?.recent_folders} />

      {/* Discovery leads with facts from THIS listing. */}
      {!busy && (run?.discovered_at || run?.status === 'discovered') && (
        <AccordionSection id="discover-latest" title="Latest discovery results"
                          ariaLabel="Latest discovery results" defaultOpen
                          style={{ marginBottom: 14 }}>
          <LastSuccessfulScanSummary run={run} scope={scope} runAt={runAt}
                                     files={estateFiles} inventory={scope?.inventory || null} />
        </AccordionSection>
      )}

      {!busy && scanId && (run?.discovered_at || run?.status === 'discovered') && (
        <AccordionSection id="discover-lifecycle-estate" title="Lifecycle estate summary"
                          ariaLabel="Lifecycle estate summary" defaultOpen
                          style={{ marginBottom: 14 }}>
          <DiscoveryLifecycleEstateSummary scanId={scanId} />
        </AccordionSection>
      )}

      {/* Only actionable rule matches return to the main flow. The old all-supported-documents
          presentation duplicated File inventory even when every row was Active. */}
      {!busy && lifecycleCandidateRows.length > 0 && (
        <AccordionSection id="discover-lifecycle-results" title="Lifecycle rule matches"
                          meta={`${lifecycleCandidateRows.length.toLocaleString()} files`}
                          ariaLabel="Lifecycle rule matches" defaultOpen={false}
                          style={{ marginBottom: 14 }}>
          <DiscoveryLifecycleResults rows={lifecycleCandidateRows} scanId={scanId}
                                     source={run?.source} />
        </AccordionSection>
      )}

      {/* Any run whose numbers below cannot be trusted as "the whole source, as of now" —
          not just the outright failure this used to cover alone. Without one of these, EVERY
          one of these statuses reads exactly like a clean, complete, empty scan: 0 documents, no
          scope line, "inventory could not be read" with no reason given — the same silent-zero
          shape found live 2026-08-28 on a scan that was actually stuck, not empty. This is the
          one place that says outright why the counts below should not be trusted, rather than
          leaving the reader to conclude the source itself had nothing in it.

          - failed: set by handlers._scan_discover right before it re-raises (expired token, a
            transient API error, the worker dying mid-list).
          - cancelled / interrupted: an explicit user Stop, or the server restarting mid-run —
            both have real (if partial) inventory, described as such, not as "0 found".
          - running with nothing tracking it live (busy is false): the persisted row still says
            in-flight, but this tab has no active reconnect/poll for it — a scan that got orphaned
            (worker died without ever reaching a terminal status) looks IDENTICAL to a healthy
            small one here unless this says so. Deliberately does not attempt to distinguish
            "still genuinely running elsewhere" from "stuck forever" — this tab cannot tell either
            way, and both deserve the same "don't trust this yet" reading.

          ALL THREE now also require `!busy`. `run` is `scan?.run`, which App.jsx only replaces
          once a poll SETTLES — while a scan is in flight (doScan/reconnectScan), `run` still
          describes whatever scan was on screen before this one started, not the one `busy` and
          the progress card above are tracking. `running` already guarded on this; `failed` and
          `cancelled`/`interrupted` did not, so a brand-new scan's live "Discovering documents"
          card could render directly above a banner reading "Discovery was stopped before it
          finished" or "did not finish" — both true, about two different scans, read as one.
          Found live 2026-08-28: a reconnected scan stuck at "Discovering documents · 41m
          elapsed" sat under a stale "Discovery was stopped" banner left over from the PRIOR
          scan on this source, which really had been cancelled. */}
      {/* failureReason reads api/handlers.py's _scan_discover's own decision-log entry for THIS
          failure (scan.discover_conflict / scan.discover_failed / scan.suspicious_zero /
          scan.unreachable_zero — see discoveryFailureReason.js). Every one of those is a
          different, specific, already-recorded reason — a single-flight rejection because
          another scan of this source is still running reads nothing like an expired token or a
          dead API, and until this they were indistinguishable, both behind the same generic "the
          last attempt to list this source failed". Shown verbatim, not paraphrased: a restatement
          of what was logged, the same choice unreadableWhy.js makes for per-file reasons, so the
          banner can never say something the log does not back up. Falls back to the old generic
          text only when nothing was recorded (e.g. a transient DB error mid-check logs no
          decision at all) — never fabricated. */}
      {run?.status === 'failed' && !busy && (
        <div className="err" role="alert" style={{ marginBottom: 12 }}>
          {failureReason
            ? <>Discovery did not finish: {failureReason}.</>
            : 'Discovery did not finish — the last attempt to list this source failed.'}
          {' '}The counts below are incomplete or stale. Re-run discovery to get a current inventory.
        </div>
      )}
      {(run?.status === 'cancelled' || run?.status === 'interrupted') && !busy && (
        <div className="err" role="alert" style={{ marginBottom: 12 }}>
          {run.status === 'cancelled'
            ? 'Discovery was stopped before it finished.'
            : 'Discovery was interrupted before it finished (the server likely restarted mid-run).'}
          {' '}The counts below reflect only what was found up to that point — not the whole
          source. Re-run discovery to get a current inventory.
        </div>
      )}
      {run?.status === 'running' && !busy && (
        <div className="err" role="alert" style={{ marginBottom: 12 }}>
          This scan still shows as running, but nothing here is tracking its live progress right
          now — it may be stuck. The counts below are not final. Re-run discovery, or check back
          shortly.
        </div>
      )}
      {/* A scan can be `status: 'queued'` on the displayed run without this tab tracking it live
          (busy=false) — e.g. the default-scan pick lands on a just-created scan this tab never
          reconnected to. Without SOME notice, "0 documents discovered · 0 could not be read"
          reads as a completed, genuinely empty scan — found live 2026-08-28 on scan
          90203ef148e3. That notice used to live here, as its own banner; it was consolidated
          into ProcessingStatusPanel above (2026-08-28: `!busy && runStatus === 'queued'` in
          discoverProcessingState.js says the same thing — "Queued — not started yet / This scan
          has not been picked up by a worker yet") after a stakeholder review flagged two blue
          banners saying the same thing back to back on this exact screen. Do not re-add a
          banner here; extend that one branch instead. */}

      {/* A listing that ran to completion but did NOT cover the whole source. The backend has
          recorded this in scope.enumeration since the resilience work, and nothing read it — so a
          truncated run rendered its partial counts below exactly like a complete one, with the
          estate bar stating them as fact. Not shown while busy (the counts are openly provisional
          then) and not shown for a failed run, which has its own, stronger banner above. */}
      {!busy && (() => {
        const msg = snapshotTrustMessage(snapshotTrust(run))
        if (!msg) return null
        return (
          <div className="readywarn" role="status"
               style={{ marginBottom: 12, padding: '10px 14px', borderRadius: 8,
                        background: 'var(--amber-bg,#fffbeb)',
                        border: '1px solid var(--amber,#d97706)',
                        color: 'var(--amber-ink,#92400e)' }}>
            <span style={{ fontWeight: 600 }}>⚠ {msg.title}</span>
            <span style={{ marginLeft: 8 }}>{msg.body}</span>
          </div>
        )
      })()}

      {/* Capacity state notice — shown before/after a scan, not during (busy). Shows the most
          specific signal available: preflightCapacityState is set right after a user clicks a
          scan button; readiness is the background ambient probe. Prefer preflight when set. */}
      {!busy && (() => {
        const cs = preflightCapacityState
          || (readiness?.capacity_state !== 'ready' ? readiness?.capacity_state : null)
          // Legacy: older /readyz responses without capacity_state
          || (readiness?.ready === false ? 'starting' : null)
        if (!cs || cs === 'ready' || cs === 'unknown') return null

        const configs = {
          starting: {
            style: { background: 'var(--blue-bg,#eef4ff)', border: '1px solid var(--blue,#3b82f6)', color: 'var(--blue-ink,#1e40af)' },
            icon: '◌',
            title: 'Preparing Discovery capacity',
            body: 'A worker is starting. You can scan now — your Discovery will be queued and start automatically.',
          },
          busy: {
            style: { background: 'var(--blue-bg,#eef4ff)', border: '1px solid var(--blue,#3b82f6)', color: 'var(--blue-ink,#1e40af)' },
            icon: '⏳',
            title: 'Discovery capacity is currently busy',
            body: 'Your scan will be queued and start automatically when a worker is free.',
          },
          degraded: {
            style: { background: 'var(--amber-bg,#fffbeb)', border: '1px solid var(--amber,#d97706)', color: 'var(--amber-ink,#92400e)' },
            icon: '⚠',
            title: 'Discovery capacity is limited',
            body: 'A scan started now may not progress immediately. You can still try.',
          },
          unavailable: {
            style: { background: 'var(--red-bg,#fef2f2)', border: '1px solid var(--red,#ef4444)', color: 'var(--red-ink,#991b1b)' },
            icon: '✕',
            title: 'Discovery is temporarily unavailable',
            body: 'ACP could not start a compatible worker. Try again, or contact an administrator if this continues.',
          },
        }
        const cfg = configs[cs] || configs.degraded
        return (
          <div className="readywarn" role="status" style={{ marginBottom: 12, padding: '10px 14px',
                                                            borderRadius: 8, ...cfg.style }}>
            <span style={{ fontWeight: 600 }}>{cfg.icon} {cfg.title}</span>
            <span style={{ marginLeft: 8 }}>{cfg.body}</span>
          </div>
        )
      })()}

      <div className="estatebar">
        {/* Text description only shown while busy or before a scan completes — once the full
            discovery card above appears it covers this same information more richly.

            Suppressed while progress.phase === 'queued' (this tab is tracking a scan it just
            started/reconnected to): DiscoverRunProgress is already showing its own "Discovery
            queued — waiting for an available worker" card immediately above, which says nothing
            has started. Also suppressed while run.status === 'queued' with busy false (this tab
            is showing a queued scan it is NOT tracking live): the banner just above this one now
            covers that case instead. Either way, this line's "0 documents discovered" is bold and
            reads as a result, not a caveat — the "provisional" note next to it is small italic
            text easily missed. A scan that hasn't started yet showed as prominently as a genuine
            empty one — found live 2026-08-28 twice, once for each of these two paths.

            A THIRD path, found live 2026-08-30: `run` is null not because nothing has ever been
            scanned, but because App.jsx's initial load hasn't resolved `run` yet — `files` is `[]`
            (App.jsx's own fallback, never `null`) for the same reason estateSummary() already
            treats as "genuinely empty" (discoveryRecommendations.js), so this line, DiscoveryResults
            and the "No documents yet" fallback below all read a just-logged-in, already-scanned
            workspace as brand new. `pendingScanLoad` (App.jsx: `!run && !!overviewPreview` — the
            SAME bootstrap snapshot OverviewPreviewCard/AssessPreviewCard already render from, so
            this needed no new fetch) is the one signal that distinguishes the two: bootstrap found
            a real scan, its full payload just hasn't arrived.

            `&& !busy` (stakeholder UX review, 2026-08-30): pendingScanLoad and a freshly-started
            scan are not mutually exclusive — clicking "Re-scan" sets `busy` true and starts
            polling `progress` well before App.jsx's own `run` re-fetch resolves, so both this
            placeholder AND the ProcessingStatusPanel queued card below could render at once,
            contradicting each other ("loading" next to "waiting for a worker" for a job nothing
            has started on). The queued card already answers the question this placeholder exists
            to answer for that window, so it takes over instead of doubling it. */}
        {pendingScanLoad && !busy && (
          <div className="muted">Loading your inventory…</div>
        )}
        {!pendingScanLoad && (busy || !(run?.discovered_at || run?.status === 'discovered'))
          && progress?.phase !== 'queued' && run?.status !== 'queued' && (
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
        )}
        {/* Gated on the SharePoint token for the same reason the Drive button is gated on its
            own: offering a picker that cannot authenticate produces an error where a missing
            button would have produced an obvious next step (connect the source). */}
        {hasSPToken && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button className="ghost" disabled={busy} onClick={() => setShowSites(true)}
                    title="Choose a SharePoint site — every document library on it is scanned">
              Choose SharePoint site…
            </button>
          </div>
        )}
      </div>

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
      {showQueuedPlaceholder && showPreviousResults && (
        <div role="status" className="muted">
          Previous scan results — not results from the active discovery.
          {scanId && <> Scan ID: {scanId}.</>}
          {runAt?.recorded && <> Recorded {runAt.absolute}.</>}
          {' '}<button type="button" className="linklike" onClick={() => setShowPreviousResults(false)}>Hide previous results</button>
        </div>
      )}

{/* The prior inventory stays opt-in throughout discovery. Its explicit historical label
          also covers exports and document rows; write actions retain the displayed run's ID. */}
      {/* pendingScanLoad suppresses this whole block the same way it suppresses the header line
          above: DiscoveryResults/DiscoverInventoryExport read `files`/`scope.inventory` from
          App.jsx, which are `[]`/`null` until `run` resolves — indistinguishable, to them, from a
          genuinely empty scan (estateSummary() only guards on `Array.isArray(files)`, never on
          "have we actually asked the backend yet"). */}
      {pendingScanLoad ? null : hidePreviousInventory ? (
        <DiscoveryQueuedPlaceholder previousCount={discoveredCount} previousAt={runAt}
                                    onShowPrevious={() => setShowPreviousResults(true)} />
      ) : (
      <div id="discover-inventory-table">
      <AccordionSection id="discover-inventory" title="File inventory"
                        ariaLabel="File inventory" className="" defaultOpen>
        <><DiscoveryResults files={estateFiles} source={run?.source} inventory={scope?.inventory || null} invRows={inv?.rows ?? null} scopeLine={scopeLine} runAt={runAt}
                        showHeadlineTiles={!run || (!run.discovered_at && run.status !== 'discovered')}
                        reasonOf={why ? why.reasonOf : undefined}
                        reasonSampleOf={why ? why.sampleOf : null}
                        reasonFetchLikely={why ? why.fetchLikely : null}
                        onOverrideRecommendation={overrideRecommendation}
                        actor={me?.email || me?.name || null} scanId={scanId}
                        rawScope={scope} rawDecisions={errLog} runStatus={run?.status ?? null} />

      {/* TAKE THE INVENTORY OUT OF ACP, DATED. Metadata-only CSV/JSON for the compliance reader,
          with the snapshot instant on every row — a count is a fact about a boundary at an
          instant, and a CSV outlives the screen that explained it.

          It self-guards: no inventory to export renders nothing, and it says "not recorded"
          rather than inventing a date for a run the backend never stamped.

          `rows`, not `inventory` — DiscoverInventoryExport reads `rows || inventory.rows`, and
          `scope.inventory` is the SUMMARY (by_format/by_status/samples), which has no `.rows`
          array at all. Passed as `inventory` alone, `list` was `null` unconditionally, so this
          panel read "The inventory could not be read" on every run, healthy or not — including
          the runs the "0 documents" fix (#835) now correctly counts. `inv` is the same paginated
          per-file read already threaded into DiscoveryResults above as `invRows`. */}
      <DiscoverInventoryExport scanId={scanId} run={runForExport} showActions={false}
                               inventory={scope?.inventory || null} rows={inv?.rows ?? null} /></>
      </AccordionSection>
      </div>
      )}

      {/* THE EMPTY STATE, kept when the per-department block above it was removed (2026-09-02 UI
          simplification PRD). Without it a workspace that has never been scanned shows the header
          and then nothing at all, which reads as a screen that failed to load rather than one with
          nothing to report — and it is the only line that says where a scan is started from now
          that Discover has no scan button of its own.

          The same two guards the removed block carried: `pendingScanLoad` means App has a scan
          whose payload has not arrived (saying "no documents" there would be a claim about an
          estate nobody has read yet), and `hidePreviousInventory` means a newer scan is queued and
          the previous results are deliberately hidden. */}
      {!pendingScanLoad && !hidePreviousInventory && files.length === 0 && (
        <p className="muted" style={{ marginTop: 20 }}>No documents yet — run a scan from Sources.</p>
      )}

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
            <span className="muted" style={{ fontSize: 13, color: 'var(--success-fg)' }}>✓ All recommendations decided — done here? Continue →</span>
          )}
          {/* DX-07 — the discovery-results acknowledgement GATES Assess. Only ever a gate when
              there is something to acknowledge: with no lifecycle recommendations on screen
              `recsToAck` is null and this button behaves exactly as it did before. */}
          {/* `data-advance` is a STABLE hook. Two tests found this control by its label, so a copy
              change broke them for no reason connected to what they assert — they care that the
              advance control is gated, not what it is called this week. */}
          <button data-advance="assess" onClick={() => onAdvance?.()} disabled={pendingActions > 0}
                  title={pendingActions > 0
                    ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending — accept or override each row, or use "Accept all recommendations"`
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
      {sel && <FileDrawer file={mergeLifecycle([sel], inv)[0]} context="discover" onClose={() => setSel(null)} overrideOwner={ownerOf(sel)} delegatedFrom={isDelegated(sel) ? sel.owner : null} scanId={scanId} />}
      {estOnlyFile && <EstateOnlyDrawer file={estOnlyFile} onClose={() => setEstOnlyFile(null)} />}
    </>
  )
}
