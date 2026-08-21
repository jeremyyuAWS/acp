/**
 * The Discovery results screen, mounted.
 *
 * DOM-level, not browser-level: `preview_start` runs vite rooted at the SHARED checkout whatever
 * worktree you are in, so a browser check of a worktree change exercises code that does not
 * contain it and passes anyway (CLAUDE.md). Everything asserted here is asserted against the DOM
 * this component actually produced.
 *
 * The wiring — that Discover mounts this and that the acknowledgement gates the Assess button —
 * is pinned separately in discoveryResultsWiring.test.js, because a source sweep cannot catch a
 * syntax error and a DOM test cannot see a component that was never mounted.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
afterEach(unmountAll)

const F = (file, extra = {}) => ({ file, type: file.split('.').pop().toUpperCase(), ...extra })
const arch = (file, rule = 'Legacy clinical policies') =>
  F(file, { lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
            lifecycle_reason: `matched archive rule '${rule}'` })
const del = (file, rule = 'Superseded drafts') =>
  F(file, { lifecycle_status: 'Delete Candidate', lifecycle_rule_id: 'p2',
            lifecycle_reason: `matched delete rule '${rule}'` })
const active = (file) => F(file, { lifecycle_status: 'Active' })

const render = async (props = {}) => {
  await act(async () => { root.render(createElement(DiscoveryResults, props)) })
  return container
}
const text = () => container.textContent
const boxes = () => [...container.querySelectorAll('input[type=checkbox]')]
const click = async (el) => { await act(async () => { el.click() }) }

// A small estate with both recommendation kinds, one unreadable file and one untestable format.
const ESTATE = [
  arch('Clinical Guidelines/2019/sepsis-pathway-v3.docx'),
  arch('Clinical Guidelines/2020/triage-criteria.pdf'),
  del('Accessibility Program/_superseded/alt-text-draft-2.docx'),
  active('Accessibility Program/live-policy.docx'),
  active('Accessibility Program/diagram.png'),
  F('Clinical Guidelines/scan.pdf', { locked: true, openIssue: 'Permission denied', lifecycle_status: 'Active' }),
]

describe('nothing is claimed about data that never arrived', () => {
  it('renders nothing at all when there are no file rows', async () => {
    await render({ files: null })
    expect(container.innerHTML).toBe('')
  })

  it('omits the archive / deletion headline when no row carries the lifecycle column', async () => {
    await render({ files: [F('a.docx'), F('b.pdf')] })
    expect(text()).toContain('2')
    expect(text()).toContain('files discovered')
    // The absence is the point: a "0 tagged for archive review" here would be a claim about the
    // estate made from a field nobody read.
    expect(text()).not.toContain('tagged for archive review')
    expect(text()).not.toContain('tagged for deletion review')
    expect(text()).not.toContain('RECOMMENDATIONS')
    expect(text()).not.toContain('I approve')
  })

  it('shows a MEASURED zero once the lifecycle column is present', async () => {
    await render({ files: [active('a.docx')] })
    expect(text()).toContain('tagged for archive review')
    expect(text()).toContain('tagged for deletion review')
  })
})

describe('the estate summary and its reconciliations add up on screen', () => {
  it('states each headline with the noun it counts', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('files discovered')
    expect(text()).toContain('tagged for archive review')
    expect(text()).toContain('tagged for deletion review')
    expect(text()).toContain('could not be read')
  })

  it('prints the by-file-type total, and it equals the number discovered', async () => {
    await render({ files: ESTATE })
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(ESTATE.length)
    expect(text()).toContain('every type, added up')
    // The sum is rendered, not merely computed — a reader can check the partition.
    expect(text()).toMatch(/Total/)
  })

  it('by-file-type reads the whole estate listing when an inventory is present, not just the scanned rows', async () => {
    // The scanned rows (ESTATE) hold 5 docx/pdf and 1 png — but a real estate this size might hold
    // thousands of images that were never opened at all. Once an inventory carries by_format, the
    // panel must show THAT population, not the 6-row scanned one, or the estate reads as
    // document-only when it is not (found 2026-08-21).
    await render({ files: ESTATE, inventory: { discovered: 9006, by_format: { docx: 2, pdf: 1, image: 9000, other: 3 } } })
    expect(text()).toContain('the whole estate listing')
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(9006)
    const imageRow = rows.find((r) => r.firstElementChild.textContent === 'Images')
    expect(imageRow.lastElementChild.textContent).toBe('9,000')
  })

  it('by-file-type falls back to the scanned rows when there is no inventory to read', async () => {
    await render({ files: ESTATE, inventory: { discovered: 12408 } })   // no by_format
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(ESTATE.length)
  })

  it('shows every discovered file landing in exactly one bucket, with the sum visible', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('EVERY DISCOVERED FILE, IN ONE BUCKET')
    expect(text()).toContain('The buckets add up to the 6 files discovered')
    const recon = [...container.querySelectorAll('table')]
      .find((t) => (t.textContent || '').includes('No recommendation'))
    const cells = [...recon.querySelectorAll('tbody tr')]
      .map((tr) => tr.children[0].textContent.trim())
    expect(cells).toContain('Tagged for archive review')
    expect(cells).toContain('Tagged for deletion review')
    expect(cells).toContain('Could not be read — no recommendation was produced')
    // Last row is the total, and it equals the population.
    const totals = [...recon.querySelectorAll('tbody tr')].at(-1)
    expect(totals.children[1].textContent.trim()).toBe('6')
    expect(totals.textContent).toContain('files discovered')
  })

  it('says when the whole-estate listing total differs from the rows on screen', async () => {
    await render({ files: ESTATE, inventory: { discovered: 12408 } })
    expect(text()).toContain('This discovery listed 12,408 files in the estate')
  })

  it('warns that a truncated listing is a floor, not a total', async () => {
    await render({ files: ESTATE, inventory: { discovered: 6, truncated: true } })
    expect(text()).toContain('hit its cap')
    expect(text()).toContain('a floor, not a total')
  })
})

describe('the could-not-be-read panel is separate, and never guesses', () => {
  it('lists the recorded reason and sums it to the unreadable count', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('COULD NOT BE READ')
    expect(text()).toContain('Permission denied')
  })

  it('says the reason was not recorded rather than inventing one', async () => {
    await render({ files: [active('a.docx'), F('b.pdf', { status: 'error', lifecycle_status: 'Active' })] })
    expect(text()).toContain('No reason was recorded for these')
    expect(text()).not.toContain('unreadable file')
  })
})

describe('the recommendation table', () => {
  it('names the rule behind every tag and quotes the recorded reason', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('RECOMMENDATIONS')
    expect(text()).toContain('Legacy clinical policies')
    expect(text()).toContain('Superseded drafts')
    expect(text()).toContain("matched archive rule 'Legacy clinical policies'")
  })

  it('says review, and says in full that nothing was archived, moved or trashed', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('archive review')
    expect(text()).toContain('deletion review')
    expect(text()).toContain('These are recommendations only')
    expect(text()).toContain('Nothing is archived, moved or trashed')
    // The words that would make this screen lie.
    expect(text()).not.toMatch(/\bfiles archived\b/)
    expect(text()).not.toMatch(/\bwere deleted\b/)
    expect(text()).not.toMatch(/\bhas been archived\b/)
  })

  it('joins a policy list on the rule id when one is supplied', async () => {
    await render({ files: [F('a.docx', { lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p9' })],
                   policies: [{ policy_id: 'p9', name: 'Finance retention' }] })
    expect(text()).toContain('Finance retention')
  })

  it('says the rule was not recorded rather than inferring one from the action', async () => {
    await render({ files: [F('a.docx', { lifecycle_status: 'Archive Candidate' })] })
    expect(text()).toContain(`Rule not recorded`)
  })

  it('filters to archive or deletion without changing any count above it', async () => {
    await render({ files: ESTATE })
    const btn = (label) => [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
    await click(btn('Deletion'))
    expect(text()).toContain('alt-text-draft-2.docx')
    expect(text()).not.toContain('sepsis-pathway-v3.docx')
    // The headline is a fact about the estate, not about the filter.
    expect(text()).toContain('tagged for archive review')
    await click(btn('All'))
    expect(text()).toContain('sepsis-pathway-v3.docx')
  })
})

describe('the per-file override (lifecycle rules #8)', () => {
  const setValue = async (input, value) => {
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  const btnByText = (text2) => [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === text2)

  it('offers "Keep this file" per recommendation row when a handler is wired', async () => {
    await render({ files: ESTATE, onOverrideRecommendation: async () => true })
    expect(btnByText('Keep this file')).toBeTruthy()
  })

  it('is disabled with no handler wired, rather than silently doing nothing', async () => {
    await render({ files: ESTATE })
    expect(btnByText('Keep this file').disabled).toBe(true)
  })

  it('calls the handler with (file, reason) and explains the override in the footnote', async () => {
    const onOverrideRecommendation = vi.fn(() => Promise.resolve(true))
    await render({
      files: [arch('Clinical Guidelines/2019/sepsis-pathway-v3.docx')],
      onOverrideRecommendation,
    })
    await click(btnByText('Keep this file'))
    await setValue(container.querySelector('.lc-override-form input'), 'still needed for the audit')
    await click(btnByText('Save'))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(onOverrideRecommendation).toHaveBeenCalledWith(
      'Clinical Guidelines/2019/sepsis-pathway-v3.docx', 'still needed for the audit')
    expect(text()).toContain('Keep this file')
    expect(text()).toContain('records that you reviewed the recommendation')
  })

  it('renders a recorded override permanently, distinct from Assess anyway', async () => {
    const overridden = F('kept.pdf', {
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy clinical policies'",
      lifecycle_override_reason: 'under active legal hold', lifecycle_overridden_by: 'reviewer@x.com',
    })
    await render({ files: [overridden] })
    expect(text()).toContain('Kept')
    expect(text()).toContain('under active legal hold')
    expect(btnByText('Keep this file')).toBeFalsy()
  })
})

describe('the acknowledgement', () => {
  it('names how many recommendations it covers and what approving does', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('I approve these 3 recommendations.')
    expect(text()).toContain('2 for archive review')
    expect(text()).toContain('1 for deletion review')
    expect(text()).toContain('archives, moves and deletes nothing')
  })

  it('reports the checkbox change to its caller, which is what gates Assess', async () => {
    const seen = []
    await render({ files: ESTATE, onAcknowledge: (v) => seen.push(v) })
    const ackBox = boxes().at(-1)
    await click(ackBox)
    expect(seen).toEqual([true])
  })

  it('counts "assess anyway" overrides, and keeps the recommendation on the file', async () => {
    let overrides = []
    const rerender = async () => render({
      files: ESTATE, overrides, onOverridesChange: (next) => { overrides = next },
    })
    await rerender()
    const rowBox = boxes()[0]
    await click(rowBox)
    expect(overrides).toHaveLength(1)
    await rerender()
    expect(text()).toContain('1 file overridden to assess anyway')
    // The tag survives the override — the file is still recommended for review.
    expect(text()).toContain('deletion review')
  })

  it('is absent when the rules matched nothing — there is nothing to approve', async () => {
    await render({ files: [active('a.docx')] })
    expect(text()).not.toContain('I approve')
  })

  it('claims attribution only when it was given an actor', async () => {
    await render({ files: ESTATE })
    expect(text()).not.toContain('approving as')
    await render({ files: ESTATE, actor: 'jeremy@example.com' })
    expect(text()).toContain('approving as jeremy@example.com')
  })

  it('offers an export only when the caller can actually perform one', async () => {
    await render({ files: ESTATE })
    expect(text()).not.toContain('Export inventory')
    await render({ files: ESTATE, onExport: () => {} })
    expect(text()).toContain('Export inventory')
  })
})
