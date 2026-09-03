/**
 * Discover step 2 — "Lifecycle rules" (design board DiscoverRules.dc.html), driven through the DOM.
 *
 * The behaviour lane. Its companion, lifecycleRules.test.js, asserts the exact wording and the
 * payload shaping at source level, because a DOM query cannot tell "will be tagged for archive
 * review" from "will be archived" — both are just text nodes. What is checked HERE is what only a
 * mounted component can show: that the rule the person typed is the rule that reaches the API,
 * that a pending list never renders as an empty one, that a server refusal appears next to the
 * control that caused it, and that a rule is created disabled and previewed before it is enabled.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const listDispositionPolicies = vi.fn()
const createDispositionPolicy = vi.fn()
const setDispositionPolicyEnabled = vi.fn()
const previewDispositionPolicy = vi.fn()
const updateDispositionPolicy = vi.fn()
const previewDispositionDraft = vi.fn()
const deleteDispositionPolicy = vi.fn()
const reorderDispositionPolicies = vi.fn()
const listDispositionConflicts = vi.fn()
vi.mock('./api.js', () => ({
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
  createDispositionPolicy: (...a) => createDispositionPolicy(...a),
  setDispositionPolicyEnabled: (...a) => setDispositionPolicyEnabled(...a),
  previewDispositionPolicy: (...a) => previewDispositionPolicy(...a),
  updateDispositionPolicy: (...a) => updateDispositionPolicy(...a),
  previewDispositionDraft: (...a) => previewDispositionDraft(...a),
  deleteDispositionPolicy: (...a) => deleteDispositionPolicy(...a),
  reorderDispositionPolicies: (...a) => reorderDispositionPolicies(...a),
  listDispositionConflicts: (...a) => listDispositionConflicts(...a),
}))

const confirmMock = vi.fn()
const notifyMock = vi.fn()
vi.mock('./ConfirmDialog.jsx', () => ({
  confirm: (...a) => confirmMock(...a),
  notify: (...a) => notifyMock(...a),
  default: () => null,
}))

const { default: DispositionRules } = await import('./DispositionRules.jsx')

afterEach(unmountAll)
let container, root
beforeEach(() => {
  confirmMock.mockReset().mockResolvedValue(false)
  notifyMock.mockReset()
  listDispositionPolicies.mockReset().mockResolvedValue([])
  createDispositionPolicy.mockReset().mockResolvedValue({ policy_id: 'new1' })
  setDispositionPolicyEnabled.mockReset().mockResolvedValue({})
  previewDispositionPolicy.mockReset().mockResolvedValue({ would_match: 0 })
  updateDispositionPolicy.mockReset().mockResolvedValue({})
  previewDispositionDraft.mockReset().mockResolvedValue({ would_match: 0 })
  deleteDispositionPolicy.mockReset().mockResolvedValue({ deleted: 'p1' })
  reorderDispositionPolicies.mockReset().mockResolvedValue([])
  listDispositionConflicts.mockReset().mockResolvedValue({ conflicts: [] })
  ;({ container, root } = createTestRoot())
})

const render = async () => { await act(async () => { root.render(createElement(DispositionRules)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const byLabel = (label) => container.querySelector(`[aria-label="${label}"]`)
const setValue = async (el, val) => {
  const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  await act(async () => { setter.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) })
}
const expand = async () => { await click(btnByText('Lifecycle rules')) }
const flush = async () => { await act(async () => {}) }
const text = () => container.textContent

const RULES = [
  { policy_id: 'p1', name: 'Legacy clinical policies', action: 'archive', enabled: 1,
    match: JSON.stringify([{ field: 'parent_folder', op: 'prefix', value: 'Clinical Guidelines/' },
                           { field: 'modified_at', op: 'before', value: '2021-01-01' }]) },
  { policy_id: 'p2', name: 'Superseded drafts', action: 'delete', enabled: 0,
    match: JSON.stringify([{ field: 'parent_folder', op: 'prefix', value: 'Accessibility Program/_superseded/' },
                           { field: 'modified_at', op: 'before', value: '2023-01-01' }]) },
  { policy_id: 'p3', name: 'Tag legacy', action: 'tag', enabled: 1, match: '[]' },
]

describe('the existing rules list', () => {
  it('keeps the creation form collapsed when rules already exist', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    await render(); await expand(); await flush()
    expect(byLabel('Rule name')).toBeNull()
    expect(btnByText('Create rule').getAttribute('aria-expanded')).toBe('false')
    await click(btnByText('Create rule'))
    expect(byLabel('Rule name')).not.toBeNull()
    expect(btnByText('Close form').getAttribute('aria-expanded')).toBe('true')
  })

  it('loads only when opened, and shows only the two lifecycle actions', async () => {
    listDispositionPolicies.mockResolvedValue(RULES)
    await render()
    expect(listDispositionPolicies).not.toHaveBeenCalled()   // nothing fetched while collapsed
    await expand(); await flush()
    expect(text()).toContain('Legacy clinical policies')
    expect(text()).toContain('Superseded drafts')
    expect(text()).not.toContain('Tag legacy')               // a 'tag' policy is not a lifecycle rule
    expect(text()).toContain('recommend archive')
    expect(text()).toContain('recommend deletion')
  })

  it('restates each rule in the reader\'s words, with the scanned parts in bold', async () => {
    listDispositionPolicies.mockResolvedValue(RULES)
    await render(); await expand(); await flush()
    const sentences = [...container.querySelectorAll('.lifecycle-rule .lifecycle-sentence')]
    expect(sentences[0].textContent).toContain(
      'Files under Clinical Guidelines/ last modified before 1 Jan 2021 will be tagged for archive review.')
    expect(sentences[1].textContent).toContain(
      'Files under Accessibility Program/_superseded/ last modified before 1 Jan 2023 '
      + 'will be tagged for deletion review.')
    expect([...sentences[0].querySelectorAll('b')].map((b) => b.textContent))
      .toEqual(['Clinical Guidelines/', '1 Jan 2021', 'tagged for archive review'])
  })

  it('says which rules are live, and marks a disabled one as tagging nothing', async () => {
    listDispositionPolicies.mockResolvedValue(RULES)
    await render(); await expand(); await flush()
    expect(text()).toContain('1 of 2 rules enabled')
    expect(text()).toContain('Off')
  })

  // Product rule 3. A pending answer and an empty answer are different facts.
  it('renders NOTHING for the list while it is still loading — no empty state, no count', async () => {
    let resolve
    listDispositionPolicies.mockReturnValue(new Promise((r) => { resolve = r }))
    await render(); await expand(); await flush()
    expect(text()).not.toContain('No lifecycle rules yet')
    expect(text()).not.toMatch(/\d+ of \d+ rules? enabled/)
    expect(container.querySelectorAll('.lifecycle-rule')).toHaveLength(0)
    await act(async () => { resolve([]) }); await flush()
    expect(text()).toContain('No lifecycle rules yet')       // only once the answer is in
    expect(text()).toContain('0 of 0 rules enabled')
  })

  it('shows a match count only after the count has been asked for', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({ would_match: 310 })
    await render(); await expand(); await flush()
    expect(text()).toContain('Preview to see how many files match.')
    expect(text()).not.toMatch(/Matches about/)
    await click(btnByText('Preview matches')); await flush()
    expect(previewDispositionPolicy).toHaveBeenCalledWith('p1')
    expect(text()).toContain('Matches about 310 files.')
  })

  it('leaves the count unasked when the preview response carries no number', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({})           // no would_match at all
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('Preview to see how many files match.')
    expect(text()).not.toContain('Matches none of the files')  // never a manufactured zero
  })

  // Suppressed-matches breakdown — the PreviewPanel explains how raw matches split into
  // effective (will receive the action), superseded (another rule wins), and unable-to-evaluate
  // (missing metadata prevented the match). Only shown when there's something worth explaining.

  it('shows no breakdown row when everything is effective', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 2, documents: [{doc_id:'d1',path:'/a'},{doc_id:'d2',path:'/b'}],
      effective: 2, superseded: 0, exempted: 0, unable_to_evaluate: 0,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).not.toContain('will receive the action')
    expect(text()).not.toContain('overridden by another rule')
    expect(text()).not.toContain("couldn't be evaluated")
  })

  it('shows breakdown when some matches are superseded by another rule', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 5, documents: Array.from({length:5},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 3, superseded: 2, exempted: 0, unable_to_evaluate: 0,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('3')
    expect(text()).toContain('will receive the action')
    expect(text()).toContain('2')
    expect(text()).toContain('overridden by another rule')
  })

  it('shows exempted count in the breakdown when > 0', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 4, documents: Array.from({length:4},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 3, superseded: 0, exempted: 1, unable_to_evaluate: 0,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('legal hold')
  })

  it('shows exempted file names in the exempted note', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 3, documents: Array.from({length:3},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 3, superseded: 0, exempted: 2, unable_to_evaluate: 0,
      exempted_documents: [
        { doc_id: 'h1', path: 'Finance/2019/contract.docx' },
        { doc_id: 'h2', path: 'Finance/2019/nda.pdf' },
      ],
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('legal hold')
    expect(text()).toContain('contract.docx')
    expect(text()).toContain('nda.pdf')
  })

  it('shows overflow count when more than 3 files are exempted', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    const exemptedDocs = Array.from({length: 5}, (_, i) => ({
      doc_id: `h${i}`, path: `Finance/hold${i}.docx`,
    }))
    previewDispositionPolicy.mockResolvedValue({
      would_match: 2, documents: [],
      effective: 2, superseded: 0, exempted: 5, unable_to_evaluate: 0,
      exempted_documents: exemptedDocs,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    // Shows the first 3 names and "+ 2 more"
    expect(text()).toContain('hold0.docx')
    expect(text()).toContain('hold1.docx')
    expect(text()).toContain('hold2.docx')
    expect(text()).toContain('2 more')
    expect(text()).not.toContain('hold3.docx')
  })

  it('falls back to generic message when exempted_documents is absent (old server)', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 4, documents: Array.from({length:4},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 3, superseded: 0, exempted: 1, unable_to_evaluate: 0,
      // no exempted_documents key — old server
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('legal hold')
    expect(text()).toContain("won't be tagged")
  })

  it("shows unable-to-evaluate note when some files couldn't be assessed", async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 10, documents: Array.from({length:10},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 10, superseded: 0, exempted: 0, unable_to_evaluate: 3,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('3')
    expect(text()).toContain("couldn't be evaluated")
    expect(text()).toContain('metadata')
  })

  it('shows the missing field names in the unable-to-evaluate note', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 8, documents: Array.from({length:8},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 8, superseded: 0, exempted: 0, unable_to_evaluate: 3,
      unable_to_evaluate_fields: { department: 2, size_kb: 1 },
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain("couldn't be evaluated")
    expect(text()).toContain('Department')
    expect(text()).toContain('Larger than')
  })

  it('omits per-field counts when only one file is unable to evaluate', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 5, documents: Array.from({length:5},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 5, superseded: 0, exempted: 0, unable_to_evaluate: 1,
      unable_to_evaluate_fields: { department: 1 },
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain('Department')
    // No "(1)" when only one file — redundant next to the headline count
    expect(text()).not.toMatch(/Department\s*\(1\)/)
  })

  it('falls back to generic message when unable_to_evaluate_fields is absent (old server)', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({
      would_match: 5, documents: Array.from({length:5},(_,i)=>({doc_id:`d${i}`,path:`/p${i}`})),
      effective: 5, superseded: 0, exempted: 0, unable_to_evaluate: 2,
    })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).toContain("couldn't be evaluated")
    expect(text()).toContain("wasn't recorded")
  })

  it('shows no breakdown when the response lacks breakdown fields (old server)', async () => {
    // Older server responses without the breakdown fields must not render broken UI.
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    previewDispositionPolicy.mockResolvedValue({ would_match: 5, documents: [] })
    await render(); await expand(); await flush()
    await click(btnByText('Preview matches')); await flush()
    expect(text()).not.toContain('will receive the action')
    expect(text()).not.toContain("couldn't be evaluated")
  })

  it('confirms before disabling, warns about persisted tags, and only disables on accept', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])   // RULES[0] is enabled
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Legacy clinical policies')); await flush()
    expect(previewDispositionPolicy).not.toHaveBeenCalled()
    expect(confirmMock).toHaveBeenCalled()
    expect(confirmMock.mock.calls.at(-1)[0].message).toContain('keep their lifecycle status')
    expect(setDispositionPolicyEnabled).not.toHaveBeenCalled()   // declined by default

    confirmMock.mockResolvedValue(true)
    await click(byLabel('Enable rule Legacy clinical policies')); await flush()
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p1', false)
  })

  it('previews before enabling, names the count and percentage in the confirm, and only enables on accept', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])   // RULES[1] is disabled, action=delete
    previewDispositionPolicy.mockResolvedValue({ would_match: 41, total: 205 })
    await render(); await expand(); await flush()

    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(previewDispositionPolicy).toHaveBeenCalledWith('p2')
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      presentation: 'toast',
      message: expect.stringContaining('never moves, archives, or deletes source files'),
      facts: expect.arrayContaining([
        expect.objectContaining({ label: 'Files currently in scope', value: '41 files · 20% of discovered files' }),
        expect.objectContaining({ label: 'Recommendation', value: 'tagged for deletion review' }),
        expect.objectContaining({ label: 'Starts', value: 'Next Discovery run' }),
      ])
    }))
    expect(setDispositionPolicyEnabled).not.toHaveBeenCalled()   // declined

    confirmMock.mockResolvedValue(true)
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    // The count the dialog just showed is sent with the activation: the server re-derives it and
    // refuses if the estate moved in between (PRD §7.5). Previously the number was displayed to a
    // person and then thrown away, so nothing checked that what they agreed to still held.
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p2', true, 41)
    expect(notifyMock).toHaveBeenCalledWith(expect.objectContaining({
      title: expect.stringContaining('enabled'), actionLabel: 'Undo',
    }))

    await act(async () => { await notifyMock.mock.calls.at(-1)[0].onAction() }); await flush()
    expect(setDispositionPolicyEnabled).toHaveBeenLastCalledWith('p2', false)
  })

  it('shows that impact is being checked while the enable preview is pending', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    let settle
    previewDispositionPolicy.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts'))
    expect(text()).toContain('Checking impact…')
    await act(async () => settle({ would_match: 0, total: 10 })); await flush()
    expect(text()).not.toContain('Checking impact…')
  })

  it('adds a broad-rule warning past the stated threshold, and omits it below it', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    confirmMock.mockResolvedValue(true)

    previewDispositionPolicy.mockResolvedValue({ would_match: 60, total: 100 })   // 60% — broad
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ warning: expect.stringContaining('check the conditions are as narrow') }))

    confirmMock.mockClear()
    previewDispositionPolicy.mockResolvedValue({ would_match: 10, total: 100 })   // 10% — not broad
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ warning: undefined }))
  })

  it('still offers to enable when the preview itself fails, naming the failure instead of the count', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    previewDispositionPolicy.mockRejectedValue(new Error('network error'))
    confirmMock.mockResolvedValue(true)
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      presentation: 'toast',
      message: expect.stringContaining('current impact could not be measured'),
    }))
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p2', true)
  })

  it('surfaces a refusal on the rule it happened to, after confirming', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    previewDispositionPolicy.mockResolvedValue({ would_match: 3, total: 10 })
    setDispositionPolicyEnabled.mockRejectedValue(new Error('403: admin required'))
    confirmMock.mockResolvedValue(true)
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('Only a platform admin')
  })

  it('duplicates a rule with the same match/action, a distinguishing name, and no id of its own', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    await render(); await expand(); await flush()
    await click(btnByText('Duplicate')); await flush()
    expect(createDispositionPolicy).toHaveBeenCalledWith(
      'Legacy clinical policies (copy)', JSON.parse(RULES[0].match), 'archive', {}, false)
    // The duplicate is previewed like any freshly created rule — not executed, not enabled.
    expect(previewDispositionPolicy).toHaveBeenCalledWith('new1')
  })

  it('confirms before deleting, and only deletes on confirmation', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(confirmMock).toHaveBeenCalled()
    expect(deleteDispositionPolicy).not.toHaveBeenCalled()

    confirmMock.mockResolvedValue(true)
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(deleteDispositionPolicy).toHaveBeenCalledWith('p2')
  })

  it('surfaces the history guard when deleting a rule that has already run', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    confirmMock.mockResolvedValue(true)
    deleteDispositionPolicy.mockRejectedValue(new Error("409: this rule has already run"))
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
  })

  it('moving a rule down sends the whole new order, not just the one that moved', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])   // p1 then p2
    await render(); await expand(); await flush()
    await click(byLabel('Move rule Legacy clinical policies down')); await flush()
    expect(reorderDispositionPolicies).toHaveBeenCalledWith(['p2', 'p1'])
  })

  it('moving up is the mirror of moving down', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])
    await render(); await expand(); await flush()
    await click(byLabel('Move rule Superseded drafts up')); await flush()
    expect(reorderDispositionPolicies).toHaveBeenCalledWith(['p2', 'p1'])
  })

  it('disables moving the first rule up and the last rule down', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])
    await render(); await expand(); await flush()
    expect(byLabel('Move rule Legacy clinical policies up').disabled).toBe(true)
    expect(byLabel('Move rule Superseded drafts down').disabled).toBe(true)
    expect(byLabel('Move rule Legacy clinical policies down').disabled).toBe(false)
    expect(byLabel('Move rule Superseded drafts up').disabled).toBe(false)
  })

  it('shows no conflict-check control at all with 0 or 1 rules', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    await render(); await expand(); await flush()
    expect(btnByText('Check for rule conflicts')).toBeUndefined()
  })

  it('checks for conflicts on demand and reports none found', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])
    await render(); await expand(); await flush()
    expect(listDispositionConflicts).not.toHaveBeenCalled()   // not fetched automatically
    await click(btnByText('Check for rule conflicts')); await flush()
    expect(listDispositionConflicts).toHaveBeenCalled()
    expect(text()).toContain('No file matches more than one enabled rule.')
  })

  it('reports a real conflict with both matched rules, the winner and why', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])
    listDispositionConflicts.mockResolvedValue({
      conflicts: [{
        doc_id: 'd1', path: 'Finance/2019/ledger.docx',
        matched_rules: [{ policy_id: 'p1', name: 'Legacy clinical policies', action: 'archive' },
                       { policy_id: 'p2', name: 'Superseded drafts', action: 'delete' }],
        winner: { policy_id: 'p1', name: 'Legacy clinical policies' },
        outcome: 'Archive Candidate',
        reason: "matched archive rule 'Legacy clinical policies' — flagged for review",
      }],
    })
    await render(); await expand(); await flush()
    await click(btnByText('Check for rule conflicts')); await flush()
    expect(text()).toContain('Finance/2019/ledger.docx')
    expect(text()).toContain('Legacy clinical policies')
    expect(text()).toContain('Superseded drafts')
    expect(text()).toContain('flagged for review')
  })

  it('surfaces a refusal from the conflicts check inline', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0], RULES[1]])
    listDispositionConflicts.mockRejectedValue(new Error('500: internal error'))
    await render(); await expand(); await flush()
    await click(btnByText('Check for rule conflicts')); await flush()
    expect(text()).toContain('500: internal error')
  })

  it('duplicates a rule with the same match/action, a distinguishing name, and no id of its own', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    await render(); await expand(); await flush()
    await click(btnByText('Duplicate')); await flush()
    expect(createDispositionPolicy).toHaveBeenCalledWith(
      'Legacy clinical policies (copy)', JSON.parse(RULES[0].match), 'archive', {}, false)
    // The duplicate is previewed like any freshly created rule — not executed, not enabled.
    expect(previewDispositionPolicy).toHaveBeenCalledWith('new1')
  })

  it('confirms before deleting, and only deletes on confirmation', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(confirmMock).toHaveBeenCalled()
    expect(deleteDispositionPolicy).not.toHaveBeenCalled()

    confirmMock.mockResolvedValue(true)
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(deleteDispositionPolicy).toHaveBeenCalledWith('p2')
  })

  it('surfaces the history guard when deleting a rule that has already run', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    confirmMock.mockResolvedValue(true)
    deleteDispositionPolicy.mockRejectedValue(new Error("409: this rule has already run"))
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
  })
})

// Lifecycle rules #2 — editing a SAVED rule in place, distinct from the new-rule builder below
// (which only ever creates). Reuses draftProblem's validation and RuleFields' layout, so this
// covers the wiring — pre-fill, save, cancel, the 409 refusal, the enabled-rule confirmation —
// not the field-by-field parsing, already pinned in lifecycleRules.test.js.
describe('editing a saved rule', () => {
  it('pre-fills the edit form from the rule\'s own name, action and conditions', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Legacy clinical policies'))
    expect(byLabel('Rule name (editing Legacy clinical policies)').value).toBe('Legacy clinical policies')
    expect(byLabel('Action (editing Legacy clinical policies)').value).toBe('archive')
    expect(byLabel('Folder path starts with (editing Legacy clinical policies)').value).toBe('Clinical Guidelines/')
    expect(byLabel('Last modified before (editing Legacy clinical policies)').value).toBe('2021-01-01')
  })

  it('saves the edited name/action/conditions and reloads the list', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])   // disabled — no enable-confirmation in the way
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Superseded drafts'))
    await setValue(byLabel('Rule name (editing Superseded drafts)'), 'Superseded drafts (renamed)')
    await setValue(byLabel('Folder path starts with (editing Superseded drafts)'), 'Accessibility Program/_old/')
    await click(byLabel('Save changes to Superseded drafts')); await flush()
    expect(updateDispositionPolicy).toHaveBeenCalledWith('p2', {
      name: 'Superseded drafts (renamed)', action: 'delete',
      match: [{ field: 'parent_folder', op: 'prefix', value: 'Accessibility Program/_old/' },
             { field: 'modified_at', op: 'before', value: '2023-01-01' }],
    })
    expect(listDispositionPolicies).toHaveBeenCalledTimes(2)   // the list reloads on success
    expect(byLabel('Edit rule Superseded drafts')).toBeTruthy()  // back to view mode
  })

  it('cancel discards the in-progress edit without saving', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Superseded drafts'))
    await setValue(byLabel('Rule name (editing Superseded drafts)'), 'discarded name')
    await click(byLabel('Cancel editing Superseded drafts')); await flush()
    expect(updateDispositionPolicy).not.toHaveBeenCalled()
    expect(text()).toContain('Superseded drafts')          // the ORIGINAL name, still shown
    expect(text()).not.toContain('discarded name')
  })

  it('refuses to save with no conditions, the same rule the create form enforces', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Superseded drafts'))
    await setValue(byLabel('Folder path starts with (editing Superseded drafts)'), '')
    await setValue(byLabel('Last modified before (editing Superseded drafts)'), '')
    await click(byLabel('Save changes to Superseded drafts')); await flush()
    expect(updateDispositionPolicy).not.toHaveBeenCalled()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('a rule with none would match every file in scope')
  })

  it('confirms before saving an edit to a rule that is currently enabled, warning about persisted tags', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])   // enabled: 1
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Legacy clinical policies'))
    await click(byLabel('Save changes to Legacy clinical policies')); await flush()
    expect(confirmMock).toHaveBeenCalled()
    expect(confirmMock.mock.calls.at(-1)[0].message).toContain('enabled')
    expect(confirmMock.mock.calls.at(-1)[0].message).toContain('old conditions keep their status')
    expect(updateDispositionPolicy).not.toHaveBeenCalled()   // declined — nothing sent

    confirmMock.mockResolvedValue(true)
    await click(byLabel('Save changes to Legacy clinical policies')); await flush()
    expect(updateDispositionPolicy).toHaveBeenCalled()
  })

  it('surfaces the history-change refusal (409) inline, same as every other write on this screen', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    updateDispositionPolicy.mockRejectedValue(
      new Error("409: this rule has already run — its match can no longer be changed"))
    await render(); await expand(); await flush()
    await click(byLabel('Edit rule Superseded drafts'))
    await setValue(byLabel('Folder path starts with (editing Superseded drafts)'), 'Accessibility Program/_old/')
    await click(byLabel('Save changes to Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
    expect(byLabel('Rule name (editing Superseded drafts)')).toBeTruthy()   // edit form stays open
  })
})

describe('the new-rule builder', () => {
  const fillBoardExample = async () => {
    await setValue(byLabel('Rule name'), 'Finance retention')
    await setValue(byLabel('Folder path starts with'), 'Finance/2019/')
    await setValue(byLabel('Last modified before'), '2022-01-01')
  }

  it('restates the draft in plain language as it is typed, before anything is saved', async () => {
    await render(); await expand(); await flush()
    await fillBoardExample()
    const draft = container.querySelector('.lifecycle-new .lifecycle-sentence')
    expect(draft.textContent).toContain(
      'Files under Finance/2019/ last modified before 1 Jan 2022 will be tagged for archive review.')
    expect(createDispositionPolicy).not.toHaveBeenCalled()   // a restatement, not a save
  })

  // Lifecycle rules #4 — a live preview of the DRAFT before it is saved, not only after
  // (previewDispositionPolicy needs a saved policy_id). Debounced, so these wait past the window.
  it('shows a live match count for the draft, before it is saved', async () => {
    previewDispositionDraft.mockResolvedValue({ would_match: 40 })
    await render(); await expand(); await flush()
    await fillBoardExample()
    expect(text()).toContain('Checking how many files match…')
    await act(async () => { await new Promise((r) => setTimeout(r, 500)) })
    expect(previewDispositionDraft).toHaveBeenCalledWith(
      [{ field: 'parent_folder', op: 'prefix', value: 'Finance/2019/' },
       { field: 'modified_at', op: 'before', value: '2022-01-01' }], 'archive')
    expect(text()).toContain('Matches about 40 files.')
    expect(createDispositionPolicy).not.toHaveBeenCalled()   // still just a preview
  })

  it('does not ask for a preview until at least one condition is valid', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'Everything')
    await act(async () => { await new Promise((r) => setTimeout(r, 500)) })
    expect(previewDispositionDraft).not.toHaveBeenCalled()
  })

  it('previews before the rule has a name — a name has no bearing on which files match', async () => {
    previewDispositionDraft.mockResolvedValue({ would_match: 7 })
    await render(); await expand(); await flush()
    await setValue(byLabel('Folder path starts with'), 'HR/')   // no name yet
    await act(async () => { await new Promise((r) => setTimeout(r, 500)) })
    expect(previewDispositionDraft).toHaveBeenCalled()
    expect(text()).toContain('Matches about 7 files.')
    expect(btnByText('Add rule').disabled).toBe(true)          // still can't submit — no name
  })

  it('debounces rapid edits into the last value typed, not one request per keystroke', async () => {
    previewDispositionDraft.mockResolvedValue({ would_match: 1 })
    await render(); await expand(); await flush()
    const folder = byLabel('Folder path starts with')
    await setValue(folder, 'F')
    await setValue(folder, 'Fi')
    await setValue(folder, 'Fin')
    await setValue(folder, 'Finance/')
    await act(async () => { await new Promise((r) => setTimeout(r, 500)) })
    expect(previewDispositionDraft).toHaveBeenCalledTimes(1)
    expect(previewDispositionDraft).toHaveBeenCalledWith(
      [{ field: 'parent_folder', op: 'prefix', value: 'Finance/' }], 'archive')
  })

  it('surfaces a preview failure without blocking Add rule', async () => {
    previewDispositionDraft.mockRejectedValue(new Error('network error'))
    await render(); await expand(); await flush()
    await fillBoardExample()
    await act(async () => { await new Promise((r) => setTimeout(r, 500)) })
    expect(text()).toContain('Could not check how many files this would match')
    expect(btnByText('Add rule').disabled).toBe(false)
  })

  it('sends exactly the conditions that were filled in, coercing days to a number', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'Stale HR')
    await setValue(byLabel('Folder path starts with'), 'HR/')
    await setValue(byLabel('Not modified in the last'), '1095')
    await setValue(byLabel('Action'), 'delete')
    await click(btnByText('Add rule')); await flush()
    expect(createDispositionPolicy).toHaveBeenCalledWith('Stale HR', [
      { field: 'parent_folder', op: 'prefix', value: 'HR/' },
      { field: 'modified_age_days', op: 'gt', value: 1095 },
    ], 'delete')
  })

  // Product rule 2, and the deliverable's "preview of what a rule WOULD match before it is enabled".
  it('adds the rule disabled, says so, and previews it without enabling it', async () => {
    createDispositionPolicy.mockResolvedValue({ policy_id: 'new1', enabled: 0 })
    previewDispositionPolicy.mockResolvedValue({ would_match: 42 })
    await render(); await expand(); await flush()
    await fillBoardExample()
    expect(text()).toContain('Added disabled — it tags nothing until you enable it.')
    await click(btnByText('Add rule')); await flush()
    expect(createDispositionPolicy).toHaveBeenCalled()
    expect(listDispositionPolicies).toHaveBeenCalledTimes(2)             // the list reloads
    expect(previewDispositionPolicy).toHaveBeenCalledWith('new1')        // counted while disabled
    expect(setDispositionPolicyEnabled).not.toHaveBeenCalled()           // and never enabled for us
    expect(container.querySelector('[role="status"]').textContent)
      .toContain('It is disabled — nothing is tagged until you enable it.')
    expect(byLabel('Rule name').value).toBe('')                          // the form resets
  })

  it('refuses a rule with no conditions rather than tagging the whole estate', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Rule name'), 'Everything')
    expect(btnByText('Add rule').disabled).toBe(true)
    expect(text()).toContain('a rule with none would match every file in scope')
    await click(btnByText('Add rule'))
    expect(createDispositionPolicy).not.toHaveBeenCalled()
  })

  it('will not submit an unnamed rule or a nonsense day count', async () => {
    await render(); await expand(); await flush()
    await setValue(byLabel('Folder path starts with'), 'Finance/')
    expect(btnByText('Add rule').disabled).toBe(true)
    expect(text()).toContain('Give the rule a name.')
    await setValue(byLabel('Rule name'), 'Finance')
    expect(btnByText('Add rule').disabled).toBe(false)
    await setValue(byLabel('Not modified in the last'), 'soon')
    expect(btnByText('Add rule').disabled).toBe(true)
  })

  // Product rule 4 — a non-admin's create is refused server-side; that has to be visible.
  it('surfaces a non-admin refusal inline instead of failing silently', async () => {
    createDispositionPolicy.mockRejectedValue(new Error('403: admin required'))
    await render(); await expand(); await flush()
    await fillBoardExample()
    await click(btnByText('Add rule')); await flush()
    const alert = container.querySelector('.lifecycle-new [role="alert"]')
    expect(alert.textContent).toContain('Only a platform admin')
    expect(alert.textContent).toContain('the rule was not saved')
    expect(alert.textContent).toContain('403: admin required')            // the server's own words
    expect(container.querySelector('[role="status"]')).toBeNull()          // no false success
  })

  // Product rule 2 — the trash semantics belong where the choice is made, not in a footnote.
  it('states the real safety of each action next to the action control', async () => {
    await render(); await expand(); await flush()
    expect(text()).toContain('Nothing is moved')
    await setValue(byLabel('Action'), 'delete')
    expect(text()).toContain('Nothing is trashed or deleted here')
    expect(text()).toContain('Drive trash — recoverable')
    expect(text()).toContain('never a permanent delete')
  })

  it('offers only the two lifecycle actions, worded as recommendations', async () => {
    await render(); await expand(); await flush()
    expect([...byLabel('Action').options].map((o) => [o.value, o.textContent]))
      .toEqual([['archive', 'Recommend archive'], ['delete', 'Recommend deletion']])
  })
})

describe('the safety copy the whole screen rests on', () => {
  // Product rule 1. Every word a person can read on this screen, swept at once — the builder in
  // its delete state, an enabled archive rule and a disabled delete rule all on screen together.
  it('never says a file was archived, deleted, moved or trashed', async () => {
    listDispositionPolicies.mockResolvedValue(RULES)
    await render(); await expand(); await flush()
    await click(btnByText('Create rule'))
    await setValue(byLabel('Action'), 'delete')
    const t = text()
    expect(t).not.toMatch(/\b(?:files?|documents?) (?:was|were|are|is) (?:archived|deleted|trashed|moved|removed)\b/i)
    // The one a rule sentence would trip: "Files under Finance/2019/ … will be deleted."
    expect(t).not.toMatch(/\bwill be (?:archived|deleted|trashed|moved|removed)\b/i)
    expect(t).not.toMatch(/\bhas been (?:archived|deleted|trashed|moved)\b/i)
    expect(t).not.toMatch(/permanently delet/i)
    expect(t).toContain('Nothing is moved, trashed or changed.')
  })

  it('states, before any rule is written, that rules only tag', async () => {
    await render()
    // Visible while still collapsed — the promise is made before the person starts building.
    expect(text()).toContain('Rules run during discovery and')
    expect(text()).toContain('Nothing is moved, trashed or changed.')
  })

  it('explains rule precedence where a conflicting rule would be created', async () => {
    await render(); await expand(); await flush()
    // One assertion per outcome in disposition.resolve_candidate, because the old copy
    // described only the third and asserted it as universal.
    expect(text()).toContain('keeps the')                     // archive is kept ...
    expect(text()).toContain('flags that a deletion rule also matched')
    expect(text()).toContain('Deletion wins only if that rule explicitly permits it')
    expect(text()).toContain('neither')                       // ... equal priority applies neither
    expect(text()).toContain('Conflict — review required')
    // The corrected claim: the DESTRUCTIVE outcome is the one never chosen silently. The old
    // sentence said "safer", which is both false and the more alarming way round.
    expect(text()).toContain('A deletion is never chosen silently.')
    expect(text(), 'the inverted claim is back').not.toContain('The safer outcome is never chosen')
  })

  it('says a file may carry only one recommendation, next to the list it applies to', async () => {
    await render(); await expand(); await flush()
    expect(text()).toContain('Each rule applies one recommendation to the files it matches.')
    expect(text()).toContain('a file may carry only one recommendation')
  })

  it('does not claim a rule count when the list could not be loaded', async () => {
    listDispositionPolicies.mockRejectedValue(new Error('backend down'))
    await render(); await expand(); await flush()
    expect(text()).toContain('backend down')
    expect(text()).not.toMatch(/\d+ of \d+ rules? enabled/)
    expect(text()).not.toContain('No lifecycle rules yet')
  })
})
