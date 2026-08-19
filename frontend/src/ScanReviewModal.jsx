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
  source = 'all', folder = null,
  deepScan, setDeepScan, queuedScan, setQueuedScan,
  excludeRemediated, setExcludeRemediated, incremental, setIncremental,
  estCount = null, estWhere = null,
  hasDrive = false, hasSP = false,
  canEditScope = true, rememberDefault = true,
  onConfirm, onCancel,
}) {
  const label = scanSourceLabel(source, { hasDrive, hasSP })
  const where = estWhere || label
  const hasBehavior = setDeepScan || setQueuedScan || setExcludeRemediated || setIncremental
  // Only a real, positive count is worth showing. 0 / null / unknown would render "~0 documents",
  // which reads as "nothing to scan" — so we say when the count is actually determined instead.
  const hasEstimate = typeof estCount === 'number' && estCount > 0

  return (
    <div role="dialog" aria-modal="true" aria-label="New scan"
         onClick={() => onCancel?.()}
         style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.45)',
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '5vh 16px' }}>
      {/* ~1.5× wider than the old Sources-tab modal (min(620px) → min(940px)); max-height and
          padding bumped proportionally so the wider body still fits ~90vh with vertical scroll. */}
      <div onClick={(e) => e.stopPropagation()}
           style={{ background: 'var(--surface, #fff)', color: 'inherit', borderRadius: 12,
                    width: 'min(940px, 100%)', maxHeight: '90vh', overflowY: 'auto',
                    boxShadow: '0 12px 40px rgba(0,0,0,.3)', padding: '20px 26px' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>New scan</h3>
          <button className="ghost small" aria-label="Close" onClick={() => onCancel?.()}
                  style={{ marginLeft: 'auto' }}>×</button>
        </div>

        {/* 1. Sources included — informational */}
        <div className="scanmodal-sec">
          <div className="scanmodal-head">Sources included</div>
          <div style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="pulsedot" aria-hidden="true" />
            {label}{folder ? ' · selected folder' : ''}
          </div>
        </div>

        {/* 2. Scan behavior — only when the toggle setters are wired (the app-level gate) */}
        {hasBehavior && (
          <div className="scanmodal-sec">
            <div className="scanmodal-head">Scan behavior</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {setDeepScan && (
                <ScanSwitch on={deepScan} onToggle={() => setDeepScan((v) => !v)} label="PII scan"
                  title={deepScan
                    ? 'PII scan also looks for sensitive data (SSNs, credit cards, emails) in your documents — a bit slower on large PDF sets. Turn off for a fast, accessibility-only scan.'
                    : 'Off — Fast scan (accessibility only). Turn on to also detect sensitive data (PII).'} />
              )}
              {setQueuedScan && (
                <ScanSwitch on={queuedScan} onToggle={() => setQueuedScan((v) => !v)} label="Durable scan"
                  title={queuedScan
                    ? 'Durable scan — runs in the background queue: keeps going if you close the tab AND survives server restarts, with parallel downloads for large libraries (recommended). Turn off for a quick one-off scan in this browser session.'
                    : 'Off — Quick scan in this browser session: starts instantly, streams live per-file progress, best for spot-checking a few files. Turn on for a durable background scan that survives restarts and handles very large libraries.'} />
              )}
              {setExcludeRemediated && (
                <ScanSwitch on={excludeRemediated} onToggle={() => setExcludeRemediated((v) => !v)} label="Skip Remediated/"
                  title={excludeRemediated
                    ? 'On — skips the Remediated/ folder ACP writes fixed copies to, so they don’t get re-discovered and flagged as new documents needing attention. Turn off to also audit that folder.'
                    : 'Off — the Remediated/ folder (ACP’s own output) is scanned like any other folder. Turn on to skip it and avoid a re-discovery feedback loop.'} />
              )}
              {setIncremental && (
                <ScanSwitch on={incremental} onToggle={() => setIncremental((v) => !v)} label="Incremental scan"
                  title={incremental
                    ? 'On — a file byte-identical to one already scored under the current rubric is copied forward instead of re-analysed (ADR 0011). Turn off to force a fresh re-analysis of every file (e.g. after a manual rubric edit, or if you don’t trust the cache).'
                    : 'Off — Fresh scan: every file is re-downloaded and re-analysed, even ones that haven’t changed. Turn on for the normal, much faster incremental behavior.'} />
              )}
            </div>
          </div>
        )}

        {/* 3. Formats & WCAG criteria + estimate + the wizard's confirm/cancel footer */}
        <div className="scanmodal-sec">
          <div className="scanmodal-head">Formats &amp; WCAG criteria</div>
          <div className="scanmodal-est muted">
            {hasEstimate ? (
              <>
                ~{estCount.toLocaleString()} documents in {where}
                <span style={{ display: 'block', fontSize: 11 }}>
                  Discovered count — the actual scanned total may be lower after dedup, scope and unsupported-type filtering.
                </span>
              </>
            ) : (
              <>Document count is determined when the scan starts.</>
            )}
          </div>
          {/* source/hasDrive/hasSP so the wizard can seed its folder step from the SAME source the
              scan will resolve to; the run scope comes back out through onConfirm. */}
          <ScanScopeWizard showStartButton canEditScope={canEditScope} rememberDefault={rememberDefault}
            source={source} hasDrive={hasDrive} hasSP={hasSP}
            onStartScan={(o) => { if (o?.cancel) onCancel?.(); else onConfirm?.(o) }} />
        </div>
      </div>
    </div>
  )
}
