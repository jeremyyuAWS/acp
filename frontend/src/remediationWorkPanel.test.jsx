/**
 * R2 + R3, rendered — the four things the panel must never do.
 *
 *   · render five zeros for a run that has not happened;
 *   · advertise an AI-drafted criterion as something the Apply button will apply;
 *   · claim nothing is written to the user's drive when the Drive mirror is on;
 *   · say "fixed" about a document, when what remediation produces is a corrected copy.
 *
 * Asserted from the DOM rather than from the model, because the sum's entire purpose is to be
 * READ. An identity that holds in a unit test and is absent from the page protects nobody.
 *
 * These are DOM assertions under vitest, not browser screenshots. The preview server runs vite
 * against the SHARED checkout whatever worktree it is launched from, so a browser check of a
 * worktree change exercises code that does not contain it.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWork from './RemediationWork.jsx'

afterEach(unmountAll)

const HERE = dirname(fileURLToPath(import.meta.url))
// Source with every comment removed, so a rule stated in prose cannot fail its own check.
const codeOf = (f) => readFileSync(join(HERE, f), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

const CRITERIA = new Set(['1.1.1', '1.3.1', '1.4.3'])
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' },
              pdf: { '1.1.1': 'assisted', '1.4.3': 'auto' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto', '1.4.3': 'review' },
               pdf: { '1.1.1': 'review', '1.4.3': 'auto' } }

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc) => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity: 'SERIOUS' })

const ESTATE = [
  doc('a.docx', [finding('1.3.1'), finding('1.3.1'), finding('1.1.1'), finding('1.4.3')]),
  doc('b.pdf', [finding('1.4.3'), finding('1.1.1')]),
]

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(RemediationWork, { cap: CAP, assessment: ASMT, criteria: CRITERIA, ...props }))
  })
  return container
}

const text = (c) => c.textContent.replace(/\s+/g, ' ')
const buttons = (c) => [...c.querySelectorAll('button')].map((b) => b.textContent.trim())

describe('nothing, rather than zeros', () => {
  it('renders nothing at all before a run has been loaded', async () => {
    const c = await mount({ files: null })
    expect(c.textContent).toBe('')
  })

  it('renders the partition for a real run', async () => {
    const c = await mount({ files: ESTATE })
    expect(text(c)).toContain('ACP applies · deterministic')
    expect(text(c)).toContain('Drafted · you approve')
  })
})

describe('the partition sums on screen', () => {
  it('prints the identity and the total the assessment counted', async () => {
    const c = await mount({ files: ESTATE })
    expect(text(c)).toContain('3 + 2 + 1 + 0 + 0 = 6 findings')
    expect(text(c)).toContain('The same 6 findings the assessment counted')
    expect(text(c)).toContain('who does the work')
  })

  it('shows applied work moving between lanes without breaking the sum', async () => {
    const c = await mount({ files: ESTATE, appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'complete' }] } })
    expect(text(c)).toContain('1 + 2 + 1 + 2 + 0 = 6 findings')
  })
})

describe('the batch acts on the deterministic lane and says so', () => {
  it('offers a button for the automatic count only', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {} })
    expect(buttons(c)).toContain('Apply 3 fixes')
    expect(text(c)).toContain('Apply 3 automatic fixes')
  })

  it('names the deterministic criteria and never the drafted one', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {} })
    expect(text(c)).toContain('Covers 2 criteria (1.3.1, 1.4.3) across 2 documents')
    // 1.1.1 is drafted on both documents. The batch must not advertise it.
    expect(text(c)).not.toContain('1.1.1')
  })

  it('hands the parent the documents holding automatic work', async () => {
    let got = null
    const c = await mount({ files: ESTATE, onApplyAutomatic: (f) => { got = f } })
    const apply = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Apply 3'))
    await act(async () => { apply.click() })
    expect(got).toEqual(['a.docx', 'b.pdf'])
  })

  it('renders no button at all when the parent cannot perform the action', async () => {
    const c = await mount({ files: ESTATE })
    expect(buttons(c)).toEqual([])
    // The panel still explains the lane; it just does not offer a control nothing is behind.
    expect(text(c)).toContain('Apply 3 automatic fixes')
  })

  it('says the deterministic lane is empty rather than vanishing', async () => {
    const c = await mount({ files: [doc('a.docx', [finding('1.1.1'), finding('1.4.3')])],
                            onApplyAutomatic: () => {} })
    expect(text(c)).toContain('No finding here has a deterministic fix')
    expect(buttons(c)).toEqual([])
  })
})

describe('what the batch will and will not do, where the button is', () => {
  it('states that nothing applies without the explicit action and no draft is auto-approved', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {} })
    const t = text(c)
    expect(t).toContain('Nothing is applied without this explicit action')
    expect(t).toContain('no AI draft is ever approved by it')
  })

  it('always says the originals are not modified', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {} })
    expect(text(c)).toContain('Your original documents are never modified')
    expect(text(c)).toContain('corrected copy')
  })
})

describe('the drive claim is the setting, not the reassuring answer', () => {
  it('says nothing is written to the drive only when the mirror is off', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {},
                            driveMirror: { enabled: false } })
    expect(text(c)).toContain('nothing is written to your drive')
  })

  it('says the copy IS written to the drive when the mirror is on', async () => {
    // The design board's flat "Nothing is written to your drive" is false in this configuration —
    // remediate_file uploads the corrected copy to a folder in the source drive.
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {},
                            driveMirror: { enabled: true, folder: 'Remediated' } })
    const t = text(c)
    expect(t).toContain('also written to your drive')
    expect(t).toContain('“Remediated” folder')
    expect(t).toContain('a new file, never an overwrite')
    expect(t).not.toContain('nothing is written to your drive')
  })

  it('makes no claim about the destination when the setting has not been read', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {} })
    const t = text(c)
    expect(t).not.toContain('nothing is written to your drive')
    expect(t).not.toContain('also written to your drive')
    expect(t).toContain('a platform setting this screen has not read')
  })
})

describe('the prohibitions this screen inherits', () => {
  const SRC = codeOf('RemediationWork.jsx')

  it('renders no percentage, no score and no effort estimate', async () => {
    const c = await mount({ files: ESTATE, onApplyAutomatic: () => {},
                            driveMirror: { enabled: true, folder: 'Remediated' } })
    const t = text(c)
    expect(t).not.toMatch(/\d+\s?%/)
    expect(t).not.toMatch(/\bscore\b/i)
    expect(t).not.toMatch(/\b(hrs|hours|minutes|est\.)\b/i)
  })

  it('never says a document was fixed, archived or deleted', () => {
    // Rule 4 of the redesign, checked against the source so a future edit cannot slip the word
    // into a branch these cases do not happen to render.
    expect(SRC).not.toMatch(/\bfixed\b/i)
    expect(SRC).not.toMatch(/\barchiv/i)
    expect(SRC).not.toMatch(/\bdelet/i)
  })
})
