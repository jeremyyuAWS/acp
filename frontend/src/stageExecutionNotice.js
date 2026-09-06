const label = (stage) => String(stage || 'Work').trim()

/**
 * Translate the durable stage-execution response into one truthful sentence.
 *
 * `reused` means this request queued nothing because equivalent work already exists.
 * `requeued` means failed rows were revived in that same execution.  Keep this
 * interpretation in one place so every stage tells the same story.
 */
export function stageExecutionNotice(stage, response) {
  if (!response || typeof response !== 'object') return ''
  const name = label(stage)
  const requeued = Math.max(0, Number(response.requeued) || 0)
  if (requeued > 0) {
    return `Retrying ${requeued.toLocaleString()} failed ${requeued === 1 ? 'item' : 'items'} in the existing ${name} run — no duplicate run was created.`
  }
  if (response.reused === true) {
    return `Reconnected to the existing ${name} run — equivalent work was already accepted, so nothing was queued twice.`
  }
  return ''
}
