export const STAGE_CONFLICT_DECISION = Object.freeze({
  CONTINUE: 'continue-active',
  RESTART: 'restart-workflow',
  CANCEL: 'cancel',
})

const positiveRevision = (value) => {
  const revision = Number(value)
  return Number.isInteger(revision) && revision > 0 ? revision : null
}

/**
 * Read the machine contract carried by api.js errors. FastAPI puts these fields
 * under `detail`; a direct transport may provide the same object itself.
 */
export function parseStageExecutionConflict(error) {
  if (!error || Number(error.status) !== 409) return null
  const detail = error.detail && typeof error.detail === 'object' ? error.detail : error
  if (detail.code !== 'stage_execution_active') return null
  const executionId = String(detail.current_execution_id || '').trim()
  if (!executionId) return null
  return {
    code: detail.code,
    currentExecutionId: executionId,
    revision: positiveRevision(detail.revision),
    currentStage: detail.current_stage || detail.stage || null,
    allowedNextActions: Array.isArray(detail.allowed_next_actions)
      ? detail.allowed_next_actions.filter((action) => typeof action === 'string')
      : [],
  }
}

/**
 * Resolve a rejected upstream start without manufacturing atomicity in the
 * browser. `replaceWorkflow` must be one server mutation that both stops the
 * named execution and accepts the new workflow revision using expectedRevision.
 */
export async function startStageWithConflictDecision({
  submit,
  choose,
  loadExecution,
  replaceWorkflow,
}) {
  try {
    return { outcome: 'started', response: await submit() }
  } catch (error) {
    const conflict = parseStageExecutionConflict(error)
    if (!conflict) throw error

    let execution = null
    if (conflict.revision == null || conflict.currentStage == null) {
      execution = await loadExecution(conflict.currentExecutionId)
      conflict.revision = positiveRevision(execution?.revision)
      conflict.currentStage = conflict.currentStage || execution?.stage || null
    }

    const decision = await choose({ ...conflict })
    if (!decision || decision === STAGE_CONFLICT_DECISION.CANCEL) {
      return { outcome: 'cancelled', conflict }
    }
    if (decision === STAGE_CONFLICT_DECISION.CONTINUE) {
      execution = execution || await loadExecution(conflict.currentExecutionId)
      return { outcome: 'continued', conflict, execution }
    }
    if (decision !== STAGE_CONFLICT_DECISION.RESTART) {
      throw new TypeError(`Unknown stage conflict decision: ${decision}`)
    }
    if (conflict.revision == null) {
      throw new Error('The server did not provide a revision for the active stage execution.')
    }
    if (typeof replaceWorkflow !== 'function') {
      throw new Error('The server does not support atomic workflow replacement yet.')
    }

    const response = await replaceWorkflow({
      currentExecutionId: conflict.currentExecutionId,
      expectedRevision: conflict.revision,
    })
    return { outcome: 'restarted', conflict, response }
  }
}
