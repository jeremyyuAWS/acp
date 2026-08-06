import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0026 Epic 2 — the compact evidence header. Pins: renders only from structured evidence
// (never prose), the value/threshold formatting, the method label, and the Needs-Review pill.

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: EvidenceHeader } = await import('./EvidenceHeader.jsx')

const render = async (props) => {
  const { container: c, root } = createTestRoot()
  await act(async () => { root.render(createElement(EvidenceHeader, props)) })
  return c
}

describe('EvidenceHeader (compact evidence, ADR 0026 Epic 2)', () => {
  it('renders method · metric value · required · status from structured evidence', async () => {
    const c = await render({
      evidence: { method: 'structural', metric: 'Contrast', value: 2.4, required: 3.0, unit: ':1' },
      severity: 'REVIEW',
    })
    expect(c.textContent).toContain('Structural')
    expect(c.textContent).toContain('Contrast 2.4:1')
    expect(c.textContent).toContain('Required 3:1')     // 3.0 formats as 3:1, not 3.0:1
    expect(c.textContent).toContain('Needs Review')
  })

  it('formats × and % units and omits Required when absent', async () => {
    const c = await render({ evidence: { method: 'structural', metric: 'Narrowest column', value: 4, unit: '%' } })
    expect(c.textContent).toContain('Narrowest column 4%')
    expect(c.textContent).not.toContain('Required')
    const c2 = await render({ evidence: { method: 'structural', metric: 'Line spacing', value: 1.08, required: 1.5, unit: '×' }, severity: 'REVIEW' })
    expect(c2.textContent).toContain('Line spacing 1.08×')
    expect(c2.textContent).toContain('Required 1.5×')
  })

  it('renders nothing without structured evidence — never derives from prose', async () => {
    const c = await render({ evidence: null, severity: 'REVIEW' })
    expect(c.querySelector('.evheader')).toBeNull()
  })
})
