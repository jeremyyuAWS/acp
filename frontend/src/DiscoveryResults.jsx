import { useState } from 'react'
import DiscoveryLifecycleResults, { supportedDiscoveryRow } from './DiscoveryLifecycleResults.jsx'
import DiscoveryFolderLabel from './DiscoveryFolderLabel.jsx'
import Term from './Term.jsx'
import {
  NOT_RECORDED, acknowledgementSummary, estateSummary, estateTypeReconciliation, plural,
  recommendationReconciliation, recommendationRows, typeReconciliation, unreadableReasons,
} from './discoveryRecommendations.js'
import { contentTypeBreakdown } from './contentTypeBreakdown.js'
import { ageBucketDistribution, sizeBucketDistribution, folderDistribution } from './discoveryDistributions.js'
import LifecycleOverrideControl from './LifecycleOverrideControl.jsx'

// The Discovery results screen (approved design board `DiscoverResults.dc.html`).
//
// What discovery produced, in the order a reviewer needs it: what was found, what could not be
// read, which files a lifecycle rule recommended for review and WHICH RULE said so, the
// acknowledgement that gates Assess, and — last — the reconciliation that shows every discovered
// file landing in exactly one bucket.
//
// Three things this screen refuses to do, each of which this repo has shipped before:
//
//   · It never says a file was archived or deleted. Discovery writes a recommendation and records
//     the rule behind it; the Drive action is a separate, approval-gated step. Every label here is
//     a REVIEW label, and the footnote says so in full.
//   · It never renders a missing answer as a measured zero. The recommendation surface is absent
//     — not zeroed — until the per-file lifecycle columns reach this screen. See
//     `hasLifecycleData` in discoveryRecommendations.js for what is missing and where it lives.
//   · It never prints a count without its population. Both reconciliations show their sum and the
//     total it must equal, on screen, so a reader can add the rows up and check the claim.
//
// Every number is derived from a prop. Nothing here estimates.

const TAG_TONE = {
  arch: { background: '#EEF2FB', border: '1px solid #D3DDF1', color: '#2B4A7E' },
  del: { background: '#FBE9E9', border: '1px solid #E5C4C4', color: '#A32D2D' },
}
const BAR_COLOR = { assessable: '#6B8FC7', other: '#B9B1BD' }
const STAT_COLOR = { archive: '#2B4A7E', delete: '#A32D2D', unreadable: '#8a6d1f', assessable: '#3B6D11' }

const tagStyle = (tone) => ({
  fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 20,
  whiteSpace: 'nowrap', display: 'inline-block', ...TAG_TONE[tone],
})

const Stat = ({ n, label, color, sub = null }) => (
  <div style={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 12,
                padding: '14px 16px', flex: 1, minWidth: 0 }}>
    <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-.01em', lineHeight: 1.15, color }}>
      {n.toLocaleString()}
    </div>
    <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 3 }}>{label}</div>
    {sub && <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
  </div>
)

/** The eligible share, as a string, or null when it cannot be stated.
 *
 *  THE DENOMINATOR IS THE ESTATE LISTING, NOT THE ROWS ON SCREEN, and that is the whole difficulty.
 *  `summary.assessable` is an ESTATE-level figure (it comes from `scope.inventory`), while
 *  `summary.discovered` counts the rows this screen is rendering, which a filter can narrow. Divide
 *  one by the other on a filtered view and you get "183% of the estate" — a true numerator over a
 *  denominator from a different population. Caught by a fixture, not by reading it.
 *
 *  So this takes `listed` and REFUSES to compute without it. No estate denominator, no share: a
 *  percentage whose boundary is unstated is the count-without-its-boundary defect wearing a
 *  percent sign.
 *
 *  Rounded AWAY FROM ZERO for a non-zero count: 22 of 12,408 is 0.18%, and "0%" beside a tile
 *  reading "22" says the estate contains none of what it just counted. `<1%` is the true statement
 *  and the more useful one — it is the whole point of putting a percentage here.
 *
 *  Exported for the test, and because a share of a total is exactly the kind of arithmetic that
 *  gets re-derived slightly differently in a second place. */
