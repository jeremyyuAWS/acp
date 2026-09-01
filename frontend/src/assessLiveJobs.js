const ASSESS_FILE_TYPES = new Set(['scan_file', 'scan_batch'])

const payloadOf = (raw) => {
  if (raw && typeof raw === 'object') return raw
  try { return JSON.parse(raw || '{}') } catch { return {} }
}

export const assessmentStageLabel = (phase) => {
  const p = String(phase || '').toLowerCase()
  if (p.includes('ocr')) return 'Reading text and images'
  if (p.includes('office')) return 'Opening document structure'
  if (p.includes('pdf')) return 'Opening PDF structure'
  if (p.includes('text')) return 'Checking text'
  if (p.includes('structure')) return 'Checking document structure'
  if (p.includes('trace')) return 'Saving assessment evidence'
  return 'Assessing now'
}

/** Active file jobs for one scan, from the durable queue shared by every worker replica. */
export function activeAssessmentFiles(jobs, scanId) {
  const active = new Map()
  for (const job of Array.isArray(jobs) ? jobs : []) {
    if (job?.scan_id !== scanId || job.status !== 'running' || !ASSESS_FILE_TYPES.has(job.type)) continue
    const payload = payloadOf(job.payload)
    const files = payload.file ? [payload.file]
      : Array.isArray(payload.items) ? payload.items.map((item) => item?.file).filter(Boolean) : []
    for (const file of files) active.set(file, assessmentStageLabel(job.phase))
  }
  return active
}
