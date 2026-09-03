// "Folder discovery activity" — the compact card version of the folder-activity backend slice
// (#929): which folders the BFS is fetching RIGHT NOW, and the last few that finished. Purely
// presentational; `active`/`recent` are `progress.active_folders`/`progress.recent_folders`,
// already flowing through the same job-state channel `files_found`/`phase` use — no new fetch.
//
// Deliberately NOT the full tree view from the design review (checked/scanning/waiting per
// folder, "N of M folders scanned"): the backend does not track a total folder count or a
// per-folder waiting state yet, only what is actively in flight and a bounded recent-completions
// list (see api/scanner.py's _search_folder — active/recent are capped, not a durable history).
// Showing a tree implies knowledge of the whole shape of the estate that does not exist yet;
// this shows only what is real. The full tree is later, backend-dependent work.
//
// Renders nothing when both lists are empty — most scans (the flat Drive-query path has no
// folder concept at all; a scan not yet in the discovering/lifecycle phase has neither) simply
// have nothing to show, which is different from "loading" and should not look like it.
const STATE_LABEL = {
  completed: { text: 'Scanned', ink: 'var(--success-fg)', icon: '✓' },
  failed: { text: 'Failed', ink: '#8A2A20', icon: '✗' },
  rate_limited: { text: 'Rate-limited', ink: '#7A5800', icon: '⚠' },
}

export default function FolderActivity({ active, recent }) {
  const activeList = Array.isArray(active) ? active : []
  const recentList = Array.isArray(recent) ? recent : []
  if (activeList.length === 0 && recentList.length === 0) return null

  return (
    <div role="status" aria-label="Folder discovery activity" style={{ margin: '8px 0', padding: '10px 14px',
         borderRadius: 8, fontSize: 12.5, background: 'var(--surface)', border: '1px solid var(--line)' }}>
      <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.02em', fontWeight: 600 }}
           className="muted">
        Folder discovery activity
      </div>
      {activeList.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <div className="muted" style={{ fontSize: 11 }}>
            Currently exploring {activeList.length} folder{activeList.length === 1 ? '' : 's'}
          </div>
          <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none', display: 'flex',
                       flexDirection: 'column', gap: 3 }}>
            {activeList.map((f) => (
              <li key={f.path || f.name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="pulsedot" aria-hidden="true" />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={f.path}>
                  {f.path || f.name}
                </span>
                {/* Text label alongside the dot, not color/animation alone — the dot is
                    decorative (aria-hidden), this is what a screen reader announces. */}
                <span className="muted" style={{ fontSize: 10.5, flexShrink: 0 }}>scanning</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {recentList.length > 0 && (
        <div style={{ marginTop: activeList.length > 0 ? 8 : 6 }}>
          <div className="muted" style={{ fontSize: 11 }}>Recently finished</div>
          <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none', display: 'flex',
                       flexDirection: 'column', gap: 3 }}>
            {recentList.map((f) => {
              const s = STATE_LABEL[f.state] || STATE_LABEL.completed
              return (
                <li key={f.path || f.name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span aria-hidden="true" style={{ color: s.ink }}>{s.icon}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={f.path}>
                    {f.path || f.name}
                  </span>
                  <span style={{ fontSize: 10.5, flexShrink: 0, color: s.ink, fontWeight: 600 }}>
                    {s.text}
                    {f.state === 'completed' && f.files_found != null
                      ? ` · ${f.files_found} file${f.files_found === 1 ? '' : 's'}` : ''}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {/* Same distinction the design review flagged for the future full tree view: a folder
          finishing here means it was LISTED, not that its documents were assessed. Cheap to say
          now, before anyone has a reason to misread "Scanned" as "compliant". */}
      <div className="muted" style={{ marginTop: 6, fontSize: 10.5, fontStyle: 'italic' }}>
        "Scanned" means this folder was listed, not that its documents were assessed.
      </div>
    </div>
  )
}
