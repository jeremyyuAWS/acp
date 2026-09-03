import { useState } from 'react'
import { ASSESSABLE_FORMATS, assessmentEligible } from './estateFunnel.js'
import AccordionSection from './AccordionSection.jsx'

// ── Estate Progress Panel ───────────────────────────────────────────────────
// Three interlocking components:
//   1. Funnel      — horizontal stage flow, hero component
//   2. DocTypes    — horizontal bars, eligible vs ineligible by format
//   3. PendingWork — action table showing where work is accumulating
//
// All four read from the same data model so the numbers can never disagree.

const nf = new Intl.NumberFormat('en-US')
const pct = (a, b) => (b > 0 ? Math.round((a / b) * 100) : 0)
const pctLabel = (a, b) => `${pct(a, b)}%`

// ── 1. Horizontal estate progress funnel ─────────────────────────────────────

const STAGE_COLOR = ['#46303F', '#7a5c8e', 'var(--info-fg)', '#067647']
const STAGE_LIGHT = ['#f3eef6', '#ede7f6', '#eff8ff', '#ecfdf3']
const STAGE_FG    = ['#46303F', '#4B3460', '#0B3A7A', '#074D31']

function FunnelStage({ label, count, ofDiscovered, pending, pendingLabel, color, lightColor, fgColor, onClick, isLast }) {
  const pctNum = pct(count, ofDiscovered)
  const width = Math.max(52, pctNum)   // never collapse below readable width
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, flex: 1, minWidth: 0 }}>
      {/* Stage box */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <button
          onClick={onClick}
          style={{ width: '100%', background: lightColor, border: `2px solid ${color}`, borderRadius: 12,
                   padding: '14px 16px', cursor: onClick ? 'pointer' : 'default', textAlign: 'left',
                   transition: 'filter .15s' }}
          onMouseEnter={(e) => onClick && (e.currentTarget.style.filter = 'brightness(0.95)')}
          onMouseLeave={(e) => (e.currentTarget.style.filter = '')}
        >
          <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em',
                        color: fgColor, marginBottom: 6 }}>{label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: fgColor, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
            {count == null ? '—' : nf.format(count)}
          </div>
          <div style={{ fontSize: 12.5, color: fgColor, opacity: 0.75, marginTop: 4 }}>
            {count != null && ofDiscovered ? pctLabel(count, ofDiscovered) + ' of estate' : ''}
          </div>
          {/* Progress bar showing proportion of discovered */}
          <div style={{ marginTop: 10, height: 4, borderRadius: 2, background: `${color}33` }}>
            <div style={{ width: `${width}%`, height: '100%', borderRadius: 2, background: color,
                          transition: 'width .6s cubic-bezier(.4,0,.2,1)' }} />
          </div>
        </button>
        {/* Pending label below stage */}
        {pending != null && pending > 0 && (
          <div style={{ textAlign: 'center', marginTop: 6, fontSize: 11.5, color: 'var(--muted)' }}>
            <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{nf.format(pending)}</span>
            {' '}{pendingLabel || 'pending'}
          </div>
        )}
      </div>
      {/* Arrow connector */}
      {!isLast && (
        <div style={{ alignSelf: 'center', color: 'var(--muted)', fontSize: 20, padding: '0 6px',
                      flexShrink: 0, lineHeight: 1, marginTop: -16 }}>›</div>
      )}
    </div>
  )
}

function SideBranch({ count, label, color }) {
  if (!count) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)',
                  padding: '4px 10px', background: 'var(--bg)', border: '1px solid var(--line)',
                  borderRadius: 8 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span><b style={{ color: 'var(--ink)' }}>{nf.format(count)}</b> {label}</span>
    </div>
  )
}

// ── 3. Document types & eligibility ──────────────────────────────────────────

