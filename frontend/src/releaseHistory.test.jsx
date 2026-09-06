// @vitest-environment jsdom
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReleaseHistory from './ReleaseHistory.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

describe('ReleaseHistory', () => {
  it('shows durable cross-run evidence and failures', async () => {
    const loadHistory = vi.fn().mockResolvedValue({ releases: [{
      release_id: 'rel-42', scan_id: 'scan-8', actor: 'owner@example.com', source: 'sharepoint',
      folder_name: 'Finance release', status: 'partial', created_at: '2026-09-06T12:00:00Z',
      updated_at: '2026-09-06T12:02:00Z', published: 1, failed: 1, remaining: 0,
      destinations: [{ location: 'Finance / Reports', folder_url: 'https://example.com/folder' }],
      documents: [
        { file: 'ready.pdf', status: 'published', created: false, verification: 'checksum verified',
          checksum: 'abc123', destination_path: 'Remediated/Finance/ready.pdf', released_url: 'https://example.com/file' },
        { file: 'failed.docx', status: 'failed', failure_category: 'provider_write_failed', explanation: 'Permission denied' },
      ],
    }] })
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(ReleaseHistory, { loadHistory })))
    expect(container.textContent).toContain('Finance release')
    expect(container.textContent).toContain('owner@example.com')
    expect(container.textContent).toContain('rel-42')
    expect(container.textContent).toContain('Reused · checksum verified · SHA-256 abc123')
    expect(container.textContent).toContain('Failed · Permission denied')
    expect(container.querySelector('a[href="https://example.com/folder"]')).toBeTruthy()
    expect(container.querySelector('a[href="https://example.com/file"]')).toBeTruthy()

    const search = container.querySelector('input[type="search"]')
    const type = (value) => act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, value)
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    type('permission denied')
    expect(container.textContent).toContain('failed.docx')
    type('no match')
    expect(container.textContent).toContain('No releases match “no match”')
  })

  it('makes loading failures retryable', async () => {
    const loadHistory = vi.fn().mockRejectedValue(new Error('History unavailable'))
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(ReleaseHistory, { loadHistory })))
    expect(container.querySelector('[role="alert"]').textContent).toContain('History unavailable')
    act(() => [...container.querySelectorAll('button')].find((button) => button.textContent === 'Retry').click())
    expect(loadHistory).toHaveBeenCalledTimes(2)
  })
})
