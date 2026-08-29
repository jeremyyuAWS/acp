import { useState } from 'react'

// The "Processing details" expandable row from the stakeholder design review: a compact,
// collapsed-by-default disclosure for the job-level facts a scan owner can legitimately see —
// attempt count against its real ceiling, and a truncated job id for support/debugging —
// without cluttering the queued/live-activity cards above with detail most readers never need.
//
// Deliberately omits queue priority. The design review itself splits this: a coarse label like
// "Normal" is owner-safe, the raw numeric value is admin-only — and this frontend has no
// admin/owner distinction to enforce that split against yet. Rather than guess at a banding
// scheme or expose the raw number, this leaves priority out entirely until that distinction
// exists; adding it later needs no rework here; not the reverse.
//
// Renders nothing when there is nothing to show — no jobId at all, or a jobId with neither
// attempts nor a shortened id worth naming (attempts/max_attempts genuinely absent, e.g. SIM
// mode's getQueueJob fixture, which does not track them).
export default function QueueJobDetails({ jobId, attempts, maxAttempts }) {
  const [open, setOpen] = useState(false)
  const hasAttempts = attempts != null && maxAttempts != null
  if (!jobId && !hasAttempts) return null

  return (
    <div style={{ marginTop: 4, fontSize: 11.5 }}>
      <button type="button" className="linklike" onClick={() => setOpen((o) => !o)}
              aria-expanded={open} style={{ color: 'inherit' }}>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> Processing details
      </button>
      {open && (
        <div className="muted" style={{ marginTop: 2 }}>
          {hasAttempts && <>Attempt {attempts + 1} of {maxAttempts}</>}
          {hasAttempts && jobId && <> · </>}
          {jobId && <>Job ID …{String(jobId).slice(-6)}</>}
        </div>
      )}
    </div>
  )
}
