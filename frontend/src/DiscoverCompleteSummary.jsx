// Shown after a discovery scan completes — a summary of what was found, with a prominent CTA to
// continue to Assess. Every fact line is a real <li> in a real <ul> (design review 2026-08-29:
// "bullet points in formatting of all the key stats") — three short bulleted lists (headline
// counts, Assessment eligibility, Lifecycle rules), not one flat list, so the existing grouping
// still tells a reader which numbers belong together without re-deriving it from position alone.
// Uses a parent-child layout for assessment eligibility so the relationship between the aggregate
// (not-assessable total) and its breakdown is clear.
//
// The sub-breakdown items are marked as a real list (bullets), not bare stacked divs — the
// screenshot this was built from read as an unstructured wall of numbers. Each label also carries
// a Term glossary tooltip: "metadata-only" and "unsupported" are internal ACP classification
// vocabulary, not terms a reader coming from a source drive already knows.
//
// The breakdown itself is collapsed behind a "Why aren't N assessable?" disclosure, not shown
// open by default (design review): the card's job is to answer "can I move on to Assess", which
// the two top-level numbers (assessable / not-assessable, with percentages) already do — the
// five-way split of WHY only matters to a reader who is about to ask that question, and forcing
// it onto everyone read as a wall of numbers ahead of the one decision the card exists to support.

import { useState } from 'react'
import Term from './Term.jsx'

// Sub-breakdown label -> glossary key.
const SUB_TERM_KEY = {
  unsupported: 'unsupported_format',
  'metadata-only': 'metadata_only_format',
  'eligibility unknown': 'eligibility_unknown',
  excluded: 'excluded_from_scope',
  'could not be opened': 'could_not_be_opened',
}

function fmtDuration(startedAt, discoveredAt) {
  if (!startedAt || !discoveredAt) return null
  const ms = Date.parse(discoveredAt) - Date.parse(startedAt)
  if (!isFinite(ms) || ms < 0) return null
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function n(count) { return Number(count).toLocaleString() }

function pct(part, total) {
  if (!total) return null
  return Math.round((part / total) * 100)
}

// A single assessment-eligibility row: right-aligned count, label, optional percentage.
function EligRow({ count, label, muted = false, pctValue = null }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
      <span style={{ minWidth: '4.2em', textAlign: 'right',
                     fontVariantNumeric: 'tabular-nums',
                     color: muted ? 'var(--muted)' : 'var(--ink)' }}>
        {n(count)}
      </span>
      <span style={{ flex: 1, color: muted ? 'var(--muted)' : 'var(--ink)' }}>
        {label}
      </span>
      {pctValue !== null && (
        <span style={{ minWidth: '2.5em', textAlign: 'right',
                       fontVariantNumeric: 'tabular-nums', color: 'var(--muted)', fontSize: 12.5 }}>
          {pctValue}%
        </span>
      )}
    </div>
  )
}

