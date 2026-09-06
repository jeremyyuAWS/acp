import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import DiscoveryLifecycleResults from './DiscoveryLifecycleResults.jsx'
import DiscoveryFolderLabel, { readableFolderPath } from './DiscoveryFolderLabel.jsx'
import { getDriveFolderName } from './api.js'
vi.mock('./api.js', () => ({ getDriveFolderName: vi.fn(async () => ({
  name: 'Working', path: 'Department Drives / Cardiology / Working',
})), listDispositionPolicies: vi.fn(async () => []) }))
afterEach(() => { unmountAll(); vi.clearAllMocks() })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
it('filters supported files by enabled winning rule and reveals saved metadata', async () => {
  const { root, container } = createTestRoot()
  const rows = [
    { file: 'Policy.docx', lifecycle_rule_id: 'r1', lifecycle_status: 'Archive Candidate', source_modified: '2026-08-01T12:00:00Z', owner: 'Deva', size_kb: 0, lifecycle_reason: 'Older than cutoff' },
    { file: 'Report.pdf', lifecycle_status: 'Active' },
    { file: 'Photo.png', lifecycle_rule_id: 'r1' },
  ]
  await act(async () => root.render(<DiscoveryLifecycleResults rows={rows} policies={[
    { policy_id: 'r1', name: 'Old policies', enabled: 1, action: 'archive' },
    { policy_id: 'r2', name: 'Disabled rule', enabled: 0, action: 'archive' },
  ]} />))
  expect(container.textContent).not.toContain('Photo.png')
  expect(container.textContent).not.toContain('Disabled rule')
  const select = container.querySelector('select')
  expect(select.textContent).toContain('Old policies (1)')
  await act(async () => { select.value = 'r1'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(container.textContent).not.toContain('Report.pdf')
  expect(container.textContent).toContain('Older than cutoff')
  expect(container.textContent).toContain('Deva')
  expect(container.textContent).toContain('0 KB')
  await act(async () => container.querySelector('button').click())
  expect(container.textContent).toContain('Report.pdf')
})
it('shows a readable Drive folder name instead of its ID', async () => {
  const { root, container } = createTestRoot()
  const id = '1abcdefghijklmnopqrstuvwxyz'
  await act(async () => root.render(<DiscoveryFolderLabel source="drive" folder={id} />))
  expect(container.textContent).toBe('Department Drives / Cardiology / Working')
  expect(container.textContent).not.toContain(id)
  expect(container.querySelector('span').title).toContain(id)
  expect(getDriveFolderName).toHaveBeenCalledWith(id)
})
it('does not send local or SharePoint paths to Google', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<DiscoveryFolderLabel source="sharepoint" folder="Clinical/Policies" />))
  expect(container.textContent).toBe('Clinical/Policies')
  expect(getDriveFolderName).not.toHaveBeenCalled()
})
it('removes the Graph drive root prefix from displayed folder paths', async () => {
  const { root, container } = createTestRoot()
  const path = '/drive/root:/Clinical Shared Documents/Cardiology'
  await act(async () => root.render(<DiscoveryFolderLabel source="sharepoint" folder={path} />))
  expect(container.textContent).toBe('Clinical Shared Documents/Cardiology')
  expect(container.querySelector('span').title).toBe(path)
  expect(getDriveFolderName).not.toHaveBeenCalled()
  expect(readableFolderPath('/drive/root:')).toBe('Drive root')
})
it('bounds the rendered metadata rows while keeping the full search population', async () => {
  const { root, container } = createTestRoot()
  const rows = Array.from({ length: 120 }, (_, i) => ({ file: `Document-${i}.pdf` }))
  await act(async () => root.render(<DiscoveryLifecycleResults rows={rows} policies={[]} />))
  expect(container.querySelectorAll('details')).toHaveLength(50)
  expect(container.textContent).toContain('120 of 120 supported documents match')
  const next = [...container.querySelectorAll('button')].find(b => b.textContent === 'Next page')
  await act(async () => next.click())
  expect(container.textContent).toContain('Page 2 of 3')
  expect(container.querySelectorAll('details')).toHaveLength(50)
})
