/**
 * The folder browser's failure and loading states, at the DOM.
 *
 * folderErrorCopy.test.js proves the sentences are right and that the source references them. It
 * cannot prove the picker RENDERS them, that the retry button re-runs the load, or that the raw
 * text is reachable rather than merely present in the file — which is the difference between a
 * disclosure and a leak.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import FolderPicker from './FolderPicker.jsx'

afterEach(unmountAll)

const REAL_400 = "Microsoft Graph error: Client error '400 Bad Request' for url "
  + "'https://graph.microsoft.com/v1.0/drives/b!C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_/items/…'"

async function mount(lister, props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(FolderPicker, {
      layout: 'inline', rootName: 'OneDrive', sourceName: 'SharePoint', lister, ...props,
    }))
  })
  return container
}

const failing = (msg) => vi.fn(async () => { throw new Error(msg) })
const ok = vi.fn(async () => ({ folders: [{ id: 'a', name: 'Accessibility Program' }] }))

describe('when the folder list fails', () => {
  it('shows the friendly sentence, not the Graph URL', async () => {
    const c = await mount(failing(REAL_400))
    expect(c.textContent).toMatch(/couldn’t load your folders/i)
    // The alert region is what a user reads first; the raw text must not be in it as the message.
    const alert = c.querySelector('[role="alert"]')
    expect(alert, 'the failure is not announced as an alert').toBeTruthy()
    const summaryText = alert.textContent.split('Technical details')[0]
    expect(summaryText, 'the Graph URL is in the headline').not.toMatch(/graph\.microsoft\.com/)
  })

  it('keeps the raw error reachable under a disclosure', async () => {
    const c = await mount(failing(REAL_400))
    const det = c.querySelector('details')
    expect(det, 'there is no technical-details disclosure').toBeTruthy()
    expect(det.textContent).toMatch(/Technical details/)
    expect(det.textContent, 'the raw error was dropped entirely — support needs it')
      .toMatch(/graph\.microsoft\.com/)
    expect(det.open, 'the raw error is expanded by default').toBeFalsy()
  })

  it('does not advise reconnecting over a malformed request', async () => {
    const c = await mount(failing(REAL_400))
    const alert = c.querySelector('[role="alert"]')
    const summaryText = alert.textContent.split('Technical details')[0]
    expect(summaryText, 'a working connection was blamed').not.toMatch(/Reconnect source/)
  })

  it('does advise reconnecting when the credential IS the problem', async () => {
    // The control: without this, the assertion above would pass on copy that never says it.
    const c = await mount(failing('401 Unauthorized'))
    expect(c.textContent).toMatch(/Reconnect source/)
  })

  it('retries the same folder when asked', async () => {
    const lister = vi.fn()
      .mockRejectedValueOnce(new Error(REAL_400))
      .mockResolvedValueOnce({ folders: [{ id: 'a', name: 'Accessibility Program' }] })
    const c = await mount(lister)
    expect(c.textContent).toMatch(/couldn’t load/i)

    const retry = [...c.querySelectorAll('button')].find((b) => /Try again/.test(b.textContent))
    expect(retry, 'no retry control was offered').toBeTruthy()
    await act(async () => { retry.click() })

    expect(lister).toHaveBeenCalledTimes(2)
    expect(c.textContent, 'the retry did not recover the list').toMatch(/Accessibility Program/)
    expect(c.textContent).not.toMatch(/couldn’t load/i)
  })
})

describe('while loading', () => {
  it('shows placeholder rows rather than an empty box', async () => {
    // An empty bordered box is the same space that says "No subfolders here" — a stated absence.
    // A never-resolving lister holds the component in its loading state.
    const { root, container } = createTestRoot()
    await act(async () => {
      root.render(createElement(FolderPicker, {
        layout: 'inline', rootName: 'OneDrive', sourceName: 'SharePoint',
        lister: () => new Promise(() => {}),
      }))
    })
    const busy = container.querySelector('[aria-busy="true"]')
    expect(busy, 'nothing announces that the list is loading').toBeTruthy()
    expect(busy.textContent).toMatch(/Loading folders from SharePoint/)
    expect(container.textContent, 'the empty state is showing while still loading')
      .not.toMatch(/No subfolders here/)
  })

  it('stops showing them once the list arrives', async () => {
    const c = await mount(ok)
    expect(c.querySelector('[aria-busy="true"]')).toBeNull()
    expect(c.textContent).toMatch(/Accessibility Program/)
  })
})
