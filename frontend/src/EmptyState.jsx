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

export function Loading() {
  return <div className="loadingbox"><span className="spinner" />Loading your workspace…</div>
}
