const number = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)

export function attemptStage(phase = '') {
  const text = String(phase).toLowerCase()
  if (/verif|re-?check|validat/.test(text)) return 'rechecking'
  if (/sav|stor|deliver|publish|sharepoint/.test(text)) return 'saving'
  if (/final|evidence/.test(text)) return 'finalizing'
  if (/prepar|open|load|download/.test(text)) return 'preparing'
  return 'applying'
}

export function milestoneCrossings(previous, next) {
  if (!previous || !next || previous.run_id !== next.run_id) return []
  const beforeCompleted = number(previous.documents?.completed)
  const completed = number(next.documents?.completed)
  const beforeDelivered = number(previous.delivery?.delivered)
  const delivered = number(next.delivery?.delivered)
  const total = number(next.total_documents)
  const notices = []
  if (beforeDelivered !== null && delivered !== null && beforeDelivered < 1 && delivered >= 1) {
    notices.push({ key: 'first-delivery', text: 'First corrected copy delivered' })
  }
  if (beforeCompleted !== null && completed !== null) {
    const reached = (Math.floor(beforeCompleted / 50) + 1) * 50
    if (reached <= completed) notices.push({ key: `completed-${reached}`, text: `${reached.toLocaleString()} documents completed` })
    if (total && beforeCompleted < total / 2 && completed >= total / 2) notices.push({ key: 'halfway', text: 'Halfway through this batch' })
  }
  return notices
}

export function activityBuckets(events = [], endAt, bucketCount = 12) {
  const end = Date.parse(endAt || '')
  if (!Number.isFinite(end)) return []
  const bucketMs = 5_000
  const values = Array.from({ length: bucketCount }, () => 0)
  for (const event of events) {
    const at = Date.parse(event?.occurredAt || '')
    if (!Number.isFinite(at) || at > end || at <= end - bucketCount * bucketMs) continue
    const index = Math.min(bucketCount - 1, Math.floor((at - (end - bucketCount * bucketMs)) / bucketMs))
    values[index] += 1
  }
  return values
}

export function retrySeconds(retryAt, now = Date.now()) {
  const at = Date.parse(retryAt || '')
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at - now) / 1000)) : null
}
