/**
 * The mode diagram's job is to answer one question before a person commits to a mode: what will
 * ACP ask me to do? These tests assert the rendered DOM, because every failure this component can
 * have is a rendering failure — a mode missing, a stage missing, an actor readable only as a
 * colour, or a count that nobody supplied appearing as if it were measured.
 */
import { act, createElement } from 'react'
import axe from 'axe-core'
import { afterEach, expect, it } from 'vitest'
import Diagram, { REMEDIATION_MODES, REMEDIATION_STAGES } from './RemediationModeDiagram.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

const mount = async (props = {}) => {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(Diagram, props)) })
  return container
}

const rows = (container) => [...container.querySelectorAll('tbody tr')]
const cells = (container, modeId) =>
  [...container.querySelectorAll(`tr[data-mode="${modeId}"] td`)]
const cell = (container, modeId, stageId) =>
  container.querySelector(`tr[data-mode="${modeId}"] td[data-stage="${stageId}"]`)

it('shows all three modes and every pipeline stage, as a headed table', async () => {
  const container = await mount()
  const table = container.querySelector('table')
  expect(table).not.toBeNull()
  expect(table.querySelector('caption')).not.toBeNull()

  const modeNames = rows(container).map((row) => row.querySelector('th[scope=row]').textContent)
  expect(modeNames).toHaveLength(3)
  for (const label of ['Review every change', 'Apply rule-based fixes', 'Run end to end']) {
    expect(modeNames.some((name) => name.includes(label))).toBe(true)
  }

  const stageHeaders = [...table.querySelectorAll('thead th[scope=col]')]
  // One header per stage, plus the corner cell naming the mode column.
  expect(stageHeaders).toHaveLength(REMEDIATION_STAGES.length + 1)
  for (const stage of REMEDIATION_STAGES) {
    const header = table.querySelector(`thead th[data-stage="${stage.id}"]`)
    expect(header, `no column header for ${stage.id}`).not.toBeNull()
    expect(header.getAttribute('scope')).toBe('col')
    expect(header.textContent).toContain(stage.label)
  }
  for (const label of ['Scan', 'Rule fixes', 'AI draft', 'AI review', 'Write', 'Verify', 'Publish']) {
    expect(table.querySelector('thead').textContent).toContain(label)
  }
  // Every mode is scored against every stage: a rectangular matrix, no silent gaps.
  expect(container.querySelectorAll('tbody td')).toHaveLength(3 * REMEDIATION_STAGES.length)
})

it('names who acts at each stage as text, not colour alone', async () => {
  const container = await mount()
  const all = [...container.querySelectorAll('tbody td')]
  expect(all).toHaveLength(21)
  for (const td of all) {
    const actor = td.querySelector('.rmd__actor')
    expect(actor, `no actor word in ${td.dataset.stage}`).not.toBeNull()
    expect(['ACP', 'You', 'Not used']).toContain(actor.textContent.trim())
    // The word, not the class, has to carry it — assert the visible text of the cell says so.
    expect(td.textContent).toMatch(/ACP|You|Not used/)
  }
  const review = cell(container, 'review-every-change', 'rule-fixes')
  expect(review.textContent).toContain('You')
  expect(review.textContent).toContain('Approve each fix')
  expect(cell(container, 'rule-based-auto', 'rule-fixes').textContent).toContain('ACP')
})

it('marks the active mode with visible text as well as aria-current', async () => {
  const container = await mount({ activeModeId: 'end-to-end' })
  const active = container.querySelector('tr[data-mode="end-to-end"] th[scope=row]')
  expect(active.getAttribute('aria-current')).toBe('true')
  // Text, so the selection survives monochrome, forced colours and a screen reader.
  expect(active.querySelector('.rmd__selected')).not.toBeNull()
  expect(active.textContent).toContain('Your selection')

  const others = rows(container).filter((row) => row.dataset.mode !== 'end-to-end')
  expect(others).toHaveLength(2)
  for (const row of others) {
    const header = row.querySelector('th[scope=row]')
    expect(header.getAttribute('aria-current')).toBeNull()
    expect(header.textContent).not.toContain('Your selection')
  }
})

it('marks no mode active when the caller names none', async () => {
  const container = await mount()
  expect(container.querySelectorAll('[aria-current]')).toHaveLength(0)
  expect(container.textContent).not.toContain('Your selection')
})

it('shows the automated mode asking for no AI approval, publishing aside', async () => {
  const container = await mount({ activeModeId: 'end-to-end' })
  const person = cells(container, 'end-to-end').filter((td) => td.dataset.actor === 'person')
  expect(person.map((td) => td.dataset.stage)).toEqual(['publish'])
  const aiReview = cell(container, 'end-to-end', 'ai-review')
  expect(aiReview.dataset.actor).toBe('acp')
  expect(aiReview.textContent).toContain('ACP')
  expect(aiReview.textContent).not.toContain('You')
  // The other two modes do route AI suggestions to a person — otherwise the contrast is empty.
  for (const mode of ['review-every-change', 'rule-based-auto']) {
    expect(cell(container, mode, 'ai-review').dataset.actor).toBe('person')
  }
})

it('shows publishing as a person step in every mode', async () => {
  const container = await mount()
  for (const mode of REMEDIATION_MODES) {
    const publish = cell(container, mode.id, 'publish')
    expect(publish, `no publish cell for ${mode.id}`).not.toBeNull()
    expect(publish.dataset.actor, `publish is not a person step in ${mode.id}`).toBe('person')
    expect(publish.textContent).toContain('You')
  }
})

