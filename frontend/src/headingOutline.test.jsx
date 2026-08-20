import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Mock just the one API call the component uses; scanId 'has-skip' yields an outline, anything else null.
vi.mock('./api.js', () => ({
  getHeadingOutline: (scanId) => Promise.resolve(scanId === 'has-skip'
    ? { before: [{ level: 1, text: 'Intro' }, { level: 3, text: 'Details' }],
        after: [{ level: 1, text: 'Intro' }, { level: 2, text: 'Details' }] }
    : null),
}))

const { default: HeadingOutline } = await import('./HeadingOutline.jsx')
afterEach(unmountAll)

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(HeadingOutline, props)) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })  // flush the fetch + state
  return container
}

describe('HeadingOutline', () => {
  it('renders the real before → corrected outline when the fetch returns one', async () => {
    const c = await mount({ scanId: 'has-skip', file: 'a.docx', wcag: 'WCAG 2.4.6',
                            fallback: createElement('div', null, 'FALLBACK') })
    expect(c.textContent).toContain('Before')
    expect(c.textContent).toContain('After (corrected)')
    expect(c.textContent).toContain('Intro')
    expect(c.textContent).toContain('Details')
    expect(c.textContent).not.toContain('FALLBACK')
    expect(c.querySelectorAll('ol').length).toBe(2)          // before + after lists
    // The corrected side renumbers the H3 to H2; the texts are unchanged.
    expect(c.textContent).toContain('H2')
  })

  it('renders the honest fallback when no outline is available', async () => {
    const c = await mount({ scanId: 'no-headings', file: 'a.docx',
                            fallback: createElement('div', null, 'FALLBACK') })
    expect(c.textContent).toContain('FALLBACK')
    expect(c.querySelector('ol')).toBeNull()
  })
})