function DocTypeRow({ label, total, eligible, assessed, ineligible }) {
  const eligPct = pct(eligible, total)
  const assPct  = pct(assessed, total)
  const elig = eligible ?? 0
  const inelig = ineligible ?? (total - elig)
  const maxW = total

  return (
    <div style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                    marginBottom: 6, gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--ink)' }}>{label}</span>
        <span style={{ fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}>
          {nf.format(total)} · <span style={{ color: eligPct >= 80 ? 'var(--success-fg)' : 'var(--warn-fg)',
                                              fontWeight: 600 }}>{eligPct}% eligible</span>
        </span>
      </div>
      {/* Stacked bar: eligible (plum) + ineligible (grey) */}
      <div style={{ height: 10, borderRadius: 5, background: '#ece8ee', overflow: 'hidden',
                    display: 'flex' }}>
        <div style={{ width: `${Math.max(0, pct(elig, maxW))}%`, background: '#7a5c8e',
                      borderRadius: '5px 0 0 5px', transition: 'width .5s ease' }} />
        <div style={{ width: `${Math.max(0, pct(inelig, maxW))}%`, background: '#c8b8d0',
                      transition: 'width .5s ease' }} />
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 5, fontSize: 11.5, color: 'var(--muted)' }}>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                              background: '#7a5c8e', marginRight: 4, verticalAlign: 'middle' }} />
          {nf.format(elig)} eligible</span>
        {inelig > 0 && (
          <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                                background: '#c8b8d0', marginRight: 4, verticalAlign: 'middle' }} />
            {nf.format(inelig)} not eligible</span>
        )}
        {assessed != null && (
          <span style={{ marginLeft: 'auto' }}>{nf.format(assessed)} assessed</span>
        )}
      </div>
    </div>
  )
}

// ── 4. Pending work by stage ──────────────────────────────────────────────────

const URGENCY = {
  low:    { bg: '#F9FAFB', fg: '#374151', dot: '#9CA3AF' },
  medium: { bg: '#FFFBEB', fg: '#78350F', dot: '#F59E0B' },
  high:   { bg: '#FEF3F2', fg: '#7A271A', dot: '#B42318' },
}

