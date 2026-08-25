import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import WorkerCard from './WorkerCard.jsx'

afterEach(unmountAll)

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(WorkerCard, props)) })
  return container
}

describe('WorkerCard', () => {
  it('renders nothing when no current file and filesDone is 0', async () => {
    const c = await render({ current: null, filesDone: 0, filesTotal: 100, elapsed: 5 })
    expect(c.firstChild).toBeNull()
  })

  it('renders when a current file is set even if filesDone is 0', async () => {
    const c = await render({ current: '/docs/report.pdf', filesDone: 0, filesTotal: 50, elapsed: 1 })
    expect(c.textContent).toMatch(/report\.pdf/)
  })

  it('shows a progressbar with correct aria-valuenow', async () => {
    const c = await render({ current: '/a.pdf', filesDone: 25, filesTotal: 100, elapsed: 10 })
    const bar = c.querySelector('[role="progressbar"]')
    expect(bar).toBeTruthy()
    expect(bar.getAttribute('aria-valuenow')).toBe('25')
    expect(bar.getAttribute('aria-valuemin')).toBe('0')
    expect(bar.getAttribute('aria-valuemax')).toBe('100')
  })

  it('labels the progressbar with done-of-total counts', async () => {
    const c = await render({ current: '/b.docx', filesDone: 10, filesTotal: 200, elapsed: 5 })
    const label = c.querySelector('[role="progressbar"]').getAttribute('aria-label')
    expect(label).toMatch(/10/)
    expect(label).toMatch(/200/)
  })

  it('shows 0% when filesDone is 0 but filesTotal > 0', async () => {
    const c = await render({ current: '/c.pdf', filesDone: 0, filesTotal: 100, elapsed: 5 })
    expect(c.textContent).toMatch(/0%/)
  })

  it('shows 100% when all files are done', async () => {
    const c = await render({ current: '/done.pdf', filesDone: 50, filesTotal: 50, elapsed: 30 })
    expect(c.textContent).toMatch(/100%/)
  })

  it('shows speed after 3 seconds with files processed', async () => {
    const c = await render({ current: '/x.pdf', filesDone: 30, filesTotal: 100, elapsed: 10 })
    expect(c.textContent).toMatch(/files\/s/)
  })

  it('does not show speed when elapsed < 3', async () => {
    const c = await render({ current: '/x.pdf', filesDone: 10, filesTotal: 100, elapsed: 2 })
    expect(c.textContent).not.toMatch(/files\/s/)
  })

  it('shows ETA when speed is available and files remain', async () => {
    const c = await render({ current: '/y.pdf', filesDone: 10, filesTotal: 100, elapsed: 5 })
    expect(c.textContent).toMatch(/remaining/)
  })

  it('hides ETA when all files are done', async () => {
    const c = await render({ current: '/z.pdf', filesDone: 100, filesTotal: 100, elapsed: 20 })
    expect(c.textContent).not.toMatch(/remaining/)
  })

  it('formats ETA in seconds when under 60 seconds', async () => {
    // 50 done in 5s = 10/s; 10 remaining → 1s → ~1s
    const c = await render({ current: '/f.pdf', filesDone: 50, filesTotal: 60, elapsed: 5 })
    expect(c.textContent).toMatch(/~\d+s remaining/)
  })

  it('formats ETA in minutes when over 60 seconds', async () => {
    // 10 done in 5s = 2/s; 990 remaining → 495s → ~9m
    const c = await render({ current: '/f.pdf', filesDone: 10, filesTotal: 1000, elapsed: 5 })
    expect(c.textContent).toMatch(/~\d+m remaining/)
  })

  it('truncates a long path but preserves the filename', async () => {
    const longPath = '/very/long/nested/folder/structure/with/many/levels/document.pdf'
    const c = await render({ current: longPath, filesDone: 1, filesTotal: 10, elapsed: 5 })
    const el = c.querySelector('[title]')
    expect(el.getAttribute('title')).toBe(longPath)
    expect(el.textContent).toContain('document.pdf')
    expect(el.textContent.length).toBeLessThan(longPath.length)
  })

  it('exposes the full path via title attribute', async () => {
    const path = '/folder/file.docx'
    const c = await render({ current: path, filesDone: 5, filesTotal: 20, elapsed: 5 })
    expect(c.querySelector('[title]').getAttribute('title')).toBe(path)
  })
})
