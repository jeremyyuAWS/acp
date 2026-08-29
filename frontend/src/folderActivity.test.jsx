import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: FolderActivity } = await import('./FolderActivity.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(FolderActivity, props)) })
  return container
}
afterEach(() => unmountAll())

describe('FolderActivity', () => {
  it('renders nothing when both lists are empty or absent', async () => {
    const c = await mount({})
    expect(c.textContent).toBe('')
  })

  it('renders nothing for empty arrays, not a "nothing to show" placeholder', async () => {
    const c = await mount({ active: [], recent: [] })
    expect(c.textContent).toBe('')
  })

  it('lists currently-exploring folders by path, with a live pulse and a text label', async () => {
    const c = await mount({
      active: [{ name: 'Policies', path: 'My Drive/Compliance/Policies', started_at: 't0' }],
    })
    expect(c.textContent).toMatch(/Currently exploring 1 folder/i)
    expect(c.textContent).toMatch(/My Drive\/Compliance\/Policies/)
    expect(c.textContent).toMatch(/scanning/i)
    expect(c.querySelector('.pulsedot')).toBeTruthy()
  })

  it('pluralizes "folders" for more than one active folder', async () => {
    const c = await mount({
      active: [
        { name: 'A', path: 'My Drive/A', started_at: 't0' },
        { name: 'B', path: 'My Drive/B', started_at: 't0' },
      ],
    })
    expect(c.textContent).toMatch(/Currently exploring 2 folders/i)
  })

  it('shows a completed folder with its real file count', async () => {
    const c = await mount({
      recent: [{ name: 'Benefits', path: 'My Drive/Benefits', state: 'completed',
                files_found: 12, completed_at: 't1' }],
    })
    expect(c.textContent).toMatch(/My Drive\/Benefits/)
    expect(c.textContent).toMatch(/Scanned/)
    expect(c.textContent).toMatch(/12 files/)
  })

  it('singularizes the file count for exactly one file', async () => {
    const c = await mount({
      recent: [{ name: 'Solo', path: 'My Drive/Solo', state: 'completed',
                files_found: 1, completed_at: 't1' }],
    })
    expect(c.textContent).toMatch(/1 file\b/)
    expect(c.textContent).not.toMatch(/1 files/)
  })

  it('names a rate-limited folder distinctly from a generic failure, in text not just color', async () => {
    const c = await mount({
      recent: [
        { name: 'Throttled', path: 'My Drive/Throttled', state: 'rate_limited',
          files_found: 0, completed_at: 't1' },
        { name: 'Denied', path: 'My Drive/Denied', state: 'failed', files_found: 0, completed_at: 't1' },
      ],
    })
    expect(c.textContent).toMatch(/Rate-limited/)
    expect(c.textContent).toMatch(/Failed/)
  })

  it('does not show a file count alongside a failed or rate-limited entry', async () => {
    const c = await mount({
      recent: [{ name: 'Throttled', path: 'My Drive/Throttled', state: 'rate_limited',
                files_found: 0, completed_at: 't1' }],
    })
    expect(c.textContent).not.toMatch(/0 files/)
  })

  it('shows both sections together when both are present', async () => {
    const c = await mount({
      active: [{ name: 'Legal', path: 'My Drive/Legal', started_at: 't0' }],
      recent: [{ name: 'Finance', path: 'My Drive/Finance', state: 'completed',
                files_found: 4, completed_at: 't1' }],
    })
    expect(c.textContent).toMatch(/Currently exploring/i)
    expect(c.textContent).toMatch(/Recently finished/i)
  })

  it('names the boundary — scanned means listed, not assessed', async () => {
    const c = await mount({
      recent: [{ name: 'X', path: 'My Drive/X', state: 'completed', files_found: 1, completed_at: 't1' }],
    })
    expect(c.textContent).toMatch(/not that its documents were assessed/i)
  })

  it('falls back to a completed state for an unrecognized state value rather than rendering nothing', async () => {
    const c = await mount({
      recent: [{ name: 'Odd', path: 'My Drive/Odd', state: 'something_new', files_found: 3, completed_at: 't1' }],
    })
    expect(c.textContent).toMatch(/My Drive\/Odd/)
  })
})
