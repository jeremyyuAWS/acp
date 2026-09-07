import React from 'react'
import CrossStageConflictDialog from './CrossStageConflictDialog.jsx'
import { STAGE_CONFLICT_DECISION } from './stageExecutionConflict.js'

/** Connect the reusable decision dialog to the real Discovery start callbacks. */
export function StageStartConflictDialog({ choice, onContinue, onRestart, onCancel }) {
  const decide = (decision) => {
    if (decision === STAGE_CONFLICT_DECISION.CONTINUE) onContinue()
    else if (decision === STAGE_CONFLICT_DECISION.RESTART) onRestart()
    else if (decision === STAGE_CONFLICT_DECISION.CANCEL) onCancel()
  }

  return <CrossStageConflictDialog
    conflict={choice ? {
      currentExecutionId: choice.executionId || null,
      currentScanId: choice.scanId || null,
      currentStage: choice.activeStage,
    } : null}
    requestedStage="discover"
    activeStage={choice?.activeStage}
    onDecision={decide}
  />
}