export function eligibleShare(eligible, listed) {
  if (typeof eligible !== 'number' || typeof listed !== 'number') return null
  if (!(listed > 0) || eligible < 0) return null
  // A numerator larger than its denominator means they came from different populations. Saying
  // nothing is right: the alternative is printing a figure over 100%, which is what this guard
  // exists to have caught.
  if (eligible > listed) return null
  const pct = (eligible / listed) * 100
  if (eligible === 0) return '0% of the estate'
  if (pct < 1) return '<1% of the estate'
  return `${Math.round(pct)}% of the estate`
}

/** A reconciliation table: one row per bucket, then the sum and the total it must equal. The sum
 *  line is not decoration — it is the claim "these partition the estate", rendered. */
const Reconciliation = ({ id, heading, note, rec, renderLabel }) => (
  <table style={{ width: '100%', borderCollapse: 'collapse' }} aria-labelledby={id}>
    <caption id={id} style={{ captionSide: 'top', textAlign: 'left', fontSize: 12,
                              color: 'var(--muted)', padding: '0 0 8px' }}>{heading}</caption>
    <tbody>
      {rec.buckets.map((b) => (
        <tr key={b.key || b.reason}>
          <td style={{ fontSize: 13 }}>{renderLabel ? renderLabel(b) : b.label}</td>
          <td style={{ textAlign: 'right', fontSize: 13, whiteSpace: 'nowrap' }}>
            {b.count.toLocaleString()}
          </td>
        </tr>
      ))}
      <tr>
        <td style={{ fontSize: 13, fontWeight: 600 }}>
          {rec.balanced
            ? <>Total · {rec.population}</>
            : <>⚠ Total · {rec.population} — {rec.total.toLocaleString()} expected</>}
        </td>
        <td style={{ textAlign: 'right', fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' }}>
          {rec.sum.toLocaleString()}
        </td>
      </tr>
    </tbody>
  </table>
)

export default function DiscoveryResults({
  source = null, files = null, inventory = null, invRows = null, scopeLine = null, runAt = null, policies = null,
  reasonOf = undefined,
  reasonSampleOf = null, reasonFetchLikely = null,
  acknowledged = false, onAcknowledge = null,
  overrides: overridesProp, onOverridesChange,
  onExport = null, actor = null, scanId = null,
  // Lifecycle rules #8 — a human's per-file override of the recommendation itself, distinct from
  // `overrides`/`onOverridesChange` above (which is "Assess anyway", a separate, unreasoned,
  // client-state-only flag). `onOverrideRecommendation(file, reason)` should POST the override and
  // resolve truthy on success; the caller (Discover.jsx) owns refetching the inventory afterward
  // so the recorded override reaches this table on the next render.
  onOverrideRecommendation = null,
  // For support/debugging (2026-08-28): the run's raw `scope` (includes `enumeration` — whether
  // the source was reachable, the raw pre-filter file count, truncation) and its decision-log
  // rows (system.py GET /decisions — the same audit trail a `scan.suspicious_zero` or
  // `scan.unreachable_zero` entry lands in when discovery refuses to publish a zero it can't
  // trust). Both are already loaded client-side for other reasons — Discover.jsx passes them
  // straight through — so showing them here costs no extra request. `runStatus` rides along for
  // the same reason: it is what decides whether the page's OWN "Discovery did not finish" banner
  // (Discover.jsx, run?.status === 'failed') should be showing — printing it here is what lets a
  // "the banner isn't showing but I expected it to be" report be checked directly instead of
  // guessed at.
  rawScope = null, rawDecisions = null, runStatus = null,
}) {
  const [filter, setFilter] = useState('all')
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)
  // Uncontrolled by default, exactly like Discover's own `decisions` prop: a caller that wants the
  // overrides to survive a reload passes its own state in, and one that does not still gets a
  // working control.
  const [localOverrides, setLocalOverrides] = useState([])
  const overrides = overridesProp ?? localOverrides
  const setOverrides = onOverridesChange ?? setLocalOverrides

  const summary = estateSummary(files, inventory)
  // Nothing was read, so nothing is claimed — not "0 files discovered".
  if (!summary) return null

  // Prefer the whole-estate breakdown (every image/video/unsupported file Drive or SharePoint
  // returned, not just what got opened and scored) — see estateTypeReconciliation's own header
  // for why typeReconciliation(files) cannot show them. Falls back only when there is no
  // inventory to read (a local scan, or one predating the field).
  const types = estateTypeReconciliation(inventory) || typeReconciliation(files)
  // null on every source but SharePoint today, and null there too unless the tenant actually
  // returned a content type — see contentTypeBreakdown.js for why that is the honest default.
  const contentTypes = contentTypeBreakdown(files)
  const unread = unreadableReasons(files, reasonOf)
  // Buckets whose RECORDED message names a transport/HTTP failure. Derived from the log, not
  // from the fact that a file failed — a scan with no such messages gets no clause at all.
  const fetchBuckets = (unread && reasonFetchLikely)
    ? unread.buckets.filter((b) => b.recorded && reasonFetchLikely(b.reason))
    : []
  const fetchFiles = fetchBuckets.reduce((n, b) => n + b.count, 0)
  const ageDist = ageBucketDistribution(invRows)
  const sizeDist = sizeBucketDistribution(invRows)
  const folderDist = folderDistribution(invRows?.filter(supportedDiscoveryRow))

  const recRows = recommendationRows(files, policies)
  const recRec = recommendationReconciliation(files)
  const ack = acknowledgementSummary(files, overrides)
  const shown = recRows && (filter === 'all' ? recRows : recRows.filter((r) => r.bucket === filter))
  const maxType = types ? Math.max(1, ...types.buckets.map((b) => b.count)) : 1

  const toggleOverride = (file) => {
    const next = overrides.includes(file) ? overrides.filter((f) => f !== file) : [...overrides, file]
    setOverrides(next)
  }

  return (
    <section className="panel" aria-labelledby="discres-h">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <h2 id="discres-h" style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--muted)' }}>
          DISCOVERY RESULTS
        </h2>
        {/* The boundary the counts below are counts OF, and WHEN they were counted. Both are
            omitted rather than guessed: "no scope recorded" is not evidence of a whole-estate
            scan, and a results header that invented today's date for an undateable run would be
            worse than one that gives no date at all — this estate gets re-scanned, and an
            undated inventory reads exactly like a current one.

            `runAt` is an `inventorySnapshot()` from discoverRunTime.js — resolved, formatted and
            SOURCED. This component still owns no date format; it renders what that module
            resolved, and hangs the provenance off the title so a reader can find out which of the
            three records dated their inventory.

            It used to take a plain string built from `run.completed_at`, which was wrong in a way
            no test caught: under ADR 0020 that column is written at ASSESS finalize, so it is
            NULL on a discover-only run — the exact screen this line lives on — and afterwards
            dates the assessment rather than the listing. `resolveInventoryTime` prefers the real
            run-level stamp, falls back to the newest per-file stamp, and accepts completed_at
            only last, labelled as the upper bound it is. */}
        {(scopeLine || (runAt && runAt.recorded)) && (
          <span className="muted" style={{ fontSize: 12.5 }} title={runAt && runAt.recorded ? runAt.label : undefined}>
            {scopeLine}{scopeLine && runAt && runAt.recorded ? ' · ' : ''}
            {runAt && runAt.recorded ? `listed ${runAt.absolute}` : ''}
            {runAt && runAt.recorded && runAt.stale ? ' · this snapshot is over a day old' : ''}
          </span>
        )}
      </div>
      <p className="muted" style={{ margin: '6px 0 0', lineHeight: 1.5 }}>
        Metadata for every file in scope. Discovery reads names, paths, sizes and dates — no file
        was opened and nothing in the source was changed.
      </p>

      {/* Visible identifier for QA and auditing — the ONLY way to name this exact run when
          reporting a discrepancy or asking support to look something up. Deliberately plain,
          copyable text rather than only the URL: the URL scrolls out of view, gets lost across a
          screenshot crop, and is not what a reviewer thinks to check first. */}
      {scanId && (
        <>
          <p className="muted" style={{ margin: '4px 0 0', fontSize: 11.5,
                                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
            Scan ID: {scanId}{' '}
            <button type="button" className="linklike" style={{ fontSize: 11.5 }}
                    aria-expanded={showRaw} onClick={() => setShowRaw((s) => !s)}>
              {showRaw ? '▾ hide raw scan data' : '▸ show raw scan data (for support)'}
            </button>
          </p>
          {/* The whole point: something a user can select-all and paste into a support thread
              without hunting through DevTools for the right network request and its auth header
              — which is exactly what got asked for after that turned out to be the alternative.
              scope.enumeration (auth_ok/files_found/truncated) and the decision-log rows are the
              two places a "why did this find nothing" investigation actually starts. */}
          {showRaw && (
            <div className="panel" style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <h2 style={{ margin: 0 }}>RAW SCAN DATA</h2>
                <span className="muted" style={{ fontSize: 11.5 }}>
                  scope.enumeration and the decision log — the two places a "why did this find
                  nothing" investigation starts
                </span>
                <button type="button" className="ghost small" style={{ marginLeft: 'auto' }}
                        onClick={async () => {
                          const blob = JSON.stringify(
                            { scan_id: scanId, status: runStatus, scope: rawScope, decisions: rawDecisions }, null, 2)
                          try { await navigator.clipboard.writeText(blob) } catch { /* clipboard may be unavailable */ }
                          setCopied(true); setTimeout(() => setCopied(false), 2000)
                        }}>
                  {copied ? 'Copied' : 'Copy to clipboard'}
                </button>
              </div>
              <pre style={{ fontSize: 11, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            maxHeight: 360, overflow: 'auto', margin: 0,
                            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
                {JSON.stringify({ scan_id: scanId, status: runStatus, scope: rawScope, decisions: rawDecisions }, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}

      <div style={{ display: 'flex', gap: 12, marginTop: 16, flexWrap: 'wrap' }}>
        <Stat n={summary.discovered} label={`${plural(summary.discovered, 'file', 'files')} discovered`} />
        {/* SECOND, because it qualifies the number beside it. Discovery lists everything; only some
            of it carries an accessibility test at all, and on an estate of 12,408 files where 22
            are Office or PDF that single number reframes the engagement. It was previously visible
            only inside a funnel and a bar chart — never as a headline.

            Absent when nothing measured it. A "0" here would assert the estate contains nothing
            testable, which is a discovery result nobody obtained. */}
        {summary.assessable != null && (
          <Stat n={summary.assessable} label="can be assessed" color={STAT_COLOR.assessable}
                sub={eligibleShare(summary.assessable, summary.estateListed)} />
        )}
        {/* Absent until the lifecycle columns reach this screen — a "0" here would be a claim
            about the estate made from a field nobody read. */}
        {summary.archive != null && (
          <Stat n={summary.archive} label="tagged for archive review" color={STAT_COLOR.archive} />
        )}
        {summary.delete != null && (
          <Stat n={summary.delete} label="tagged for deletion review" color={STAT_COLOR.delete} />
        )}
        <Stat n={summary.unreadable} label={<Term k="unreadable">could not be read</Term>} color={STAT_COLOR.unreadable} />
      </div>

      {summary.truncated && (
        <p className="scopewarn" role="status" style={{ fontSize: 12.5, margin: '8px 0 0', lineHeight: 1.5 }}>
          ⚠ The listing hit its cap before the end of the estate, so every count on this screen is
          a floor, not a total.
        </p>
      )}

      {/* Two totals that can legitimately differ — the rows on this screen, and the whole-estate
          listing the scan stored. Said out loud, because a filtered view that reads as the estate
          is the count-without-its-boundary defect this codebase keeps re-learning. */}
      {summary.estateListed != null && summary.estateListed !== summary.discovered && (
        <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0', lineHeight: 1.5 }}>
          This discovery listed {summary.estateListed.toLocaleString()} files in the estate.
          The {summary.discovered.toLocaleString()} counted here are the rows on this screen —
          most breakdowns below count over those; By file type counts over the whole estate
          listing when it can (its own total says which population it used).
        </p>
      )}

      {summary.unreadable > 0 && (
        <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0', lineHeight: 1.5 }}>
          The {summary.unreadable.toLocaleString()} unreadable {plural(summary.unreadable, 'item is', 'items are')} listed
          separately below and {plural(summary.unreadable, 'is', 'are')} counted inside
          the {summary.discovered.toLocaleString()} — discovery listed {plural(summary.unreadable, 'it', 'them')},
          so {plural(summary.unreadable, 'it belongs', 'they belong')} in the estate, but no
          recommendation was produced for {plural(summary.unreadable, 'it', 'them')}.
        </p>
      )}

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap', marginTop: 8 }}>
        {types && (
          <div className="panel" style={{ flex: '1 1 380px' }}>
            <h2>BY FILE TYPE</h2>
            {types.buckets.map((b) => (
              <div className="critrow" key={b.key} style={{ gridTemplateColumns: '110px 1fr 56px' }}>
                <span className="critlabel" style={{ fontSize: 13 }}>{b.label}</span>
                <span className="track">
                  <i style={{ width: `${(b.count / maxType) * 100}%`,
                              background: b.assessable ? BAR_COLOR.assessable : BAR_COLOR.other }} />
                </span>
                <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}</span>
              </div>
            ))}
            <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr 56px', gap: 12,
                          marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)',
                          fontSize: 13, fontWeight: 600 }} role="status">
              <span>{types.balanced ? 'Total' : '⚠ Total'}</span>
              <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                every type, added up — {types.population}
              </span>
              <span style={{ textAlign: 'right' }}>{types.sum.toLocaleString()}</span>
            </div>
            <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
              Grey types are inventoried but carry no WCAG test. They stay visible here rather than
              disappearing — unsupported is not the same as passed.
            </p>
          </div>
        )}

        {/* Absent on every source but SharePoint, and absent there too unless the tenant actually
            returned a content type — this is a real column an operator's library may or may not
            use, not the department/tag classification the panel above the KPI row already speaks
            to honestly. See contentTypeBreakdown.js. */}
        {contentTypes && (
          <div className="panel" style={{ flex: '1 1 380px' }}>
            <h2>BY CONTENT TYPE <span className="muted" style={{ fontWeight: 400 }}>· from SharePoint</span></h2>
            {contentTypes.buckets.map((b) => (
              <div className="critrow" key={b.key} style={{ gridTemplateColumns: '160px 1fr 56px' }}>
                <span className="critlabel" style={{ fontSize: 13, color: b.known ? undefined : 'var(--muted)' }}>
                  <DiscoveryFolderLabel folder={b.label} source={source} />
                </span>
                <span className="track">
                  <i style={{ width: `${(b.count / Math.max(1, ...contentTypes.buckets.map((x) => x.count))) * 100}%`,
                              background: b.known ? BAR_COLOR.assessable : BAR_COLOR.other }} />
                </span>
                <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}</span>
              </div>
            ))}
            <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
              Read from the source's own SharePoint Content Type column, where the library uses
              one. Not every file will carry one — that is the source's answer, not a gap in the
              scan.
            </p>
          </div>
        )}

        {ageDist && (
          <div className="panel" style={{ flex: '1 1 340px' }}>
            <h2>BY AGE <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>· last modified</span></h2>
            {ageDist.buckets.map((b) => (
              <div className="critrow" key={b.key} style={{ gridTemplateColumns: '140px 1fr 56px' }}>
                <span className="critlabel" style={{ fontSize: 13 }}>{b.label}</span>
                <span className="track">
                  <i style={{ width: `${(b.count / Math.max(1, ...ageDist.buckets.map((x) => x.count))) * 100}%`,
                              background: BAR_COLOR.assessable }} />
                </span>
                <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}</span>
              </div>
            ))}
            <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 56px', gap: 12,
                          marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)',
                          fontSize: 13, fontWeight: 600 }} role="status">
              <span>{ageDist.balanced ? 'Total' : '⚠ Total'}</span>
              <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>{ageDist.population}</span>
              <span style={{ textAlign: 'right' }}>{ageDist.sum.toLocaleString()}</span>
            </div>
          </div>
        )}

        {sizeDist && (
          <div className="panel" style={{ flex: '1 1 340px' }}>
            <h2>BY SIZE</h2>
            {sizeDist.buckets.map((b) => (
              <div className="critrow" key={b.key} style={{ gridTemplateColumns: '140px 1fr 56px' }}>
                <span className="critlabel" style={{ fontSize: 13 }}>{b.label}</span>
                <span className="track">
                  <i style={{ width: `${(b.count / Math.max(1, ...sizeDist.buckets.map((x) => x.count))) * 100}%`,
                              background: BAR_COLOR.other }} />
                </span>
                <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}</span>
              </div>
            ))}
            <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 56px', gap: 12,
                          marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)',
                          fontSize: 13, fontWeight: 600 }} role="status">
              <span>{sizeDist.balanced ? 'Total' : '⚠ Total'}</span>
              <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>{sizeDist.population}</span>
              <span style={{ textAlign: 'right' }}>{sizeDist.sum.toLocaleString()}</span>
            </div>
          </div>
        )}

        {folderDist && (
          <div className="panel" style={{ flex: '1 1 380px' }}>
            <h2>BY FOLDER</h2>
            {folderDist.buckets.map((b) => (
              <div className="critrow" key={b.key} style={{ gridTemplateColumns: '1fr 1fr 56px' }}>
                <span className="critlabel" title={b.label}
                      style={{ fontSize: 12, overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <DiscoveryFolderLabel folder={b.label} source={source} />
                </span>
                <span className="track">
                  <i style={{ width: `${(b.count / Math.max(1, ...folderDist.buckets.map((x) => x.count))) * 100}%`,
                              background: BAR_COLOR.assessable }} />
                </span>
                <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}</span>
              </div>
            ))}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 56px', gap: 12,
                          marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)',
                          fontSize: 13, fontWeight: 600 }} role="status">
              <span>{folderDist.balanced ? 'Total' : '⚠ Total'}</span>
              <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>{folderDist.population}</span>
              <span style={{ textAlign: 'right' }}>{folderDist.sum.toLocaleString()}</span>
            </div>
          </div>
        )}

        {unread && (
          <div className="panel" style={{ flex: '1 1 340px' }}>
            <h2>COULD NOT BE READ</h2>
            {unread.total === 0 ? (
              <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.5 }}>
                Every one of the {summary.discovered.toLocaleString()} files on this screen was
                read. Nothing was skipped.
              </p>
            ) : (
              <>
                <Reconciliation
                  id="discres-unread" heading="Reason · files" rec={unread}
                  renderLabel={(b) => (b.recorded
                    ? (
                      <span title={(reasonSampleOf && reasonSampleOf(b.reason)) || undefined}>
                        {b.reason}
                      </span>
                    )
                    : <span className="muted">No reason was recorded for these</span>)} />
                {/* ONE orienting clause, and only when the recorded message names a transport or
                    HTTP failure. "Could not be read" reads as "the document is broken", and that
                    reading is what sent a whole investigation to inspect 22 SharePoint documents
                    that had never been fetched at all — the download was routed to the wrong API.
                    This does not re-diagnose the failure; it says which end of it the recorded
                    message is about. */}
                {fetchBuckets.length > 0 && (
                  <p className="scopewarn" role="status"
                     style={{ fontSize: 12, margin: '10px 0 0', lineHeight: 1.5 }}>
                    {fetchFiles.toLocaleString()} of {unread.total.toLocaleString()} failed with a
                    transport or HTTP error ({fetchBuckets.map((b) => b.reason).join(', ')}), so
                    {fetchFiles === 1 ? ' that file' : ' those files'} may never have been fetched.
                    That points at the source or the connection, not at the
                    {fetchFiles === 1 ? ' document' : ' documents'}.
                  </p>
                )}
                <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
                  Shown apart from the recommendations so a partial read is never mistaken for a
                  complete one. A file with no recorded reason is counted as exactly that — the
                  reason is never guessed from the failure. Hover a reason for the message the scan
                  actually recorded.
                </p>
              </>
            )}
          </div>
        )}
      </div>

      <DiscoveryLifecycleResults rows={invRows} policies={policies} scanId={scanId} />

      {/* RECOMMENDATIONS — rendered only when the per-file lifecycle outcome reached this screen.
          An empty table and an unread field must never look the same. */}
      {recRows && (
        <div className="panel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0 }}>RECOMMENDATIONS</h2>
            <span className="muted" style={{ fontSize: 12 }}>
              {recRows.length.toLocaleString()} of {summary.discovered.toLocaleString()} discovered {plural(summary.discovered, 'file', 'files')} ·
              every tag names the rule that produced it
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }} role="group" aria-label="Filter recommendations">
              {[['all', 'All'], ['archive', 'Archive'], ['delete', 'Deletion']].map(([k, label]) => (
                <button key={k} className="ghost" style={{ padding: '6px 12px', fontSize: 13 }}
                        aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
              ))}
            </span>
          </div>

          {shown.length === 0 ? (
            <p className="muted" style={{ fontSize: 13, margin: 0 }}>
              {recRows.length === 0
                ? 'The enabled lifecycle rules matched no file in this discovery.'
                : 'No file matches this filter.'}
            </p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ width: '32%' }}>File</th>
                  <th style={{ width: '15%' }}>Recommendation</th>
                  <th style={{ width: '19%' }}>Matched rule</th>
                  <th>Reason</th>
                  <th style={{ width: '15%' }}>Override</th>
                  <th style={{ width: '11%', textAlign: 'right' }}>Assess anyway</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.file}>
                    <td>
                      <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5 }}>
                        {r.path}
                      </span>
                    </td>
                    <td><span style={tagStyle(r.bucket === 'delete' ? 'del' : 'arch')}>{r.tag}</span></td>
                    <td style={{ fontSize: 13 }}>
                      {r.rule || <span className="muted">Rule {NOT_RECORDED}</span>}
                      {r.conflicted && <span className="muted"> (conflict)</span>}
                    </td>
                    <td className="muted" style={{ fontSize: 12.5 }}>
                      {r.reason || <span>No reason was recorded for this match.</span>}
                    </td>
                    <td style={{ fontSize: 12.5 }}>
                      <LifecycleOverrideControl file={r.file} override={r.override}
                                                disabled={!onOverrideRecommendation}
                                                onSave={onOverrideRecommendation} />
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <input type="checkbox" style={{ width: 15, height: 15 }}
                             aria-label={`Assess ${r.file} anyway`}
                             checked={overrides.includes(r.file)}
                             onChange={() => toggleOverride(r.file)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="muted" style={{ fontSize: 11.5, margin: '14px 0 0', lineHeight: 1.55 }}>
            These are recommendations only. <b>Nothing is archived, moved or trashed</b> — ACP
            attaches a flag and records which rule produced it. <i>Keep this file</i> records that
            you reviewed the recommendation and are keeping the file anyway, with why — it changes
            no tag and moves no file. Ticking <i>Assess anyway</i> keeps that flag and records that
            you want this file assessed; it changes no tag and moves no file.
          </p>
        </div>
      )}

      {/* The reconciliation, last: every discovered file in exactly one bucket, with the sum on
          screen beside the total it has to equal. */}
      {recRec && (
        <div className="panel">
          <h2>EVERY DISCOVERED FILE, IN ONE BUCKET</h2>
          <Reconciliation id="discres-recon" rec={recRec}
                          heading={`Bucket · ${recRec.population}`} />
          <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            {recRec.balanced
              ? `The buckets add up to the ${recRec.total.toLocaleString()} ${plural(recRec.total, 'file', 'files')} discovered, so no file is counted twice and none is missing.`
              : `⚠ The buckets sum to ${recRec.sum.toLocaleString()} but ${recRec.total.toLocaleString()} ${plural(recRec.total, 'file was', 'files were')} discovered — do not read these as a partition of the estate.`}
          </p>
        </div>
      )}

      {/* The acknowledgement, which gates Assess. Absent when there is nothing to acknowledge. */}
      {ack && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
                      borderRadius: 12, background: 'var(--card)', border: '1px solid var(--line)',
                      flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
            <input type="checkbox" style={{ width: 15, height: 15 }} checked={!!acknowledged}
                   onChange={(e) => onAcknowledge?.(e.target.checked)} />
            I approve these {ack.total.toLocaleString()} {plural(ack.total, 'recommendation', 'recommendations')}.
          </label>
          <span className="muted" style={{ fontSize: 11.5, lineHeight: 1.5 }}>
            {ack.archive.toLocaleString()} for archive review · {ack.delete.toLocaleString()} for
            deletion review
            {ack.overridden > 0 && <> · {ack.overridden.toLocaleString()} {plural(ack.overridden, 'file', 'files')} overridden to assess anyway</>}
            {' · '}approving unblocks Assess and archives, moves and deletes nothing
            {/* Named only when we HAVE them. An unattributed approval must not claim attribution. */}
            {actor && <> · approving as {actor}</>}
            {scanId && <> · recorded against this run</>}
          </span>
          {onExport && (
            <span style={{ marginLeft: 'auto' }}>
              <button className="ghost" style={{ padding: '6px 12px', fontSize: 13 }} onClick={onExport}>
                Export inventory
              </button>
            </span>
          )}
        </div>
      )}
    </section>
  )
}
