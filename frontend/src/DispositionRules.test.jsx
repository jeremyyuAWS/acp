import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const listDispositionPolicies = vi.fn()
const createDispositionPolicy = vi.fn()
const setDispositionPolicyEnabled = vi.fn()
const previewDispositionPolicy = vi.fn()
vi.mock('./api.js', () => ({
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
  createDispositionPolicy: (...a) => createDispositionPolicy(...a),
  setDispositionPolicyEnabled: (...a) => setDispositionPolicyEnabled(...a),
  previewDispositionPolicy: (...a) => previewDispositionPolicy(...a),
}))

const { default: DispositionRules } = await import('./DispositionRules.jsx')

afterEach(unmountAll)
let container, root
beforeEach(() => {
  listDispositionPolicies.mockReset().mockResolvedValue([])
  createDispositionPolicy.mockReset().mockResolvedValue({})
  setDispositionPolicyEnabled.mockReset().mockResolvedValue({})
  previewDispositionPolicy.mockReset().mockResolvedValue({ would_match: 0 })
  ;({ container, root } = createTestRoot())
})

const render = async () => { await act(async () => { root.render(createElement(DispositionRules)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const byLabel = (label) => container.querySelector(`[aria-label="${label}"]`)
const setValue = async (el, val) => {
  const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  await act(async () => { setter.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) })
}
const expand = async () => { await click(btnByText('Archival & deletion rules')) }
const flush = async () => { await act(async () => {}) }

describe('DispositionRules — create archival/deletion rules in Discover (Deva #3)', () => {
  it('is collapsed until expanded, then lists only archive/delete rules', async () => {
    listDispositionPolicies.mockResolvedValue([
      { policy_id: 'p1', name: 'Old finance', action: 'archive', match: '[]', enabled: 0 },
      { policy_id: 'p2', name: 'Tag legacy', action: 'tag', match: '[]', enabled: 0 },
      { policy_id: 'p3', name: 'Trash superseded', action: 'delete', match: '[]', enabled: 1 },
    ])
    await render()
    expect(listDispositionPolicies).not.toHaveBeenCalled()          // lazy — nothing loads while collapsed
    await expand(); await flush()
    expect(listDispositionPolicies).toHaveBeenCalled()
    expect(container.textContent).toContain('Old finance')
    expect(container.textContent).toContain('Trash superseded')
    expect(container.textContent).not.toContain('Tag legacy')       // 'tag' is not a lifecycle action
  })

  it('creates a folder-prefix archive rule with the backend field/op the template maps to', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'Archive 2019')
    await setValue(byLabel('Condition value'), 'Finance/2019/')      // default condition = Folder path starts with
    await click(btnByText('+ Create'))
    await flush()
    expect(createDispositionPolicy).toHaveBeenCalledWith('Archive 2019',
      [{ field: 'parent_folder', op: 'prefix', value: 'Finance/2019/' }], 'archive')
    expect(listDispositionPolicies).toHaveBeenCalledTimes(2)        // reloads after create
  })

  it('coerces a numeric condition and carries the chosen delete action', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'Stale')
    await setValue(byLabel('Condition'), 'notmod')                  // Not modified in the last N days
    await setValue(byLabel('Condition value'), '1095')
    await setValue(byLabel('Action'), 'delete')
    await click(btnByText('+ Create'))
    await flush()
    expect(createDispositionPolicy).toHaveBeenCalledWith('Stale',
      [{ field: 'modified_age_days', op: 'gt', value: 1095 }], 'delete')
  })

  it('enabling a rule calls the API and previewing shows the match count', async () => {
    listDispositionPolicies.mockResolvedValue([{ policy_id: 'p1', name: 'Old', action: 'archive', match: '[]', enabled: 0 }])
    previewDispositionPolicy.mockResolvedValue({ would_match: 42 })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(previewDispositionPolicy).toHaveBeenCalledWith('p1')
    expect(container.textContent).toContain('Would match')
    expect(container.textContent).toContain('42')
    await click(byLabel('Enable Old')); await flush()
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p1', true)
  })

  it('surfaces a create error inline (e.g. a non-admin refusal)', async () => {
    createDispositionPolicy.mockRejectedValue(new Error('admin required'))
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'X')
    await setValue(byLabel('Condition value'), 'Archive/')
    await click(btnByText('+ Create'))
    await flush()
    expect(container.textContent).toContain('admin required')
  })
})
