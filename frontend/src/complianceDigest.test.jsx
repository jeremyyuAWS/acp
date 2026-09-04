// ComplianceDigest — no test file existed.
//
// THE GAP. ComplianceDigest is embedded in Monitor and provides the estate-level compliance
// health summary panel. It is purely presentational (getDigest → state → render) but had
// zero coverage. Any breaking change to Monitor's compliance summary would go undetected.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getDigest = vi.fn()
vi.mock('./api.js', () => ({
  getDigest: (...a) => getDigest(...a),
}))

const { default: ComplianceDigest } = await import('./ComplianceDigest.jsx')

afterEach(async () => { await unmountAll(); getDigest.mockReset() })

const settle = async (n = 4) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(ComplianceDigest, props)) })
  return container
}

describe('ComplianceDigest', () => {
  it('renders nothing when run is not provided', async () => {
    const c = await mount({})
    expect(c.innerHTML).toBe('')
    expect(getDigest).not.toHaveBeenCalled()
  })

  it('shows a loading indicator while the digest is being fetched', async () => {
    getDigest.mockReturnValue(new Promise(() => {})) // never resolves
    const c = await mount({ run: { id: 'r1' } })
    await settle()

    expect(c.textContent).toMatch(/Analys/)
    expect(getDigest).toHaveBeenCalledWith('r1', false)
  })

  it('renders the narrative after a successful fetch', async () => {
    getDigest.mockResolvedValue({
      narrative: 'Compliance is strong across 94% of documents.',
      changed: [],
      ai: false,
    })
    const c = await mount({ run: { id: 'r1' } })
    await settle()

    expect(c.textContent).toMatch(/Compliance is strong/)
    expect(c.textContent).toMatch(/Deterministic summary/)
    expect(c.textContent).toMatch(/nothing invented/)
  })

  it('renders changed bullets and model attribution for an AI-written digest', async () => {
    getDigest.mockResolvedValue({
      narrative: 'Three criteria improved this week.',
      changed: ['1.4.3 contrast up from 89% to 96%', '1.1.1 alt-text now 100%'],
      ai: true,
      model: 'claude-haiku-4-5',
    })
    const c = await mount({ run: { id: 'r1' } })
    await settle()

    expect(c.textContent).toMatch(/Three criteria improved/)
    expect(c.textContent).toMatch(/1\.4\.3 contrast/)
    expect(c.textContent).toMatch(/1\.1\.1 alt-text/)
    expect(c.textContent).toMatch(/claude-haiku-4-5/)
    expect(c.textContent).not.toMatch(/Deterministic summary/)
  })

  it('renders nothing extra when the API call fails (silent catch)', async () => {
    getDigest.mockRejectedValue(new Error('network error'))
    const c = await mount({ run: { id: 'r1' } })
    await settle()

    // Section header still renders (run is set), but no narrative paragraph or changed list.
    expect(c.querySelector('section')).toBeTruthy()
    expect(c.textContent).not.toMatch(/Analys/)
    expect(c.querySelector('.digestnarr')).toBeNull()
    expect(c.querySelector('.digestchanged')).toBeNull()
  })

  it('Regenerate button calls getDigest with refresh=true', async () => {
    getDigest.mockResolvedValue({ narrative: 'Estate is healthy.', changed: [], ai: false })
    const c = await mount({ run: { id: 'r1' } })
    await settle()

    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Regenerate'))
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    await settle()

    expect(getDigest).toHaveBeenCalledWith('r1', true)
  })

  it('refetches when run.id changes', async () => {
    getDigest
      .mockResolvedValueOnce({ narrative: 'First run result.', changed: [], ai: false })
      .mockResolvedValue({ narrative: 'Second run result.', changed: [], ai: false })

    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(ComplianceDigest, { run: { id: 'r1' } })) })
    await settle()
    expect(container.textContent).toMatch(/First run result/)

    await act(async () => { root.render(createElement(ComplianceDigest, { run: { id: 'r2' } })) })
    await settle()
    expect(container.textContent).toMatch(/Second run result/)
    expect(getDigest).toHaveBeenCalledTimes(2)
  })
})
