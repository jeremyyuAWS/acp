/**
 * The first screen of a workspace that has discovered nothing: one prompt, and no numbers.
 *
 * It used to be ScanSetup — the format and criterion picker, in full. Two things were wrong with
 * that under the Discover/Assess redesign, and only the second is obvious:
 *
 *   · it asked which WCAG criteria to apply before any inventory existed, so the answer could not
 *     be informed by the documents actually held;
 *   · it was the THIRD writer of `settings.scan_scope`. AssessScope's header already recorded two
 *     controls "that did not know about each other"; the wizard's copy went in #532, and this was
 *     the last one.
 *
 * What replaces it is OV-02, and the load-bearing half of that requirement is the NEGATIVE one:
 * "no zero-valued report cards that imply a completed run". A grid of 0s is the same false-verdict
 * shape as #479/#483/#491/#502 — absence of a run rendered as a run that found nothing.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import EmptyState from './EmptyState.jsx'

afterEach(unmountAll)

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(EmptyState, props)) })
  return container
}

describe('what the first screen says', () => {
  it('states that nothing has run, rather than showing a result', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/No assessment has run yet/i)
  })

  it('offers exactly one action, and it goes to Source', async () => {
    const onGoToSource = vi.fn()
    const c = await mount({ onGoToSource })
    const buttons = [...c.querySelectorAll('button')]
    expect(buttons, 'the first screen offers more than one action').toHaveLength(1)
    expect(buttons[0].textContent).toMatch(/Go to Source/)
    await act(async () => { buttons[0].click() })
    expect(onGoToSource).toHaveBeenCalled()
  })

  it('survives being rendered without a handler', async () => {
    // App owns navigation; a missing prop must not throw on the very first screen.
    const c = await mount()
    await act(async () => { c.querySelector('button').click() })
    expect(c.textContent).toMatch(/No assessment has run yet/i)
  })

  it('says where discovery results go, so their absence here is not a bug report', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/Discovery results appear on the Discover tab/i)
  })
})

describe('what it must NOT show', () => {
  it('renders no digits at all — no zero-valued cards', async () => {
    // THE requirement. Any number here reads as a measurement, and the only honest measurement
    // before a run is none. The step labels are "1 ·", "2 ·", "3 ·" — ordinals, not counts —
    // so they are excluded explicitly rather than by loosening the assertion.
    const c = await mount()
    const withoutOrdinals = c.textContent.replace(/[123] ·/g, '')
    expect(withoutOrdinals, 'a number appears on the pre-discovery screen')
      .not.toMatch(/\d/)
  })

  it('asks for nothing — it carries no control but the single action', async () => {
    // Asserted as CONTROLS, not as vocabulary. The first draft of this banned the phrase
    // "document type", and failed on the orientation line "Choose document types and WCAG
    // criteria, then run" — which describes what Assess does later rather than asking for it
    // here. Banning the words would have forced the copy to get vaguer to satisfy a test; what
    // the requirement actually forbids is a decision being collected before an inventory exists,
    // and a control is what collecting looks like.
    const c = await mount()
    expect(c.querySelectorAll('input, select, textarea'),
      'the first screen collects input before anything has been discovered').toHaveLength(0)
    expect(c.querySelectorAll('button'), 'more than one action on the first screen').toHaveLength(1)
  })

  it('no longer writes the assessment scope', () => {
    // The third writer of `settings.scan_scope`, removed. Asserted at the source because the
    // absence of a network call is not observable from the DOM.
    const src = read('EmptyState.jsx')
    // The IMPORT, not the word: the comment above the component explains why ScanSetup was
    // removed, and that explanation is worth keeping. A test that forbids naming the thing you
    // removed pushes the reason out of the file.
    expect(src, 'EmptyState still imports ScanSetup').not.toMatch(/^import .*ScanSetup/m)
    expect(src, 'EmptyState still writes settings').not.toMatch(/updateSettings\(/)
  })
})

describe('the app routes it', () => {
  it('sends the action to the Sources view', () => {
    // The button is inert without this wiring, and a DOM test of EmptyState alone cannot see it.
    const app = read('App.jsx')
    expect(app).toMatch(/<EmptyState onGoToSource=\{\(\) => \{ setView\('integrations'\)/)
  })

  it('still gates the report on a completed assessment', () => {
    // OV-01/OV-04 predate this change and must survive it: Overview renders only when a run has
    // been assessed; discovery alone never populates it.
    expect(read('App.jsx')).toMatch(/view === 'overview' && \(run \? \(assessed \?/)
  })
})
