import { describe, expect, it, vi } from 'vitest'
import {
  parseStageExecutionConflict,
  startStageWithConflictDecision,
  STAGE_CONFLICT_DECISION,
} from './stageExecutionConflict.js'

const activeError = (detail = {}) => Object.assign(new Error('conflict'), {
  status: 409,
  detail: { code: 'stage_execution_active', current_execution_id: 'exec-remediate',
    allowed_next_actions: ['cancel', 'supersede'], ...detail },
})

describe('stage execution conflict decisions', () => {
  it('parses the nested FastAPI conflict contract without reading prose', () => {
    expect(parseStageExecutionConflict(activeError({ revision: 8, stage: 'remediate' }))).toEqual({
      code: 'stage_execution_active', currentExecutionId: 'exec-remediate', revision: 8,
      currentStage: 'remediate', allowedNextActions: ['cancel', 'supersede'],
    })
    expect(parseStageExecutionConflict(Object.assign(new Error(), { status: 500 }))).toBeNull()
  })

  it('continues the authoritative active execution and does not submit again', async () => {
    const submit = vi.fn().mockRejectedValue(activeError({ revision: 3, stage: 'remediate' }))
    const loadExecution = vi.fn().mockResolvedValue({ execution_id: 'exec-remediate', revision: 3 })
    const replaceWorkflow = vi.fn()
    const result = await startStageWithConflictDecision({ submit, loadExecution, replaceWorkflow,
      choose: vi.fn().mockResolvedValue(STAGE_CONFLICT_DECISION.CONTINUE) })

    expect(result.outcome).toBe('continued')
    expect(loadExecution).toHaveBeenCalledWith('exec-remediate')
    expect(submit).toHaveBeenCalledTimes(1)
    expect(replaceWorkflow).not.toHaveBeenCalled()
  })

  it('hydrates the missing revision then delegates replacement to one server mutation', async () => {
    const replaceWorkflow = vi.fn().mockResolvedValue({ workflow_revision: 9, execution_id: 'exec-discover' })
    const result = await startStageWithConflictDecision({
      submit: vi.fn().mockRejectedValue(activeError()),
      loadExecution: vi.fn().mockResolvedValue({ revision: 14, stage: 'release' }),
      choose: vi.fn().mockResolvedValue(STAGE_CONFLICT_DECISION.RESTART),
      replaceWorkflow,
    })

    expect(replaceWorkflow).toHaveBeenCalledTimes(1)
    expect(replaceWorkflow).toHaveBeenCalledWith({ currentExecutionId: 'exec-remediate', expectedRevision: 14 })
    expect(result.outcome).toBe('restarted')
  })

  it('cancels without any mutation', async () => {
    const replaceWorkflow = vi.fn()
    const result = await startStageWithConflictDecision({
      submit: vi.fn().mockRejectedValue(activeError({ revision: 2 })),
      loadExecution: vi.fn(), replaceWorkflow,
      choose: vi.fn().mockResolvedValue(STAGE_CONFLICT_DECISION.CANCEL),
    })
    expect(result.outcome).toBe('cancelled')
    expect(replaceWorkflow).not.toHaveBeenCalled()
  })
})
