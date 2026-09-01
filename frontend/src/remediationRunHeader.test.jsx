import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: RemediationRunHeader } = await import('./RemediationRunHeader.jsx')

let container, root
const mount = async (props = {}) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(RemediationRunHeader, props)) })
  return container
}
afterEach(unmountAll)

const summary = (c) => c.querySelector('[data-testid="rem-run-summary"]').textContent
const buttonNamed = (c, re) =>
  [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

describe('RemediationRunHeader — the summary leads with automation', () => {
  it('reads automation first, then the queues, joined with a middot', async () => {
    const c = await mount({ counts: { autoFixed: 326, needsApproval: 14, manual: 8, documents: 84 } })
    expect(summary(c)).toBe(
      '326 fixes applied automatically across 84 documents · 14 need approval · 8 require manual work')
  })

  it('omits the document clause when documents is not known', async () => {
    const c = await mount({ counts: { autoFixed: 326 } })
    expect(summary(c)).toBe('326 fixes applied automatically')
  })

  it('renders every segment in the fixed order when all are present', async () => {
    const c = await mount({ counts: { autoFixed: 5, needsApproval: 4, manual: 3,
                                      revalidating: 2, blocked: 1, documents: 2 } })
    expect(summary(c)).toBe(
      '5 fixes applied automatically across 2 documents · 4 need approval · 3 require manual work'
      + ' · 2 awaiting revalidation · 1 blocked')
  })
})

describe('RemediationRunHeader — undefined is not zero', () => {
  it('omits undefined counts entirely rather than rendering them as 0', async () => {
    const c = await mount({ counts: { autoFixed: 12, documents: 4 } })
    const text = summary(c)
    expect(text).toBe('12 fixes applied automatically across 4 documents')
    expect(text).not.toMatch(/approval/)
    expect(text).not.toMatch(/manual/)
    expect(text).not.toMatch(/revalidation/)
    expect(text).not.toMatch(/blocked/)
    expect(text).not.toMatch(/\b0\b/)
  })

  it('omits a zero needsApproval segment', async () => {
    const c = await mount({ counts: { autoFixed: 9, needsApproval: 0, manual: 2 } })
    expect(summary(c)).toBe('9 fixes applied automatically · 2 require manual work')
  })

  it('omits zero revalidating and zero blocked', async () => {
    const c = await mount({ counts: { autoFixed: 9, revalidating: 0, blocked: 0 } })
    expect(summary(c)).toBe('9 fixes applied automatically')
  })

  it('states a zero autoFixed rather than dropping it — it is an automation claim', async () => {
    const c = await mount({ counts: { autoFixed: 0, needsApproval: 14 } })
    expect(summary(c)).toBe('No fixes applied automatically yet · 14 need approval')
  })

  it('falls back to one sentence when nothing at all is renderable', async () => {
    const c = await mount({ counts: {} })
    expect(summary(c)).toBe('No remediation results yet.')
  })

  it('treats a documents-only count as not renderable — documents only modifies autoFixed', async () => {
    const c = await mount({ counts: { documents: 84 } })
    expect(summary(c)).toBe('No remediation results yet.')
  })

  it('never puts completed in the summary line (it belongs to run details)', async () => {
    const c = await mount({ counts: { autoFixed: 3, completed: 77 } })
    expect(summary(c)).toBe('3 fixes applied automatically')
    expect(summary(c)).not.toMatch(/77/)
  })
})

describe('RemediationRunHeader — singular and plural', () => {
  it('says "1 fix" for a single automatic fix', async () => {
    const c = await mount({ counts: { autoFixed: 1 } })
    expect(summary(c)).toBe('1 fix applied automatically')
  })

  it('says "1 document" for a single document', async () => {
    const c = await mount({ counts: { autoFixed: 1, documents: 1 } })
    expect(summary(c)).toBe('1 fix applied automatically across 1 document')
  })
})

describe('RemediationRunHeader — the assessment time', () => {
  it('prints the assessment time when it is known', async () => {
    const c = await mount({ assessedAt: 'Aug 31, 2:14 PM' })
    expect(c.textContent).toMatch(/Assessment: Aug 31, 2:14 PM/)
  })

  it('says nothing about the assessment time when it is null', async () => {
    const c = await mount({ assessedAt: null, counts: { autoFixed: 4 } })
    expect(c.textContent).not.toMatch(/Assessment:/)
    expect(c.textContent).not.toMatch(/unknown/i)
  })

  it('renders docScope when given', async () => {
    const c = await mount({ docScope: '84 documents in scope' })
    expect(c.textContent).toMatch(/84 documents in scope/)
  })
})

describe('RemediationRunHeader — actions', () => {
  it('fires the primary handler and marks it as the primary button', async () => {
    const onClick = vi.fn()
    const c = await mount({ primary: { label: 'Apply 326 fixes', onClick } })
    const b = buttonNamed(c, /Apply 326 fixes/)
    expect(b.className).toBe('btn primary')
    await act(async () => { b.click() })
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('fires the secondary handler and marks it as the ghost button', async () => {
    const onClick = vi.fn()
    const c = await mount({ secondary: { label: 'Export report', onClick } })
    const b = buttonNamed(c, /Export report/)
    expect(b.className).toBe('btn ghost')
    await act(async () => { b.click() })
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('honours disabled on both buttons and does not fire their handlers', async () => {
    const onPrimary = vi.fn(), onSecondary = vi.fn()
    const c = await mount({
      primary: { label: 'Apply fixes', onClick: onPrimary, disabled: true },
      secondary: { label: 'Export report', onClick: onSecondary, disabled: true },
    })
    const p = buttonNamed(c, /Apply fixes/)
    const s = buttonNamed(c, /Export report/)
    expect(p.disabled).toBe(true)
    expect(s.disabled).toBe(true)
    await act(async () => { p.click(); s.click() })
    expect(onPrimary).not.toHaveBeenCalled()
    expect(onSecondary).not.toHaveBeenCalled()
  })

  it('renders no action buttons when neither is supplied', async () => {
    const c = await mount({ counts: { autoFixed: 3 } })
    expect(c.querySelectorAll('button').length).toBe(0)
  })

  it('renders Run details only when a handler is provided', async () => {
    const without = await mount({})
    expect(buttonNamed(without, /Run details/)).toBeUndefined()

    const onOpenRunDetails = vi.fn()
    const withIt = await mount({ onOpenRunDetails })
    const b = buttonNamed(withIt, /Run details/)
    expect(b.className).toBe('linklike')
    await act(async () => { b.click() })
    expect(onOpenRunDetails).toHaveBeenCalledTimes(1)
  })
})

describe('RemediationRunHeader — read-only runs', () => {
  it('hides both action buttons and says the scan is read-only', async () => {
    const onPrimary = vi.fn(), onSecondary = vi.fn()
    const c = await mount({
      readOnly: true,
      primary: { label: 'Apply fixes', onClick: onPrimary },
      secondary: { label: 'Export report', onClick: onSecondary },
    })
    expect(buttonNamed(c, /Apply fixes/)).toBeUndefined()
    expect(buttonNamed(c, /Export report/)).toBeUndefined()
    expect(c.textContent).toMatch(/Historical scan — read-only\./)
  })

  it('still offers Run details on a read-only run', async () => {
    const c = await mount({ readOnly: true, onOpenRunDetails: vi.fn() })
    expect(buttonNamed(c, /Run details/)).toBeTruthy()
  })
})

describe('RemediationRunHeader — accessibility', () => {
  it('is a header landmark named "Remediation run" with an h2', async () => {
    const c = await mount({ counts: { autoFixed: 3 } })
    const header = c.querySelector('header')
    expect(header).toBeTruthy()
    expect(header.getAttribute('aria-label')).toBe('Remediation run')
    expect(c.querySelector('h2').textContent).toBe('Remediation')
  })

  it('gives every button an accessible name', async () => {
    const c = await mount({
      primary: { label: 'Apply fixes', onClick: () => {} },
      secondary: { label: 'Export report', onClick: () => {} },
      onOpenRunDetails: () => {},
    })
    const names = [...c.querySelectorAll('button')].map(
      (b) => b.getAttribute('aria-label') || b.textContent.trim())
    expect(names.length).toBe(3)
    for (const n of names) expect(n.length).toBeGreaterThan(0)
  })

  it('carries the state in words, not colour alone', async () => {
    // Every segment is readable text; nothing is encoded only as a style.
    const c = await mount({ counts: { autoFixed: 0, blocked: 2 } })
    expect(summary(c)).toBe('No fixes applied automatically yet · 2 blocked')
  })
})
