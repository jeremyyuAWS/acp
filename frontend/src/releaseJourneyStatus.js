// Describe confirmed delivery state; a terminal remediation run does not imply delivery.
export function releaseJourneyStatus({ error, automaticRelease, loading, publishing, deliveringCount = 0, publishedCount = 0, scopeCount = 0, readyCount = 0 }) {
  if (error || automaticRelease?.needs_attention) return { label: 'Delivery needs attention', detail: error?.summary || automaticRelease.attention_reason || 'Open Release details to see the blocking requirement.' }
  if (loading) return { label: 'Checking release requirements', detail: 'Waiting for confirmed destination and release eligibility.' }
  if (publishing || deliveringCount > 0) return { label: 'Publishing corrected copies', detail: 'Delivery receipts confirm each published copy.' }
  if (scopeCount > 0 && publishedCount === scopeCount) return { label: 'Batch published', detail: 'Open the published folder below. Remaining work is recorded in the reports.' }
  if (automaticRelease) return { label: readyCount > 0 ? 'Automatic publication queued' : 'Waiting for corrected copies', detail: 'Q3 approved automatic publication; no extra click is needed for covered copies.' }
  return { label: readyCount > 0 ? 'Ready to publish' : 'Waiting for corrected copies', detail: readyCount > 0 ? 'Publish the selected batch when ready.' : 'Copies appear after processing and release checks.' }
}
