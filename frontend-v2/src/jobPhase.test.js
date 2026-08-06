import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { phaseLine, isStalled, STALLED_AFTER_S } from './jobPhase.js'

const here = dirname(fileURLToPath(import.meta.url))
const panel = () => readFileSync(join(here, 'QueuePanel.jsx'), 'utf8')

describe('phaseLine — the per-job live line', () => {
  it('shows what a running job reported', () => {
    expect(phaseLine({ status: 'running', phase: 'applying fixes to deck.pptx' }))
      .toBe('applying fixes to deck.pptx')
  })

  it('shows nothing when the handler reported nothing', () => {
    // An absent phase must render no line — never a placeholder standing in for work.
    expect(phaseLine({ status: 'running', phase: null })).toBeNull()
    expect(phaseLine({ status: 'running', phase: '   ' })).toBeNull()
    expect(phaseLine({ status: 'running' })).toBeNull()
  })

  it('shows nothing for a job that is not running', () => {
    expect(phaseLine({ status: 'done', phase: 're-verifying the corrected copy' })).toBeNull()
    expect(phaseLine({ status: 'queued', phase: 'x' })).toBeNull()
    expect(phaseLine(null)).toBeNull()
  })
})

describe('isStalled — a 16-minute job must announce itself', () => {
  it('flags a running job past the threshold', () => {
    expect(isStalled({ status: 'running' }, STALLED_AFTER_S + 1)).toBe(true)
    expect(isStalled({ status: 'running' }, 16 * 60)).toBe(true)   // the live case
  })

  it('does not flag a healthy or finished job', () => {
    expect(isStalled({ status: 'running' }, 30)).toBe(false)
    expect(isStalled({ status: 'done' }, 99999)).toBe(false)
    expect(isStalled({ status: 'running' }, null)).toBe(false)
    expect(isStalled(null, 99999)).toBe(false)
  })
})

describe('the fabricated cycling label is gone for good', () => {
  it('QueuePanel no longer carries a hardcoded criteria list', () => {
    const src = panel()
    expect(src).not.toMatch(/REM_STEPS/)
    expect(src).not.toMatch(/Low colour contrast \(1\.4\.3/)
    // and nothing cycles a label on a timer any more
    expect(src).not.toMatch(/setInterval\([^)]*remStep/)
  })

  it('renders the phase straight from the job record', () => {
    expect(panel()).toMatch(/phaseLine\(jb\)/)
  })
})