export default function DiscoverCompleteSummary({
  discoveredCount,
  scannableCount,
  assessableCount,
  metadataOnlyCount,
  unsupportedCount,
  eligibilityUnknownCount = 0,
  lockedCount,
  excludedCount,
  folderCount,
  lifecycleRulesCount,
  archiveCandidates,
  deleteCandidates,
  tagged,
  excInaccessible,
  excMetadataFailure,
  excDeleted,
  inventoryDelta,
  startedAt,
  discoveredAt,
  publishedAt,
  runAt,
  onViewSourceHistory,
  onAdvance,
  onReviewInventory,
  pendingActions = 0,
  needsAck = false,
}) {
  const [breakdownOpen, setBreakdownOpen] = useState(false)
  const elapsed = fmtDuration(startedAt, discoveredAt)
  const ctaDisabled = pendingActions > 0 || needsAck
  const hasLifecycleRules = lifecycleRulesCount != null && lifecycleRulesCount > 0

  // Lifecycle action breakdown pills (only shown when there are results)
  const lifecycleBreakdown = [
    archiveCandidates > 0 && `${n(archiveCandidates)} Archive Candidate${archiveCandidates === 1 ? '' : 's'}`,
    deleteCandidates > 0 && `${n(deleteCandidates)} Delete Candidate${deleteCandidates === 1 ? '' : 's'}`,
    tagged > 0 && `${n(tagged)} tagged`,
  ].filter(Boolean)

  // Exception counts
  const hasExcInaccessible = (excInaccessible ?? 0) > 0
  const hasExcMetadata = (excMetadataFailure ?? 0) > 0
  const hasExcDeleted = (excDeleted ?? 0) > 0
  const hasExceptions = hasExcInaccessible || hasExcMetadata || hasExcDeleted

  // Not-currently-assessable total and sub-breakdown.
  const notAssessableCount = discoveredCount - assessableCount
  const assessablePct = pct(assessableCount, discoveredCount)
  const notAssessablePct = assessablePct !== null ? 100 - assessablePct : null

  // Sub-breakdown items (indented under "Not currently assessable").
  const subBreakdown = [
    (unsupportedCount ?? 0) > 0 && { count: unsupportedCount, label: 'unsupported' },
    (metadataOnlyCount ?? 0) > 0 && { count: metadataOnlyCount, label: 'metadata-only' },
    (eligibilityUnknownCount ?? 0) > 0 && { count: eligibilityUnknownCount, label: 'eligibility unknown' },
    (excludedCount ?? 0) > 0 && { count: excludedCount, label: 'excluded' },
    (lockedCount ?? 0) > 0 && { count: lockedCount, label: 'could not be opened' },
  ].filter(Boolean)

  const ctaLabel = assessableCount > 0
    ? `Assess ${n(assessableCount)} documents →`
    : 'Continue to Assessment →'

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery complete"
             style={{ marginBottom: 16 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '16px 18px', background: 'var(--panel,#fff)',
                                                fontSize: 13.5, color: 'var(--ink)' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                      marginBottom: 14 }}>
          <span style={{ fontWeight: 650, fontSize: 14.5, display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ color: 'var(--green,#1a7f45)', fontSize: 13 }} aria-hidden="true">✓</span>
            Discovery complete
          </span>
          {elapsed && (
            <span style={{ fontSize: 13, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
              {elapsed}
            </span>
          )}
        </div>

        {/* Headline stats — bulleted (design review 2026-08-29: "bullet points in formatting of
            all the key stats" — every fact line in this card is a real <li> now, not just the
            eligibility sub-breakdown below). The timestamp is the SAME `runAt` object
            DiscoveryResults renders below this card (Discover.jsx threads its own prop through
            unchanged) — one resolved instant, shown twice, rather than two components each
            guessing at "when" and risking a mismatch. Absent (`runAt.recorded === false`) is
            rendered as nothing, same as DiscoveryResults — a run that never recorded when
            discovery finished gets no timestamp, not an invented one.

            The count and the timestamp stay TWO SIBLING spans inside the <li>, not one text run —
            e2e/pipeline.spec.js asserts `getByText('N files inventoried', { exact: true })`
            against a real (non-SIM) backend, where `runAt.recorded` is genuinely true.
            Concatenating "· as of …" into the same element broke that exact match on 2026-08-29
            (PR #941's own first CI run) — the span split keeps "N files inventoried" as its own
            exactly-matchable node regardless of whether the timestamp renders beside it. */}
        <ul style={{ listStyle: 'disc', paddingLeft: '1.2em', margin: '0 0 14px',
                     display: 'flex', flexDirection: 'column', gap: 4 }}>
          <li>
            <span>
              {n(discoveredCount)} files inventoried
              {(folderCount ?? 0) > 0 ? ` across ${n(folderCount)} folder${folderCount === 1 ? '' : 's'}` : ''}
            </span>
            {runAt && runAt.recorded && (
              <span className="muted" style={{ fontSize: 12.5, marginLeft: 6 }} title={runAt.label}>
                · as of {runAt.absolute}
                {runAt.stale ? ' · this snapshot is over a day old' : ''}
              </span>
            )}
          </li>
          {/* Scannable vs. whole estate — a THIRD population, not a restatement of the total
              above. scanner.py's _search_drive/_search_folder/_list return only files whose MIME
              type ACP can open (PDF, Office, Google-native, HTML) — filtered BEFORE the
              whole-estate inventory above is even built — while `discoveredCount` counts every
              file of every type. A Drive that is mostly photos and videos alongside a smaller set
              of real documents produces a scannable count far below the total, correctly, every
              time — not an error. Found live 2026-08-29: the top nav bar's own (unlabelled) count
              of this same number read as a contradiction against this card's "files inventoried"
              a few pixels away, because nothing said what it was counting.
              "Scannable" ⊇ "Assessable" below (some scannable-type files are still excluded by
              eligibility — locked, unreadable, …), so this stays a separate bullet rather than
              folding into the Assessable / Not-currently-assessable partition, which keeps
              summing cleanly to the total on its own. */}
          {scannableCount != null && (
            <li style={{ fontSize: 12.5, color: 'var(--muted)' }}>
              {n(scannableCount)} of {n(discoveredCount)} are scannable document types
              (PDF, Office, HTML) — everything else is excluded by file type before assessment
              eligibility is even checked.
            </li>
          )}
        </ul>

        {/* Assessment eligibility */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11.5, fontWeight: 600, textTransform: 'uppercase',
                        letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 6 }}>
            Assessment eligibility
          </div>
          <ul style={{ listStyle: 'disc', paddingLeft: '1.2em', margin: 0,
                       display: 'flex', flexDirection: 'column', gap: 3 }}>
            <li><EligRow count={assessableCount} label="Assessable" pctValue={assessablePct} /></li>
            {notAssessableCount > 0 && (
              <li>
                <EligRow count={notAssessableCount} label="Not currently assessable"
                         muted pctValue={notAssessablePct} />
                {/* Sub-breakdown, collapsed by default behind a "Why aren't N assessable?"
                    disclosure — see the file header comment. */}
                {subBreakdown.length > 0 && (
                  <div style={{ marginTop: 5 }}>
                    <button type="button" className="linklike" aria-expanded={breakdownOpen}
                            onClick={() => setBreakdownOpen((o) => !o)}
                            style={{ fontSize: 12.5, fontWeight: 500, textDecoration: 'none',
                                     color: 'var(--muted)', display: 'inline-flex',
                                     alignItems: 'center', gap: 5 }}>
                      <span aria-hidden="true">{breakdownOpen ? '▾' : '▸'}</span>
                      Why aren&rsquo;t {n(notAssessableCount)} assessable?
                    </button>
                    {breakdownOpen && (
                      <ul style={{ paddingLeft: '1.1em', marginTop: 5, marginBottom: 0,
                                   listStyle: 'disc', display: 'flex', flexDirection: 'column',
                                   gap: 2, fontSize: 12.5, color: 'var(--muted)' }}>
                        {subBreakdown.map(({ count, label }) => (
                          <li key={label} style={{ paddingLeft: 2 }}>
                            {n(count)}{' '}
                            {SUB_TERM_KEY[label]
                              ? <Term k={SUB_TERM_KEY[label]}>{label}</Term>
                              : label}
                          </li>
                        ))}
                        {hasExceptions && (
                          <li style={{ paddingLeft: 2, listStyle: 'none', marginLeft: '-1.1em' }}>
                            {[
                              hasExcInaccessible && `${n(excInaccessible)} inaccessible — skipped`,
                              hasExcMetadata && `${n(excMetadataFailure)} unreadable`,
                              hasExcDeleted && `${n(excDeleted)} deleted during scan`,
                            ].filter(Boolean).join(' · ')}
                          </li>
                        )}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            )}
          </ul>
        </div>

        {/* Lifecycle rules */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11.5, fontWeight: 600, textTransform: 'uppercase',
                        letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 6 }}>
            Lifecycle rules
          </div>
          <ul style={{ listStyle: 'disc', paddingLeft: '1.2em', margin: 0,
                       display: 'flex', flexDirection: 'column', gap: 4 }}>
            {hasLifecycleRules ? (
              <li>
                {n(lifecycleRulesCount)} matched lifecycle rule{lifecycleRulesCount === 1 ? '' : 's'}
                {lifecycleBreakdown.length > 0 && (
                  <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
                    {lifecycleBreakdown.join(' · ')}
                  </div>
                )}
              </li>
            ) : (
              <li style={{ color: 'var(--muted)' }}>No lifecycle rules enabled</li>
            )}
            {/* NOT a comparison against a previous scan, however the field name reads.
                `add_inventory` (api/store.py) upserts scoped to THIS scan_id alone — "new" vs
                "updated" says whether a row was written for the first time in this run's own
                attempt, or re-touched by a checkpoint-resumed retry of the SAME run; "unchanged"
                is presently always 0 (the upsert has no per-column comparison to detect it). On
                the overwhelmingly common case — one clean attempt, no resume — every row reads
                "new", so a label reading "added" there would just restate "N files inventoried"
                above under a header implying growth since last time. A real cross-scan delta
                already exists (store.get_inventory_diff, wired into SourceDrawer's own history
                view) — this is a different signal and must not be read as that one. Rendered
                only when there is something a resume actually changed; gated on
                `updated`/`unchanged` rather than `new` for exactly that reason. */}
            {inventoryDelta && (inventoryDelta.updated > 0 || inventoryDelta.unchanged > 0) && (
              <li>
                {'This run’s writes (including a checkpoint resume): '}
                {[
                  inventoryDelta.new > 0 && `${n(inventoryDelta.new)} written`,
                  inventoryDelta.updated > 0 && `${n(inventoryDelta.updated)} re-written on resume`,
                  inventoryDelta.unchanged > 0 && `${n(inventoryDelta.unchanged)} unchanged`,
                ].filter(Boolean).join(' · ')}
              </li>
            )}
            {/* THE redirect, not a second attempt at the answer. Product decision 2026-08-29:
                this card keeps the narrow, honest "This run's writes" line above (still accurate
                for what it measures — see its own comment) rather than growing a real cross-scan
                diff of its own. A reader who actually wants "has this estate changed since I last
                scanned it" gets sent to the place that can already answer it correctly —
                SourceDrawer's Activity tab, backed by the real store.get_inventory_diff — instead
                of a second, differently-scoped number competing with the first on this same
                card. */}
            {onViewSourceHistory && (
              <li>
                <button type="button" className="linklike" style={{ fontSize: 12.5 }}
                        onClick={onViewSourceHistory}>
                  See what's changed since your last scan of this source →
                </button>
              </li>
            )}
            {publishedAt && (
              <li>
                Enumeration verified complete —{' '}
                {new Date(publishedAt).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
              </li>
            )}
          </ul>
        </div>

        {/* Safety disclaimer — tinted info footer */}
        <div style={{ fontSize: 12.5, color: 'var(--muted)',
                      background: 'var(--info-bg,#f0f7ff)', borderRadius: 6,
                      padding: '6px 10px', marginBottom: 14, display: 'flex',
                      alignItems: 'flex-start', gap: 6, lineHeight: 1.5 }}>
          <span aria-hidden="true" style={{ marginTop: 1 }}>ⓘ</span>
          <span>No documents were assessed or changed.</span>
        </div>

        {/* CTA row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {onReviewInventory && (
            <button onClick={onReviewInventory}
                    style={{ fontSize: 13, fontWeight: 500, padding: '6px 14px',
                             background: 'transparent', color: 'var(--ink)',
                             border: '1px solid var(--line,#e4e8ec)', borderRadius: 8,
                             cursor: 'pointer', whiteSpace: 'nowrap' }}>
              Review inventory
            </button>
          )}
          <button onClick={onAdvance}
                  disabled={ctaDisabled}
                  style={{ fontSize: 14, fontWeight: 600, padding: '9px 18px',
                           background: ctaDisabled ? 'var(--muted-bg,#f1eff3)' : 'var(--ink)',
                           color: ctaDisabled ? 'var(--muted)' : 'var(--panel,#fff)',
                           border: 'none', borderRadius: 8,
                           cursor: ctaDisabled ? 'default' : 'pointer',
                           whiteSpace: 'nowrap' }}
                  title={pendingActions > 0
                    ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending`
                    : needsAck ? 'Approve discovery recommendations above to continue' : undefined}>
            {ctaLabel}
          </button>
          {ctaDisabled && (
            <span className="muted" style={{ fontSize: 12, maxWidth: 240, lineHeight: 1.4 }}>
              {needsAck
                ? 'Approve the recommendations above to continue'
                : `${pendingActions} pending action${pendingActions === 1 ? '' : 's'} — review rows below`}
            </span>
          )}
        </div>
      </div>
    </section>
  )
}
