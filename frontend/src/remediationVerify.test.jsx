/**
 * R9, rendered — the panel whose job is to withhold a word.
 *
 *   · no finding is ever rendered as resolved because a fix was applied;
 *   · "confirmed" is stated as evidence about the corrected COPY, never about the original;
 *   · the three states sum on screen;
 *   · the re-scan control, where it exists, is named for what the endpoint actually does — re-read
 *     the ORIGINAL from its source — and carries the caveat beside it.
 *
 * The last one is the reason the design board's "Re-assess the changed documents" button is not
 * here. Nothing re-runs the criteria over the remediated copies; `POST /scans/{id}/rescore`
 * re-downloads the source document, which remediation leaves untouched, so on an unreplaced source
 * it re-reports every finding it was pressed to confirm.
 *
 * DOM assertions under vitest, not browser screenshots — the preview server's vite root is the
 * shared checkout whatever worktree it is started from.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationVerify from './RemediationVerify.jsx'

afterEach(unmountAll)

const HERE = dirname(fileURLToPath(import.meta.url))
// Source with every comment removed, so a rule stated in prose cannot fail its own check.
const codeOf = (f) => readFileSync(join(HERE, f), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

const CRITERIA = new Set(['1.1.1', '1.3.1'])
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto' } }

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc) => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity: 'SERIOUS' })

const ESTATE = [
  doc('a.docx', [finding('1.3.1'), finding('1.1.1')], { remediated_at: '2026-08-20T16:57:00Z' }),
  doc('b.docx', [finding('1.3.1')]),
]

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(RemediationVerify, { cap: CAP, assessment: ASMT, criteria: CRITERIA, ...props }))
  })
  return container
}

const text = (c) => c.textContent.replace(/\s+/g, ' ')
const buttons = (c) => [...c.querySelectorAll('button')].map((b) => b.textContent.trim())

describe('nothing, rather than zeros', () => {
  it('renders nothing before a run has been loaded', async () => {
    expect((await mount({ files: null })).textContent).toBe('')
  })
})

describe('applying is not resolving', () => {
  it('leads with the rule', async () => {
    const c = await mount({ files: ESTATE })
    const t = text(c)
    expect(t).toContain('A fix is a claim until a re-run confirms it')
    expect(t).toContain('Nothing here is counted as resolved because a fix was applied')
  })

  it('confirms nothing on a remediated document whose criteria did not come back clear', async () => {
    const c = await mount({ files: ESTATE })
    // a.docx has a corrected copy and two open findings; nothing may read as resolved.
    expect(text(c)).toContain('0 confirmed cleared + 2 applied but not confirmed + '
                            + '1 not yet remediated = 3 findings')
  })

  it('confirms only what a completed remediation-state row names', async () => {
    const c = await mount({ files: ESTATE,
                            appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'complete' }] } })
    expect(text(c)).toContain('1 confirmed cleared + 1 applied but not confirmed + '
                            + '1 not yet remediated = 3 findings')
  })

  it('does not read a seeded not-started row as a confirmation', async () => {
    const c = await mount({ files: ESTATE,
                            appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'not_started' }] } })
    expect(text(c)).toContain('0 confirmed cleared')
  })
})

describe('a confirmation is about the copy, not the original', () => {
  it('says so beside the numbers', async () => {
    const c = await mount({ files: ESTATE })
    const t = text(c)
    expect(t).toContain('evidence about the corrected copy')
    expect(t).toContain('The original documents are unchanged and still contain their findings')
    expect(t).toContain('ACP does not modify them')
  })

  it('describes a remediated document as having a corrected copy, not as fixed', async () => {
    const c = await mount({ files: ESTATE })
    expect(text(c)).toContain('corrected copy produced')
    expect(text(c)).toContain('no remediation run yet')
  })

  it('dates the verification from the re-scan, never from the remediation run', async () => {
    // a.docx carries remediated_at. That is when a copy was WRITTEN; it says nothing about when —
    // or whether — anything was re-scanned, so it must not be printed as a verification time.
    const c = await mount({ files: ESTATE })
    expect(text(c)).not.toContain('re-scanned 2026-08-20T16:57:00Z')
    const c2 = await mount({ files: ESTATE, appliedCriteria: {
      'a.docx': [{ rule_id: '1.3.1', state: 'complete', updated_at: '2026-08-20T17:02:00Z' }] } })
    expect(text(c2)).toContain('re-scanned 2026-08-20T17:02:00Z')
  })

  it('lists each document’s confirmed and still-open criteria', async () => {
    const c = await mount({ files: ESTATE, appliedCriteria: { 'a.docx': ['1.3.1'] } })
    const t = text(c)
    expect(t).toContain('Confirmed cleared')
    expect(t).toContain('Still open')
    expect(t).toContain('a.docx')
    expect(t).toContain('b.docx')
  })
})

describe('the re-scan control is named for what it does', () => {
  it('is absent entirely when the parent passes no handler', async () => {
    const c = await mount({ files: ESTATE })
    expect(buttons(c)).toEqual([])
    expect(text(c)).not.toMatch(/re-assess/i)
  })

  it('re-reads the original, and says that is not a re-run over the copy', async () => {
    const c = await mount({ files: ESTATE, onRescanSource: () => {} })
    const t = text(c)
    expect(buttons(c)).toEqual(['Re-scan the original', 'Re-scan the original'])
    expect(t).toContain('re-reads the document from its source')
    expect(t).toContain('it is not a re-run over the corrected copy, and ACP has no endpoint that is')
    expect(t).toContain('report the same findings again')
  })

  it('never offers a control described as re-assessing the remediated copies', async () => {
    const c = await mount({ files: ESTATE, onRescanSource: () => {} })
    expect(buttons(c).join(' ')).not.toMatch(/re-assess/i)
  })

  it('hands the parent the file it was pressed for', async () => {
    const got = []
    const c = await mount({ files: ESTATE, onRescanSource: (f) => got.push(f) })
    await act(async () => { c.querySelectorAll('button')[0].click() })
    // Documents are ordered by what is still open, so a.docx (2 open) sorts first.
    expect(got).toEqual(['a.docx'])
  })

  it('disables the row being re-read', async () => {
    const c = await mount({ files: ESTATE, onRescanSource: () => {}, rescanning: 'a.docx' })
    const busy = [...c.querySelectorAll('button')].filter((b) => b.disabled)
    expect(busy).toHaveLength(1)
    expect(busy[0].textContent.trim()).toBe('Re-reading…')
  })
})

describe('the prohibitions this screen inherits', () => {
  it('renders no percentage, no score and no effort estimate', async () => {
    const c = await mount({ files: ESTATE, onRescanSource: () => {},
                            appliedCriteria: { 'a.docx': ['1.3.1'] } })
    const t = text(c)
    expect(t).not.toMatch(/\d+\s?%/)
    expect(t).not.toMatch(/\bscore\b/i)
    expect(t).not.toMatch(/\b(hrs|hours|minutes|est\.)\b/i)
  })

  it('never uses the word fixed, archived or deleted about a document', () => {
    // Comments stripped: this guards the copy the component RENDERS, including branches these
    // cases do not exercise, and the prose above explaining the rule names the forbidden word.
    const src = codeOf('RemediationVerify.jsx')
    expect(src).not.toMatch(/\bfixed\b/i)
    expect(src).not.toMatch(/\barchiv/i)
    expect(src).not.toMatch(/\bdelet/i)
  })
})
