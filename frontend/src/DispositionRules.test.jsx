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
const deleteDispositionPolicy = vi.fn()
vi.mock('./api.js', () => ({
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
  createDispositionPolicy: (...a) => createDispositionPolicy(...a),
  setDispositionPolicyEnabled: (...a) => setDispositionPolicyEnabled(...a),
  previewDispositionPolicy: (...a) => previewDispositionPolicy(...a),
  deleteDispositionPolicy: (...a) => deleteDispositionPolicy(...a),
}))

const { default: DispositionRules } = await import('./DispositionRules.jsx')

afterEach(unmountAll)
let container, root
beforeEach(() => {
  listDispositionPolicies.mockReset().mockResolvedValue([])
  createDispositionPolicy.mockReset().mockResolvedValue({ policy_id: 'new1' })
  setDispositionPolicyEnabled.mockReset().mockResolvedValue({})
  previewDispositionPolicy.mockReset().mockResolvedValue({ would_match: 0 })
  deleteDispositionPolicy.mockReset().mockResolvedValue({ deleted: 'p1' })
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
    expect(text()).toContain('Disabled — tags nothing yet')
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

  it('disables a rule with no confirmation and no preview', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[0]])   // RULES[0] is enabled
    await render(); await expand(); await flush()
    const confirmSpy = vi.spyOn(window, 'confirm')
    await click(byLabel('Enable rule Legacy clinical policies')); await flush()
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(previewDispositionPolicy).not.toHaveBeenCalled()
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p1', false)
    confirmSpy.mockRestore()
  })

  it('previews before enabling, names the count and percentage in the confirm, and only enables on accept', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])   // RULES[1] is disabled, action=delete
    previewDispositionPolicy.mockResolvedValue({ would_match: 41, total: 205 })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await render(); await expand(); await flush()

    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(previewDispositionPolicy).toHaveBeenCalledWith('p2')
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('41 files (20% of your estate)'))
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('tagged for deletion review'))
    expect(setDispositionPolicyEnabled).not.toHaveBeenCalled()   // declined

    confirmSpy.mockReturnValue(true)
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p2', true)
    confirmSpy.mockRestore()
  })

  it('adds a broad-rule warning past the stated threshold, and omits it below it', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    previewDispositionPolicy.mockResolvedValue({ would_match: 60, total: 100 })   // 60% — broad
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('check the conditions are as narrow'))

    confirmSpy.mockClear()
    previewDispositionPolicy.mockResolvedValue({ would_match: 10, total: 100 })   // 10% — not broad
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalledWith(expect.not.stringContaining('check the conditions are as narrow'))
    confirmSpy.mockRestore()
  })

  it('still offers to enable when the preview itself fails, naming the failure instead of the count', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    previewDispositionPolicy.mockRejectedValue(new Error('network error'))
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('Could not check how many files'))
    expect(setDispositionPolicyEnabled).toHaveBeenCalledWith('p2', true)
    confirmSpy.mockRestore()
  })

  it('surfaces a refusal on the rule it happened to, after confirming', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    previewDispositionPolicy.mockResolvedValue({ would_match: 3, total: 10 })
    setDispositionPolicyEnabled.mockRejectedValue(new Error('403: admin required'))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await render(); await expand(); await flush()
    await click(byLabel('Enable rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('Only a platform admin')
    window.confirm.mockRestore()
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
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalled()
    expect(deleteDispositionPolicy).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(deleteDispositionPolicy).toHaveBeenCalledWith('p2')
    confirmSpy.mockRestore()
  })

  it('surfaces the history guard when deleting a rule that has already run', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteDispositionPolicy.mockRejectedValue(new Error("409: this rule has already run"))
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
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
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalled()
    expect(deleteDispositionPolicy).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(deleteDispositionPolicy).toHaveBeenCalledWith('p2')
    confirmSpy.mockRestore()
  })

  it('surfaces the history guard when deleting a rule that has already run', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteDispositionPolicy.mockRejectedValue(new Error("409: this rule has already run"))
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
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
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(confirmSpy).toHaveBeenCalled()
    expect(deleteDispositionPolicy).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    expect(deleteDispositionPolicy).toHaveBeenCalledWith('p2')
    confirmSpy.mockRestore()
  })

  it('surfaces the history guard when deleting a rule that has already run', async () => {
    listDispositionPolicies.mockResolvedValue([RULES[1]])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteDispositionPolicy.mockRejectedValue(new Error("409: this rule has already run"))
    await render(); await expand(); await flush()
    await click(byLabel('Delete rule Superseded drafts')); await flush()
    const alert = container.querySelector('.lifecycle-rule [role="alert"]')
    expect(alert.textContent).toContain('already run')
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
    expect(text()).toContain('A file matching both an archive and a deletion rule keeps the')
    expect(text()).toContain('recommendation')
    expect(text()).toContain('The safer outcome is never chosen silently.')
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