it('renders a count only where the caller supplied one', async () => {
  const container = await mount({
    counts: {
      'rule-based-auto': { 'rule-fixes': { auto: 31, approve: 554 } },
      'end-to-end': { 'ai-review': { auto: 1204 } },
    },
  })
  const supplied = cell(container, 'rule-based-auto', 'rule-fixes')
  expect(supplied.querySelector('.rmd__count').textContent).toContain('31 auto')
  expect(supplied.querySelector('.rmd__count').textContent).toContain('554 to approve')

  const oneSided = cell(container, 'end-to-end', 'ai-review')
  expect(oneSided.querySelector('.rmd__count').textContent).toContain('1,204 auto')
  expect(oneSided.textContent).not.toContain('to approve')

  // Exactly the two the caller named — no sibling cell borrows or infers a figure.
  expect(container.querySelectorAll('.rmd__count')).toHaveLength(2)
  expect(cell(container, 'review-every-change', 'rule-fixes').querySelector('.rmd__count')).toBeNull()
  expect(cell(container, 'rule-based-auto', 'publish').querySelector('.rmd__count')).toBeNull()
})

it('renders no count text at all when the caller supplies none', async () => {
  const container = await mount()
  expect(container.querySelectorAll('.rmd__count')).toHaveLength(0)
  // No placeholder, no zero, no invented figure. The only digits the diagram may print unasked
  // are the stage step numbers in the header row, so the body must carry none at all.
  expect(container.querySelector('tbody').textContent).not.toMatch(/\d/)
  expect(container.textContent).not.toMatch(/\d[\d,]*\s*(auto|to approve|approvals?|files?|items?)/i)
  expect(container.textContent).not.toContain('—')
})

it('ignores counts it cannot read rather than printing a placeholder', async () => {
  const container = await mount({
    counts: {
      'rule-based-auto': {
        'rule-fixes': { auto: null, approve: undefined },
        'ai-draft': {},
        write: 'unavailable',
        verify: '   ',
      },
    },
  })
  expect(cell(container, 'rule-based-auto', 'rule-fixes').querySelector('.rmd__count')).toBeNull()
  expect(cell(container, 'rule-based-auto', 'ai-draft').querySelector('.rmd__count')).toBeNull()
  expect(cell(container, 'rule-based-auto', 'verify').querySelector('.rmd__count')).toBeNull()
  // A caller-formatted string is the caller's own words and is passed through verbatim.
  expect(cell(container, 'rule-based-auto', 'write').querySelector('.rmd__count').textContent)
    .toBe('unavailable')
})

it('keeps its decoration out of the accessibility tree and uses no images', async () => {
  const container = await mount({ activeModeId: 'review-every-change' })
  expect(container.querySelectorAll('img')).toHaveLength(0)
  for (const arrow of container.querySelectorAll('.rmd__arrow')) {
    expect(arrow.getAttribute('aria-hidden')).toBe('true')
  }
  // The wide strip is the scroller, and a keyboard user can reach it.
  const scroller = container.querySelector('.rmd__scroll')
  expect(scroller.getAttribute('tabindex')).toBe('0')
  expect(scroller.getAttribute('role')).toBe('region')
  const labelledBy = scroller.getAttribute('aria-labelledby')
  expect(labelledBy).toBeTruthy()
  expect(document.getElementById(labelledBy).textContent.trim().length).toBeGreaterThan(0)
})

it('renders nothing, rather than its own defaults, when handed an empty list', async () => {
  // Falling back to REMEDIATION_MODES here would put three modes on screen that the caller's own
  // data does not contain — the same invention the count rules forbid, one level up.
  const noModes = await mount({ modes: [] })
  expect(noModes.querySelector('table')).toBeNull()
  expect(noModes.textContent).toBe('')
  const noStages = await mount({ stages: [] })
  expect(noStages.querySelector('table')).toBeNull()
  expect(noStages.textContent).toBe('')
})

it('accepts caller-supplied modes and stages without inventing the rest', async () => {
  const container = await mount({
    stages: [{ id: 'scan', label: 'Scan' }, { id: 'publish', label: 'Publish' }],
    modes: [{ id: 'only', label: 'Only mode', stages: { scan: { actor: 'acp', text: 'Finds issues' } } }],
    activeModeId: 'only',
  })
  expect(container.querySelectorAll('thead th[scope=col]')).toHaveLength(3)
  expect(container.querySelectorAll('tbody td')).toHaveLength(2)
  // A stage the caller said nothing about is stated as such, not guessed at.
  const publish = cell(container, 'only', 'publish')
  expect(publish.dataset.actor).toBe('none')
  expect(publish.textContent).toContain('Not used')
})

// The guard this file was missing. Twelve DOM assertions passed while the component shipped a
// `landmark-unique` violation — the wrapper <section> and the scrollable region carried the same
// accessible name, so a screen-reader user got two identically-named landmarks for one diagram.
// It was caught downstream, by RemediationImpactCard's axe run, only once this was mounted there.
// A component whose entire purpose is explaining an accessibility product owes its own axe check.
//
// `region` is disabled for the same reason the impact card disables it: it flags content outside
// any landmark, which is a property of the PAGE this is embedded in, not of the fragment.
it('has no automated accessibility violations, mounted or active', async () => {
  for (const props of [{}, { activeModeId: 'end-to-end' },
                       { counts: { 'rule-fixes': { 'rule-based-auto': '31 auto' } } }]) {
    const container = await mount(props)
    const report = await axe.run(container, { rules: { region: { enabled: false } } })
    expect(report.violations.map(v => v.id)).toEqual([])
  }
})