function PendingRow({ stage, pending, blocked, action, urgency = 'low', onClick }) {
  const u = URGENCY[urgency] || URGENCY.low
  if (pending == null) return null
  return (
    <tr>
      <td style={{ paddingLeft: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: u.dot, flexShrink: 0 }} />
          <span style={{ fontSize: 13.5 }}>{stage}</span>
        </div>
      </td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        <b style={{ fontSize: 14 }}>{nf.format(pending)}</b>
      </td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {blocked > 0
          ? <span style={{ color: '#B42318', fontWeight: 600, fontSize: 13 }}>{nf.format(blocked)}</span>
          : <span className="muted">—</span>}
      </td>
      <td>
        {onClick
          ? <button className="linkbtn" style={{ fontSize: 13 }} onClick={onClick}
                    aria-label={`${action}: ${nf.format(pending)} pending in ${stage}`}>
              {action} →
            </button>
          : <span className="muted" style={{ fontSize: 13 }}>{action}</span>}
      </td>
    </tr>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

// One of this panel's three detail sections. `collapsible` decides whether the heading is a
// disclosure button (Overview, per the 2026-09-02 UI simplification PRD) or a plain heading
// (Discover, which mounts the same component and is unchanged by that PRD).
//
// Declared at module scope on purpose: an inline component would be a new type on every
// render of the parent, remounting the accordion and snapping every section back to its
// default state the moment anything else on the panel changed.
function PanelSection({ collapsible, accId, heading, label, defaultOpen = true, actions = null, style, children }) {
  if (collapsible) {
    return (
      <AccordionSection id={accId} title={heading} ariaLabel={label}
                        defaultOpen={defaultOpen} actions={actions} style={style}>
        {children}
      </AccordionSection>
    )
  }
  return (
    <section className="panel" aria-label={label} style={style}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{heading}</h2>
        {actions}
      </div>
      {children}
    </section>
  )
}

export default function EstateProgressPanel({
  inventory,       // run.scope?.inventory
  analysed,        // files actually assessed (count)
  needFix,         // docs with unresolved findings
  certifiable,     // run.certifiable — verified docs
  published,       // docs with published_at
  errorCount,      // run.error — files that couldn't open
  files,           // full file array for per-type breakdowns
  estateFiles,     // files + estate-only (for type counts)
  onGo,            // (tab) => void — navigate to a tab
  afterProgress = null, // optional content directly below the four funnel stages
  // Overview renders the three detail sections below as accordions; Discover keeps them
  // as plain sections. Opt-in, so no other caller's DOM changes.
  collapsible = false,
}) {
  const [showSideBranches, setShowSideBranches] = useState(false)

  // SELF-HEAL A STALE ZERO. Root cause fixed backend-side 2026-08-28 — the durable Discover job
  // used to flip scan_runs.status to 'discovered' before scope.inventory was persisted, so a
  // reader in that window wrote "0 discovered" permanently. New scans cannot hit it; a scan that
  // already recorded the bad snapshot re-reads it on every refresh, because a refresh does not
  // repair persisted data. Once the rows exist, file_records has been backfilled from
  // scan_inventory (ADR 0020's get_scan fallback), so `files.length` is ground truth here.
  //
  // Only an EXPLICIT zero is overridden, and only when there are rows to override it with. An
  // ABSENT `discovered` stays absent and still renders as an em dash: "we did not measure" and
  // "we measured nothing" are different claims, and files.length is not evidence for the second.
  // This moved here from DiscoverCompleteSummary, which was unmounted on 2026-09-02.
  const rawDiscovered = inventory?.discovered ?? null
  const discovered = (rawDiscovered === 0 && (files?.length ?? 0) > 0) ? files.length : rawDiscovered
  // `assessmentEligible`, not a bare field read: it prefers the direct `assessment_eligible` and
  // falls back to the older `by_status.assessable` shape, so a scan recorded under either shape
  // reports the same eligible count here as it does everywhere else that asks estateFunnel.
  const eligible   = assessmentEligible(inventory)
  const assessed   = analysed ?? null
  const remediated = certifiable ?? null

  // Pending counts between stages
  const eligPending = (discovered != null && eligible != null) ? Math.max(0, discovered - eligible) : null
  const assPending  = (eligible   != null && assessed   != null) ? Math.max(0, eligible - assessed) : null
  const remPending  = needFix ?? null
  const relPending  = (remediated != null && (published ?? 0) != null) ? Math.max(0, remediated - (published ?? 0)) : null

  // Side branches — files that fell out of the funnel
  const unsupported = (inventory?.by_status?.unsupported) ?? null
  const excluded    = (inventory?.by_status?.excluded)    ?? null
  const failed      = errorCount ?? null

  // ── Document types ──────────────────────────────────────────────────────
  const typeMap = {}
  for (const f of (estateFiles || [])) {
    const t = (f.type || 'other').toLowerCase()
    if (!typeMap[t]) typeMap[t] = { total: 0, assessed: 0 }
    typeMap[t].total++
    if (f.score != null) typeMap[t].assessed++
  }
  const docTypeRows = Object.entries(typeMap)
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 6)
    .map(([type, { total, assessed: ass }]) => {
      const isEligible = ASSESSABLE_FORMATS.includes(type)
      return {
        label: type.toUpperCase(),
        total,
        eligible: isEligible ? total : 0,
        ineligible: isEligible ? 0 : total,
        assessed: ass,
      }
    })

  // Also add inventory-level format breakdown if available and richer
  const invFormats = inventory?.by_format
  const docRows = invFormats
    ? Object.entries(invFormats)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([fmt, cnt]) => {
          const isElig = ASSESSABLE_FORMATS.includes(fmt)
          const typeLookup = typeMap[fmt] || {}
          return {
            label: fmt.toUpperCase(),
            total: cnt,
            eligible: isElig ? cnt : 0,
            ineligible: isElig ? 0 : cnt,
            assessed: typeLookup.assessed ?? null,
          }
        })
    : docTypeRows

  // ── Pending work urgency thresholds ─────────────────────────────────────
  const urgencyOf = (n, warn, crit) =>
    n == null ? 'low' : n >= crit ? 'high' : n >= warn ? 'medium' : 'low'

  const hasAnyData = discovered != null || (files && files.length > 0)

  if (!hasAnyData) return null

  return (
    <>
      {/* ── Estate progress funnel ────────────────────────────────────── */}
      <PanelSection collapsible={collapsible} accId="estate-progress"
                    heading="Estate progress" label="Estate progress funnel"
                    defaultOpen
                    actions={(unsupported || excluded || failed) ? (
                      <button className="linkbtn" type="button" style={{ fontSize: 12 }}
                              onClick={() => setShowSideBranches((v) => !v)}>
                        {showSideBranches ? 'Hide' : 'Show'} exclusions
                      </button>
                    ) : null}>

        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
          <FunnelStage
            label="Discovered"
            count={discovered}
            ofDiscovered={discovered}
            pending={eligPending}
            pendingLabel="not eligible"
            color={STAGE_COLOR[0]} lightColor={STAGE_LIGHT[0]} fgColor={STAGE_FG[0]}
            onClick={() => onGo?.('discover')}
          />
          <FunnelStage
            label="Eligible"
            count={eligible}
            ofDiscovered={discovered}
            pending={assPending}
            pendingLabel="awaiting assessment"
            color={STAGE_COLOR[1]} lightColor={STAGE_LIGHT[1]} fgColor={STAGE_FG[1]}
            onClick={() => onGo?.('assess')}
          />
          <FunnelStage
            label="Assessed"
            count={assessed}
            ofDiscovered={discovered}
            pending={remPending}
            pendingLabel="with findings"
            color={STAGE_COLOR[2]} lightColor={STAGE_LIGHT[2]} fgColor={STAGE_FG[2]}
            onClick={() => onGo?.('remediate')}
          />
          <FunnelStage
            label="Remediated"
            count={remediated}
            ofDiscovered={discovered}
            pending={relPending != null && relPending > 0 ? relPending : null}
            pendingLabel="pending release"
            color={STAGE_COLOR[3]} lightColor={STAGE_LIGHT[3]} fgColor={STAGE_FG[3]}
            isLast
            onClick={() => onGo?.('monitor')}
          />
        </div>

        {/* Side branches — unsupported / excluded / failed */}
        {showSideBranches && (unsupported || excluded || failed) && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14,
                        paddingTop: 14, borderTop: '1px solid var(--line)' }}>
            <SideBranch count={unsupported} label="unsupported format" color="#9a948f" />
            <SideBranch count={excluded}    label="excluded (ACP output)" color="#c6ccc2" />
            <SideBranch count={failed}      label="could not be opened" color="#B42318" />
          </div>
        )}
      </PanelSection>

      {afterProgress}

      {/* ── Document types + Pending work ────────────────────────────── */}
      <div className="chartrow" style={{ marginTop: 0 }}>

        {/* Document types & eligibility */}
        {docRows.length > 0 && (
          <PanelSection collapsible={collapsible} accId={collapsible ? 'estate-composition' : 'doc-types'}
                        heading={collapsible ? 'Estate composition' : <>Document types &amp; eligibility</>}
                        label={collapsible ? 'Estate composition' : 'Document types and eligibility'}
                        defaultOpen={!collapsible} style={{ margin: 0 }}>
            <p className="muted" style={{ margin: '0 0 2px', fontSize: 12 }}>
              Eligible = assessable format. Ineligible = image, video, audio, or other.
            </p>
            {docRows.map((row) => (
              <DocTypeRow key={row.label} {...row} />
            ))}
          </PanelSection>
        )}

        {/* Pending work by stage */}
        <PanelSection collapsible={collapsible} accId={collapsible ? 'operational-details' : 'pending-work'}
                      heading={collapsible ? 'Operational details' : 'Pending work by stage'}
                      label={collapsible ? 'Operational details' : 'Pending work by stage'}
                      defaultOpen={!collapsible} style={{ margin: 0 }}>
          <div className="tablewrap">
            <table style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 0 }}>Stage</th>
                  <th style={{ textAlign: 'right' }}>Pending</th>
                  <th style={{ textAlign: 'right' }}>Blocked</th>
                  <th>Next action</th>
                </tr>
              </thead>
              <tbody>
                <PendingRow
                  stage="Eligibility review"
                  pending={eligPending}
                  blocked={failed ?? 0}
                  action="Review exclusions"
                  urgency={urgencyOf(eligPending, 50, 200)}
                  onClick={eligPending > 0 ? () => onGo?.('discover') : undefined}
                />
                <PendingRow
                  stage="Assessment"
                  pending={assPending}
                  blocked={0}
                  action="Continue assessment"
                  urgency={urgencyOf(assPending, 100, 500)}
                  onClick={assPending > 0 ? () => onGo?.('assess') : undefined}
                />
                <PendingRow
                  stage="Remediation"
                  pending={remPending}
                  blocked={0}
                  action="Start remediation"
                  urgency={urgencyOf(remPending, 50, 200)}
                  onClick={remPending > 0 ? () => onGo?.('remediate') : undefined}
                />
                {relPending != null && (
                  <PendingRow
                    stage="Release approval"
                    pending={relPending}
                    blocked={0}
                    action="Review releases"
                    urgency="low"
                    onClick={relPending > 0 ? () => onGo?.('monitor') : undefined}
                  />
                )}
              </tbody>
            </table>
          </div>
          {(eligPending == null && assPending == null && remPending == null) && (
            <p className="muted" style={{ margin: '8px 0 0', fontSize: 13 }}>
              No pending work — run a scan to populate.
            </p>
          )}
        </PanelSection>

      </div>
    </>
  )
}
