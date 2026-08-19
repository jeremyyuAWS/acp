import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

// P1 — the "Improve" palette gains four content/tone steers on top of #131's shorter / more detail /
// regenerate: Mention the numbers · Ignore colours · Professional tone · Plain language. Each must be
// wired end-to-end (button → style key → suggestFix style param → vision-model prompt), reuse the
// existing refine call path, and stay disabled while a draft is in flight.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

const ProposalEditors = (await import('./ProposalEditors.jsx')).default

let container
const mount = async (props) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(ProposalEditors, props)) })
  return c
}
afterEach(unmountAll)

const NEW = [
  ['numbers', 'Mention the numbers'],
  ['no_colour', 'Ignore colours'],
  ['professional', 'Professional tone'],
  ['plain', 'Plain language'],
]

describe('extended Improve palette — the four new steers', () => {
  it('renders all four new buttons (plus the original three) once a draft exists', async () => {
    const onDraft = vi.fn()
    const c = await mount({
      proposals: [{ locator: 'p1', thumb: null }], values: ['A chart of Q3 revenue'],
      onChange: () => {}, sc: '1.1.1', onDraft, draftingIdx: null,
    })
    const labels = [...c.querySelectorAll('.evcard-refine .evcard-refine-btn')].map((b) => b.textContent)
    for (const [, label] of NEW) expect(labels).toContain(label)
    // original three still present and contiguous → 7 total
    expect(labels).toEqual(expect.arrayContaining(['Shorter', 'More detail', '↻ Regenerate']))
    expect(labels.length).toBe(7)
  })

  it('each new button re-asks through the existing refine path with its own style key', async () => {
    const onDraft = vi.fn()
    const c = await mount({
      proposals: [{ locator: 'p1', thumb: null }], values: ['A chart of Q3 revenue'],
      onChange: () => {}, sc: '1.1.1', onDraft, draftingIdx: null,
    })
    const byLabel = Object.fromEntries(
      [...c.querySelectorAll('.evcard-refine .evcard-refine-btn')].map((b) => [b.textContent, b]))
    for (const [key, label] of NEW) {
      await act(async () => { byLabel[label].dispatchEvent(new MouseEvent('click', { bubbles: true })) })
      expect(onDraft).toHaveBeenCalledWith(0, key)
    }
  })

  it('disables the new buttons while a draft is in flight, exactly as the original three', async () => {
    const c = await mount({
      proposals: [{ locator: 'p1', thumb: null }], values: ['A chart of Q3 revenue'],
      onChange: () => {}, sc: '1.1.1', onDraft: vi.fn(), draftingIdx: 0,
    })
    const btns = [...c.querySelectorAll('.evcard-refine .evcard-refine-btn')]
    expect(btns.length).toBe(7)
    expect(btns.every((b) => b.disabled)).toBe(true)
  })

  it('EvidenceCard maps each new style key to a human status word', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/style === 'numbers' \? ' \(numbers stated\)'/)
    expect(src).toMatch(/style === 'no_colour' \? ' \(colour-free\)'/)
    expect(src).toMatch(/style === 'professional' \? ' \(professional tone\)'/)
    expect(src).toMatch(/style === 'plain' \? ' \(plain language\)'/)
  })

  it('the backend vision prompt steers on each new style key (end-to-end, not a no-op button)', () => {
    const src = read('../../api/ai.py')
    for (const [key] of NEW) expect(src).toMatch(new RegExp(`"${key}":`))
  })
})
