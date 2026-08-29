// The instant to show for one entry in the Time-travel scan picker (App.jsx).
//
// `s.completed_at` is set at Assess finalize — never for an ADR 0020 Discover-only run, which
// reaches status='discovered' with completed_at staying NULL forever until (if ever) Assess
// runs. `new Date(null)` does not fail or return null — it silently formats as the Unix epoch,
// which in Pacific time renders as "Dec 31, 4:00 PM" with no year, indistinguishable from a
// real date at a glance. Found live 2026-08-29: an unassessed scan's own picker entry showed
// that exact string, because the label used to read `s.completed_at` alone.
//
// `s.discovered_at` (api/store.py's list_finished_scans) is the fix: it is set the instant
// discovery itself finished, independent of whether Assess ever runs, so it is always the more
// specific of the two whenever completed_at is absent. Returns null — never a fabricated
// instant — only when NEITHER field is set, which happens for a scan predating the
// discovered_at column itself.
export function scanOptionAt(s) {
  return (s && (s.completed_at ?? s.discovered_at)) ?? null
}
