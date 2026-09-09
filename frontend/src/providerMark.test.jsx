import { createElement } from 'react'
import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ProviderMark, { providerKey, providerLogo, providerMonogram } from './ProviderMark.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

// Deliberately no vendor names in this file: aiModel.test.js sweeps every source for
// them, because the UI once shipped model names for models that never ran. Provider
// identities arrive from the server at runtime; nothing here needs to hardcode one.
it('maps a provider name to the asset filename convention', () => {
  expect(providerKey('MixedCase')).toBe('mixedcase')
  expect(providerKey('lowercase')).toBe('lowercase')
  expect(providerKey('  Some Provider ')).toBe('some-provider')
  expect(providerKey('dots.and_underscores')).toBe('dots-and-underscores')
  expect(providerKey('')).toBe('')
})

it('finds an official asset that exists and returns null for one that does not', () => {
  // sharepoint-logo.svg, openai-logo.svg and ollama-logo.svg are vendored; nothing else is,
  // until someone adds it -- this is the "drop a file, no code change" convention working.
  expect(providerLogo('sharepoint')).toBeTruthy()
  expect(providerLogo('openai')).toBeTruthy()
  expect(providerLogo('ollama')).toBeTruthy()
  expect(providerLogo('definitely-not-a-vendored-provider')).toBeNull()
  expect(providerLogo('')).toBeNull()
})

it('never invents a brand mark: an unknown provider gets a monogram, not a lookalike', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(ProviderMark, { provider: 'Acme Cloud' })))
  const mark = container.querySelector('.provider-mark')
  expect(mark.tagName).toBe('SPAN')
  expect(mark.classList.contains('provider-mark--monogram')).toBe(true)
  expect(mark.textContent).toBe('AC')
  // Decorative only -- the provider NAME is real text rendered by the caller.
  expect(mark.getAttribute('aria-hidden')).toBe('true')
})

it('renders the image once an official asset is vendored', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(ProviderMark, { provider: 'sharepoint' })))
  const mark = container.querySelector('.provider-mark')
  expect(mark.tagName).toBe('IMG')
  expect(mark.getAttribute('alt')).toBe('')
  expect(mark.getAttribute('aria-hidden')).toBe('true')
})

// RemediationPlanChoices renders one of these per generation-chain step, keyed off
// `step.provider` as reported by the server (e.g. "openai", "ollama") -- so vendoring
// these two assets is the whole fix; this locks that wiring in as a regression test.
it('renders the vendored logo for each AI provider RemediationPlanChoices can report', async () => {
  for (const provider of ['openai', 'ollama']) {
    const { root, container } = createTestRoot()
    await act(async () => root.render(createElement(ProviderMark, { provider })))
    const mark = container.querySelector('.provider-mark')
    expect(mark.tagName).toBe('IMG')
    expect(mark.getAttribute('src')).toBe(providerLogo(provider))
  }
})

it('builds a readable monogram from multi-word and empty names', () => {
  expect(providerMonogram('Some Provider')).toBe('SP')
  expect(providerMonogram('single')).toBe('S')
  expect(providerMonogram('')).toBe('?')
})
