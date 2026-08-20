import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Mock the one API call the component uses. scanId 'marked' yields a table whose header row is marked;
// 'unmarked' yields one where it is not; anything else yields null (degrade to fallback).
vi.mock('./api.js', () => ({
  getTableStructure: (scanId) => Promise.resolve(
    scanId === 'marked'
      ? [{ rows: [['Name', 'Role'], ['Ada', 'Author']], headerRow: 0, headerMarked: true, truncated: false }]
      : scanId === 'unmarked'
        ? [{ rows: [['Q', 'A'], ['1', '2']], headerRow: 0, headerMarked: false, truncated: false }]
        : null),
}))

const { default: TableStructure } = await import('./TableStructure.jsx')
afterEach(unmountAll)

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(TableStructure, props)) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })  // flush the fetch + state
  return container
}

describe('TableStructure', () => {
  it('renders the real cell grid with the header row as <th> when the fetch returns one', async () => {
    const c = await mount({ scanId: 'marked', file: 'a.docx', wcag: 'WCAG 1.3.1',
                            fallback: createElement('div', null, 'FALLBACK') })
    expect(c.querySelector('table')).not.toBeNull()
    expect(c.textContent).toContain('Name')
    expect(c.textContent).toContain('Ada')
    expect(c.textContent).not.toContain('FALLBACK')
    const ths = c.querySelectorAll('th')
    expect(ths.length).toBe(2)                                   // the two header cells
    expect([...ths].every((th) => th.getAttribute('scope') === 'col')).toBe(true)
  })

  it('says the header is not marked when it is only the de-facto first row', async () => {
    const c = await mount({ scanId: 'unmarked', file: 'a.docx', wcag: 'WCAG 1.3.1',
                            fallback: createElement('div', null, 'FALLBACK') })
    expect(c.textContent).toContain('isn’t marked')             // honest: reads as header, not yet marked
    expect(c.textContent).not.toContain('FALLBACK')
  })

  it('renders the honest fallback when no qualifying table is available', async () => {
    const c = await mount({ scanId: 'no-table', file: 'a.docx',
                            fallback: createElement('div', null, 'FALLBACK') })
    expect(c.textContent).toContain('FALLBACK')
    expect(c.querySelector('table')).toBeNull()
  })
})
