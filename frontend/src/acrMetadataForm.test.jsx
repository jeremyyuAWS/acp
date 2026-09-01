import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * AcrMetadataForm — PRD §8's report metadata (ADR 0047, Phase 2).
 *
 * WHY THIS SCREEN IS LOAD-BEARING. Phase 1 shipped the PATCH endpoint and a read-only Overview,
 * so no report could reach a publishable state through the UI at all. §16 requires publication to
 * fail when required information is missing, and with no way to supply it that gate could never
 * open.
 *
 * The property worth pinning hardest: **which fields are required comes from the publish gate**,
 * not from a list in this component. A second hardcoded list is how a form ends up marking a
 * field optional that the server refuses — the same screen-disagrees-with-gate failure the
 * criterion detail avoids by rendering the server's own refusal sentences.
 */

const patchAcrReport = vi.fn()
vi.mock('./acrApi', () => ({ patchAcrReport: (...a) => patchAcrReport(...a) }))

const { default: AcrMetadataForm } = await import('./AcrMetadataForm.jsx')

const REPORT = {
  id: 'acr_1', report_title: 'ACP ACR', product_name: 'ACP by Movate',
  product_version: '1.4.0', vendor_name: '', evaluators: '', status: 'draft',
}

let container
const mount = async (props = {}) => {
  patchAcrReport.mockReset().mockResolvedValue({ updated: 1 })
  const created = createTestRoot()
  container = created.container
  await act(async () => {
    created.root.render(createElement(AcrMetadataForm, {
      report: REPORT, blockingFields: ['vendor_name', 'evaluators'],
      advisoryFields: ['excluded_functionality'], readOnly: false, ...props,
    }))
  })
  await act(async () => { await Promise.resolve() })
  return container
}

const field = (name) => container.querySelector(`#acr-meta-${name}`)
const labelFor = (el) => container.querySelector(`label[for="${el.id}"]`)
const text = () => container.textContent
const setValue = async (el, val) => {
  const proto = el.ownerDocument.defaultView[el.tagName === 'TEXTAREA' ? 'HTMLTextAreaElement' : 'HTMLInputElement'].prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  await act(async () => {
    setter.call(el, val)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

// Submitting the form itself rather than clicking the button: the button is inside a <form> with
// required fields, so a click only reaches the handler once constraint validation passes. Going
// through the form's submit event exercises the same handler and keeps the assertion about the
// handler rather than about jsdom's validation timing.
const submitForm = async () => {
  const form = container.querySelector('form')
  await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
  await act(async () => { await Promise.resolve() })
}

afterEach(unmountAll)

describe('required-ness comes from the publish gate', () => {
  it('marks exactly the fields validation is blocking on', async () => {
    await mount()
    expect(field('vendor_name').required).toBe(true)
    expect(field('evaluators').required).toBe(true)
    // Already filled, so not in blockingFields — must not be marked required.
    expect(field('product_version').required).toBe(false)
  })

  it('does not mark an advisory field required', async () => {
    // "No excluded functionality" is a real answer. Demanding prose for it trains people to
    // type "n/a", which is worse than an empty field.
    await mount()
    expect(field('excluded_functionality').required).toBe(false)
    expect(text()).toMatch(/Empty is a valid answer/)
    expect(text()).toMatch(/rather than typing "n\/a"/)
  })

  it('says how many required fields are still empty', async () => {
    await mount()
    expect(text()).toMatch(/2 required fields still empty/)
    expect(text()).toMatch(/cannot be published/)
  })

  it('says so when nothing is outstanding', async () => {
    await mount({ blockingFields: [], advisoryFields: [] })
    expect(text()).toMatch(/Every required field is filled in/)
  })
})

describe('editing', () => {
  it('sends only the changed fields', async () => {
    // BOTH required fields must be filled or the browser's own constraint validation blocks
    // submission before the handler runs — which is the form working, and worth knowing rather
    // than working around: an earlier version of this test filled one field and read the
    // resulting no-op as a broken handler.
    await mount()
    await setValue(field('vendor_name'), 'Movate')
    await setValue(field('evaluators'), 'alice@x.com')
    await submitForm()

    expect(patchAcrReport).toHaveBeenCalledWith(
      'acr_1', { vendor_name: 'Movate', evaluators: 'alice@x.com' })
    // …and untouched fields are not resent, so a concurrent edit elsewhere is not clobbered.
    expect(Object.keys(patchAcrReport.mock.calls[0][1])).toHaveLength(2)
  })

  it('disables save until something changes', async () => {
    await mount()
    const submit = [...container.querySelectorAll('button')].find((b) => /No changes/.test(b.textContent))
    expect(submit.disabled).toBe(true)
  })

  it('surfaces a server refusal verbatim', async () => {
    await mount()
    patchAcrReport.mockRejectedValue(new Error('this report is published'))
    await setValue(field('vendor_name'), 'Movate')
    await setValue(field('evaluators'), 'alice@x.com')
    await submitForm()
    expect(container.querySelector('[role="alert"]').textContent).toMatch(/is published/)
  })

  it('is read-only for a published report or a non-editor', async () => {
    await mount({ readOnly: true })
    expect(field('vendor_name').disabled).toBe(true)
    expect([...container.querySelectorAll('button')].some((b) => /Save/.test(b.textContent))).toBe(false)
    expect(text()).toMatch(/read-only/)
  })
})

describe('accessibility', () => {
  it('gives every control an accessible name (4.1.2, 3.3.2)', async () => {
    await mount()
    const controls = container.querySelectorAll('input, textarea')
    expect(controls.length).toBeGreaterThan(15)
    for (const el of controls) {
      expect(labelFor(el), `${el.id} has no label`).toBeTruthy()
    }
  })

  it('states required-ness in text, not by the asterisk alone (1.4.1)', async () => {
    await mount()
    const lbl = labelFor(field('vendor_name'))
    expect(lbl.querySelector('.sr-only').textContent).toMatch(/required/)
    expect(lbl.querySelector('[aria-hidden="true"]').textContent).toMatch(/\*/)
  })

  it('associates the required hint with its control (3.3.2)', async () => {
    await mount()
    const describedBy = field('vendor_name').getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(container.querySelector(`#${describedBy}`).textContent).toMatch(/Required before/)
  })

  it('groups fields in named fieldsets (1.3.1)', async () => {
    await mount()
    const legends = [...container.querySelectorAll('fieldset legend')].map((l) => l.textContent)
    expect(legends).toContain('Vendor')
    expect(legends).toContain('Method')
  })

  it('announces save status through a live region (4.1.3)', async () => {
    await mount()
    expect(container.querySelector('[role="status"]').getAttribute('aria-live')).toBe('polite')
  })

  it('has no axe-detectable violations', async () => {
    await mount()
    const axe = (await import('axe-core')).default
    const results = await axe.run(container, {
      resultTypes: ['violations'],
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      // jsdom has no layout engine, so contrast is undecidable here; checked in a real browser
      // by A11ySelfCheck.jsx. An honest statement of what this environment can decide.
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})
