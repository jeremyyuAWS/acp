// The screen before anything has been discovered — one prompt, and no numbers.
//
// It used to render ScanSetup: the format and criterion picker, in full, as the first thing an
// operator saw. That was a deliberate improvement on what came before it (three boxes explaining
// the tabs), and the Discover/Assess redesign makes it wrong for two separate reasons.
//
// IT ASKS BEFORE THERE IS ANYTHING TO ASK ABOUT. The criteria that matter are the ones that apply
// to documents you actually hold, and nobody knows what those are until an inventory exists. The
// PRD puts the order back: source -> discover -> then choose what to assess, against the real
// inventory, with a live eligible count beside it (AssessScope + ScopeImpact already do this).
//
// AND IT WAS A THIRD WRITER OF `scan_scope`. AssessScope's header already records two controls
// "that did not know about each other"; the wizard's copy went in #532, and this was the last one.
// One store, one writer, on the screen that has the information to fill it in.
//
// What is left is OV-02: a single "Go to Source" action and NO zero-valued cards. The empty
// dashboard is the specific thing being avoided — a grid of 0s reads as a completed run that
// found nothing, which is the same false-verdict family as #479/#483/#491/#502/#514. The three
// stage lines below are orientation, deliberately without counts.
export default function EmptyState({ onGoToSource }) {
  return (
    <div className="panel emptystate">
      <svg className="emptystate-icon" width="44" height="44" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 17z" />
        <path d="M8.5 13.5h7" />
      </svg>

      <h2 className="emptystate-h">No assessment has run yet</h2>
      <p className="muted emptystate-p">
        This report fills in once an assessment completes. Connect a source and choose the folders
        ACP should inventory to get started.
      </p>

      <div className="emptystate-cta">
        <button type="button" onClick={() => onGoToSource?.()}>Go to Source</button>
      </div>

      {/* Orientation, not a scoreboard: what the three stages DO, with no counts attached. */}
      <div className="emptystate-steps">
        <div>
          <div className="emptystate-stepn">1 · Source</div>
          <div className="muted emptystate-stepd">Connect a drive and pick the folders in scope.</div>
        </div>
        <div>
          <div className="emptystate-stepn">2 · Discover</div>
          <div className="muted emptystate-stepd">Inventory every file from metadata. Nothing is opened.</div>
        </div>
        <div>
          <div className="emptystate-stepn">3 · Assess</div>
          <div className="muted emptystate-stepd">Choose document types and WCAG criteria, then run.</div>
        </div>
      </div>

      <p className="muted emptystate-foot">
        Discovery results appear on the Discover tab — they never populate this report.
      </p>
    </div>
  )
}

// What each stage of App.jsx's initial-load effect is doing right now, in plain language — a
// static "Loading your workspace…" the whole way through gave no signal that anything was
// actually happening, reported live 2026-08-29 as an unexplained hang. `null` (the default,
// and every value once the load finishes) falls back to the original generic line, so a caller
// that doesn't track stages — or hasn't started the chain yet — still gets a real message.
const STAGE_TEXT = {
  bootstrap: 'Loading your workspace…',
  scan: 'Loading your latest scan…',
}

// A one-line preview of the previous load's headline numbers, shown under the spinner once
// GET /workspace/bootstrap's cached Overview snapshot has arrived but the full scan payload
// (files, findings) hasn't yet — the "meaningful Overview shell" the workspace-bootstrap
// redesign asks for, scoped to the one place safe to add without changing what gates `loaded`
// for every other tab. `overview` is the bootstrap response's `overview` field (or null before
// it arrives, or for a workspace with no scan yet) — see api.js getWorkspaceBootstrap.
export function overviewPreviewLine(overview) {
  const discovered = overview?.estate?.discovered
  if (!discovered) return null
  const certifiable = overview?.documents?.certifiable
  const pct = Number.isFinite(certifiable) ? Math.round((100 * certifiable) / discovered) : null
  return pct == null ? `${discovered} documents` : `${discovered} documents · ${pct}% certifiable`
}

export function Loading({ stage = null, preview = null } = {}) {
  const line = overviewPreviewLine(preview)
  return (
    <div className="loadingbox">
      <span className="spinner" />
      <span className="loadingbox-text">
        {STAGE_TEXT[stage] || 'Loading your workspace…'}
        {line && <div className="loadingbox-preview">{line}</div>}
      </span>
    </div>
  )
}
