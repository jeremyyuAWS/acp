import { createElement, act } from 'react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', async (importActual) => ({
  ...await importActual(), getAiProviders: vi.fn(), getSecondOpinionPolicy: vi.fn(),
  getRemediationPilot: vi.fn(), putAiProvider: vi.fn(), testAiProvider: vi.fn(), putAiProviderSecret: vi.fn(),
}))
import { getAiProviders, getSecondOpinionPolicy, getRemediationPilot, putAiProvider, testAiProvider, putAiProviderSecret } from './api.js'
import { AIProvidersPanel } from './Settings.jsx'
const row = (provider) => ({ provider, enabled: false, endpoint: '', deployment: '', model: '', key_secret_ref: '', key_present: false })
const button = (c, text) => [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === text)
const field = (c, text) => [...c.querySelectorAll('label')].find((l) => l.textContent.startsWith(text))?.querySelector('input')
const change = async (input, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
})
const mount = async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(AIProvidersPanel)))
  return container
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  getAiProviders.mockResolvedValue({ providers: [row('anthropic')], secret_write: { available: false } })
  getSecondOpinionPolicy.mockResolvedValue({ enabled: false, criteria: [], purpose_enabled: false })
  getRemediationPilot.mockResolvedValue({ enabled: false, criteria: [] })
  testAiProvider.mockResolvedValue({ ok: true, model: 'saved-model', zone: 'cloud', latency_ms: 20 })
  putAiProvider.mockImplementation(async (patch) => ({ providers: [{ ...row('anthropic'), ...patch }] }))
})
afterEach(unmountAll)

it('uses Anthropic examples and explains that a reference must exist in the running app', async () => {
  const c = await mount()
  expect(field(c, 'Endpoint').placeholder).toBe('https://api.anthropic.com/v1')
  expect(field(c, 'Model').placeholder).toBe('claude-sonnet-5')
  expect(field(c, 'Secret reference').placeholder).toBe('ANTHROPIC_API_KEY')
  expect(field(c, 'Deployment')).toBeUndefined()
  expect(c.textContent).toContain('running ACP app')
  expect(c.textContent).toContain('GitHub')
  expect(c.querySelector('input[type=password]')).toBeNull()
})

it('blocks a test of unsaved values, saves the reference, then tests saved config', async () => {
  const c = await mount()
  await change(field(c, 'Model'), 'claude-sonnet-5')
  await change(field(c, 'Secret reference'), 'ANTHROPIC_API_KEY')
  expect(button(c, 'Test connection').disabled).toBe(true)
  expect(c.textContent).toContain('Save changes before testing')
  await act(async () => button(c, 'Test connection').click())
  expect(testAiProvider).not.toHaveBeenCalled()
  await act(async () => button(c, 'Save').click())
  expect(putAiProvider).toHaveBeenCalledWith(expect.objectContaining({ provider: 'anthropic', model: 'claude-sonnet-5', key_secret_ref: 'ANTHROPIC_API_KEY' }))
  expect(button(c, 'Test connection').disabled).toBe(false)
  await act(async () => button(c, 'Test connection').click())
  expect(testAiProvider).toHaveBeenCalledWith('anthropic')
  expect(c.textContent).toContain('reached saved-model')
  await change(field(c, 'Model'), 'another-model')
  expect(c.textContent).not.toContain('reached saved-model')
})

it('keeps testing blocked when saving fails', async () => {
  putAiProvider.mockRejectedValue(new Error('save rejected'))
  const c = await mount()
  await change(field(c, 'Model'), 'claude-sonnet-5')
  await act(async () => button(c, 'Save').click())
  expect(c.textContent).toContain('save rejected')
  expect(button(c, 'Test connection').disabled).toBe(true)
  expect(field(c, 'Model').value).toBe('claude-sonnet-5')
})

it('rejects a raw key pasted into the non-secret reference field', async () => {
  const c = await mount()
  await change(field(c, 'Secret reference'), 'sk-ant-fixture-not-a-real-key')
  expect(button(c, 'Save').disabled).toBe(true)
  expect(c.textContent).toContain('Enter a secret name, not an API key')
  expect(putAiProvider).not.toHaveBeenCalled()
})


it.each([
  ['azure_openai', 'https://your.openai.azure.com', 'AZURE_OPENAI_API_KEY', true],
  ['openai', 'https://api.openai.com/v1', 'OPENAI_API_KEY', false],
  ['gemini', 'https://generativelanguage.googleapis.com/v1beta/openai', 'GEMINI_API_KEY', false],
  ['huggingface', 'https://your-endpoint.endpoints.huggingface.cloud', 'HF_API_TOKEN', false],
  ['bedrock', undefined, 'AWS_SECRET_ACCESS_KEY', false],
])('shows %s adapter fields without saving example values', async (provider, endpoint, secret, deployment) => {
  getAiProviders.mockResolvedValue({ providers: [row(provider)] })
  const c = await mount()
  expect(field(c, 'Endpoint')?.placeholder).toBe(endpoint)
  expect(field(c, 'Secret reference').placeholder).toBe(secret)
  expect(!!field(c, 'Deployment')).toBe(deployment)
  expect(field(c, 'Model').value).toBe('')
  expect(button(c, 'Save').disabled).toBe(true)
  expect(putAiProvider).not.toHaveBeenCalled()
})

it('blocks testing during save and restores testing when an edit is reverted', async () => {
  let finish
  putAiProvider.mockImplementation((patch) => new Promise((resolve) => { finish = () => resolve({ providers: [patch] }) }))
  const c = await mount()
  await change(field(c, 'Model'), 'claude-sonnet-5')
  await act(async () => button(c, 'Save').click())
  expect(button(c, 'Test connection').disabled).toBe(true)
  expect(field(c, 'Model').disabled).toBe(true)
  await act(async () => finish())
  expect(button(c, 'Test connection').disabled).toBe(false)
  await change(field(c, 'Model'), 'changed')
  expect(button(c, 'Test connection').disabled).toBe(true)
  await change(field(c, 'Model'), 'claude-sonnet-5')
  expect(button(c, 'Test connection').disabled).toBe(false)
})


it('stores a pasted key only through the vault control and replaces a draft reference', async () => {
  getAiProviders.mockResolvedValue({ providers: [row('anthropic')], secret_write: { available: true, kind: 'azure_key_vault' } })
  putAiProviderSecret.mockResolvedValue({ providers: [{ ...row('anthropic'), key_secret_ref: 'keyvault:acp-ai-anthropic-key', key_present: true }] })
  const c = await mount()
  await change(field(c, 'Secret reference'), 'OLD_REFERENCE')
  await change(field(c, 'Model'), 'claude-sonnet-5')
  await change(c.querySelector('input[type=password]'), 'fixture-key-value')
  expect(button(c, 'Test connection').disabled).toBe(true)
  await act(async () => button(c, 'Store key in the vault').click())
  expect(putAiProviderSecret).toHaveBeenCalledWith('anthropic', 'fixture-key-value')
  expect(field(c, 'Secret reference').value).toBe('keyvault:acp-ai-anthropic-key')
  expect(c.querySelector('input[type=password]').value).toBe('')
  await act(async () => button(c, 'Save').click())
  expect(putAiProvider).toHaveBeenCalledWith(expect.objectContaining({ key_secret_ref: 'keyvault:acp-ai-anthropic-key' }))
  expect(JSON.stringify(putAiProvider.mock.calls)).not.toContain('fixture-key-value')
})
