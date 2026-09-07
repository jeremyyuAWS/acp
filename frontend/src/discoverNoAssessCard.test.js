import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('the live-assess detail belongs to the canonical current stage', () => {
  it('mounts once inside the persistent workflow stack', () => {
    const stack = app.indexOf('<WorkflowStageStack')
    const card = app.indexOf('<LiveAssessmentLive')
    const main = app.indexOf('<main id="main-content"')
    expect(stack).toBeGreaterThan(-1)
    expect(card).toBeGreaterThan(stack)
    expect(main).toBeGreaterThan(card)
    expect(app.match(/<LiveAssessmentLive/g)).toHaveLength(1)
  })

  it('is owned only by the canonical Assess execution, independent of the selected tab', () => {
    expect(app).toMatch(/assess: canonicalStage\?\.stage === 'assess' \? \(/)
    expect(app).not.toMatch(/assess:.*\bview\b/)
    expect(app).toMatch(/scanId=\{canonicalScanId\}/)
  })

  it('does not let a Discover workflow activate the Assess detail', () => {
    expect(app).not.toMatch(/assess:.*primaryWorkflow\?\.stage === 'discover'/)
  })

  it('does not stack the generic continuity banner above active Assess', () => {
    expect(app).toMatch(/workflow=\{primaryWorkflow\?\.stage === 'assess'[\s\S]*?\? null : primaryWorkflow\}/)
  })
})
