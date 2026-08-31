import ScanScopeWizard from './ScanScopeWizard.jsx'

// ── The single, app-level scan-scope REVIEW modal ────────────────────────────────────────────────
//
// Every scan in the product now opens this gate first, whatever the entry point (Overview,
// Discover, the Sources tab, EmptyState/ScanSetup, or the Drive/SharePoint browse panels). It was
// lifted out of Integrations.jsx — where only the Sources tab reached it — so the scope/behavior
// review can no longer be bypassed by Discover, single-file, or browse-panel scans. See App.jsx's
// `pendingScan`/`requestScan` gate.
//
// It shows, top to bottom: the sources included (informational), the four scan-behavior toggles
// (only when their setters are wired — the browse panels omit them, since their client-side
// download+assess path does not read them), an honest estimate line, and the Formats & WCAG
// criteria wizard, which owns its own "Start scan →"/Cancel footer and scope persistence.

// iOS-style switch for the scan-time options (moved here from Integrations.jsx).
export function ScanSwitch({ on, onToggle, label, title }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={onToggle} title={title}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 9, cursor: 'pointer', font: 'inherit',
               border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit',
               borderRadius: 999, padding: '5px 13px 5px 7px' }}>
      <span aria-hidden="true" style={{ position: 'relative', width: 36, height: 20, borderRadius: 10,
            background: on ? '#6D28D9' : '#c6c6cf', transition: 'background .15s', flexShrink: 0 }}>
        <span style={{ position: 'absolute', top: 2, left: on ? 18 : 2, width: 16, height: 16, borderRadius: '50%',
              background: '#fff', transition: 'left .15s', boxShadow: '0 1px 2px rgba(0,0,0,.35)' }} />
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}

// A friendly label for the source being scanned. Accurate per source rather than calling
// everything that isn't SharePoint "Google Drive": 'local' → sample corpus, 'sharepoint' →
// SharePoint / OneDrive, 'drive' → Google Drive. 'all' has no single source, so it is derived
// from whichever provider is connected (opts.hasDrive / opts.hasSP), falling back to the neutral
// "connected source" when nothing is known.
export function scanSourceLabel(source, opts = {}) {
  switch (source) {
    case 'local': return 'sample corpus'
    case 'sharepoint': return 'SharePoint / OneDrive'
    case 'drive': return 'Google Drive'
    case 'all':
    default:
      if (opts.hasDrive) return 'Google Drive'
      if (opts.hasSP) return 'SharePoint / OneDrive'
      return 'connected source'
  }
}

export default function ScanReviewModal({
  source = 'all', folder = null, startInFolderMode = false, startInAllMode = false,
  deepScan, setDeepScan, queuedScan, setQueuedScan,
  excludeRemediated, setExcludeRemediated, incremental, setIncremental,
  estCount = null, estWhere = null,
  hasDrive = false, hasSP = false,
  canEditScope = true, rememberDefault = false,
  scans = [],
  onConfirm, onCancel,
}) {
  const label = scanSourceLabel(source, { hasDrive, hasSP })
  const hasBehavior = setDeepScan || setQueuedScan || setExcludeRemediated || setIncremental
  // estCount describes an earlier run, not the wizard's mutable folder selection.
  // Keep accepting the legacy props, but never present them as this run's estimate.

  return (
    <div role="dialog" aria-modal="true" aria-label="New discovery"
         onClick={() => onCancel?.()}
         style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.45)',
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '5vh 16px' }}>
      {/* ~1.5× wider than the old Sources-tab modal (min(620px) → min(940px)); max-height and
          padding bumped proportionally so the wider body still fits ~90vh with vertical scroll. */}
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: 'var(--surface, #fff)', color: 'inherit', borderRadius: 12,
                    width: 'min(940px, 100%)', maxHeight: '90vh', overflowY: 'auto',
                    boxShadow: '0 12px 40px rgba(0,0,0,.3)', padding: '20px 26px' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 2 }}>
          {/* Still "scan", not "assessment". This action LISTS the estate and opens no file —
              `_defer_analysis_to_assess()` defaults to on (ADR 0020), so the WCAG analysis runs
              later, at Assess. Naming it an assessment would assert one that has not happened. */}
          <h3 style={{ margin: 0, fontSize: 16 }}>New discovery</h3>
          <button className="ghost small" aria-label="Close" onClick={() => onCancel?.()}
                  style={{ marginLeft: 'auto' }}>×</button>
        </div>
        {/* One line of orientation in place of a titled section. "Sources included" was a heading,
            a rule and a status dot spent on a single fact, above the decision the user came for;
            the fact survives, the chrome does not. */}
        <p className="muted" style={{ fontSize: 12.5, margin: '0 0 12px',
                                      display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="pulsedot" aria-hidden="true" />
          {label}{folder ? ' · selected folder' : ''}
          <span aria-hidden="true">·</span>
          Choose where and what ACP should evaluate.
        </p>

        {/* 2. Scan behaviour is NOT here any more, and that is the point.
            PII scan, Durable scan, Skip Remediated/ and Incremental scan were four engine switches
            in front of every user, before they could start a basic scan. They are platform
            behaviour, not decisions a compliance officer should be asked to make per run:
            wrong combinations are slow, expensive or silently narrowing, and none of them is
            answerable without knowing how the scanner works.
            They are NOT relocated to an "Advanced" reveal — an advanced section is still surface,
            and the ones that matter (Skip Remediated/) are exactly the ones nobody should be
            toggling casually. They keep their defaults in App state (see the comment on
            `incremental` there) and remain settable by an operator through configuration.
            The props are still accepted so App does not need changing in the same step and any
            other caller keeps working; they are simply not rendered. */}

        {/* 3. Formats & WCAG criteria + estimate + the wizard's confirm/cancel footer */}
        <div className="scanmodal-sec">
          {/* No heading. This titled the entire body "Formats & WCAG criteria" while the user was
              on step 1, DRIVE LOCATIONS — naming a later step's subject as the current one. The
              wizard's own stepper says which step this is, and says it correctly. */}
          <div className="scanmodal-est muted">
            Document count is determined when the scan starts.
            <span style={{ display: 'block', fontSize: 11 }}>
              Discovery counts files within the scope selected below, including subfolders unless excluded.
            </span>
          </div>
          {/* source/hasDrive/hasSP so the wizard can seed its folder step from the SAME source the
              scan will resolve to; the run scope comes back out through onConfirm. */}
          {/* `scans` is the user's own run history — the wizard derives its "reuse a recent scope"
              shortcuts from the boundary each run FROZE, so every offer is a record rather than a
              claim. Threaded rather than fetched here: App already holds the list. */}
          <ScanScopeWizard showStartButton canEditScope={canEditScope} rememberDefault={rememberDefault}
            source={source} hasDrive={hasDrive} hasSP={hasSP} scans={scans}
            startInFolderMode={startInFolderMode}
            startInAllMode={startInAllMode}
            onStartScan={(o) => { if (o?.cancel) onCancel?.(); else onConfirm?.(o) }} />
        </div>
      </div>
    </div>
  )
}
