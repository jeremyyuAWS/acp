import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { ASSESSMENT_FALLBACK, CAPABILITY_FALLBACK } from './capability.js'
import { SCOPE_SCS } from './activeScope.js'
import { assessMetrics } from './assessMetrics.js'
import { setLangfuseBase } from './api.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
// Tracing configured, as it is on any deployment that has an observability backend. TraceChip
// renders nothing without it, so the "behind a secondary action" tests would otherwise pass for
// the wrong reason — no chips because none exist, rather than none because none were asked for.
beforeEach(() => setLangfuseBase('https://langfuse.test/project/acp/traces'))
afterEach(() => setLangfuseBase(null))

const { default: RunDetails } = await import('./RunDetails.jsx')

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = readFileSync(join(HERE, 'RunDetails.jsx'), 'utf8')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

const render = async (props) => {
  await act(async () => { root.render(createElement(RunDetails, props)) })
  return container
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btn = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

// A small, realistic estate: two formats, one file the scanner could not open, findings on the
// criteria the fallback capability map actually covers.
const FILES = [
  { file: 'Finance/Q3 Board Pack.pdf', name: 'Finance/Q3 Board Pack.pdf', type: 'pdf', status: 'analysed',
    issues: [{ wcag: 'SC_1_1_1', severity: 'CRITICAL' }, { wcag: 'SC_1_3_1', severity: 'SERIOUS' }] },
  { file: 'HR/Handbook.docx', name: 'HR/Handbook.docx', type: 'docx', status: 'analysed',
    issues: [{ wcag: 'SC_2_4_2', severity: 'MODERATE' }] },
  { file: 'Legal/Master Agreement.pdf', name: 'Legal/Master Agreement.pdf', type: 'pdf', status: 'error',
    error: 'password-protected', issues: [] },
]
const PROPS = { scanId: 'scan-1', files: FILES, cap: CAPABILITY_FALLBACK, assessment: ASSESSMENT_FALLBACK }

// The same estate, but with a method for every criterion in the agreed scope — the "nothing was
// unassessable" branch, which must still SAY so rather than fall silent.
const FULL_ASSESSMENT = { docx: Object.fromEntries([...SCOPE_SCS].map((sc) => [sc, 'auto'])) }
const FULL_PROPS = {
  scanId: 'scan-2',
  files: [{ file: 'a.docx', name: 'a.docx', type: 'docx', status: 'analysed', issues: [] }],
  cap: CAPABILITY_FALLBACK,
  assessment: FULL_ASSESSMENT,
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// Lane 1 — behaviour, asserted against the rendered DOM.
// ───────────────────────────────────────────────────────────────────────────────────────────

describe('RunDetails renders nothing until the data has arrived', () => {
  it('no files prop at all — renders nothing, not a page of zeros', async () => {
    await render({ scanId: 'scan-1', cap: CAPABILITY_FALLBACK, assessment: ASSESSMENT_FALLBACK })
    expect(container.innerHTML).toBe('')
  })

  it('files is null (the fetch has not returned) — renders nothing', async () => {
    await render({ ...PROPS, files: null })
    expect(container.innerHTML).toBe('')
  })

  it('an empty file list is not a completed run with zero checks — renders nothing', async () => {
    await render({ ...PROPS, files: [] })
    expect(container.innerHTML).toBe('')
    // The specific failure this guards: "0 checks with no method" is a true sentence about a
    // finished run and a false one about a run that has not reported.
    expect(container.textContent).not.toContain('0')
  })
})

describe('the capability scorecard is reframed as a reference, not a result', () => {
  it('says in its own copy that the numbers do not change when you run an assessment', async () => {
    const txt = (await render(PROPS)).textContent
    // THE sentence the panel moved for. Without it, a capability count on a page reached from a
    // results screen reads as this run's score again — which is the defect, not the presentation.
    expect(txt).toContain('do not change when you run an assessment')
    expect(txt).toContain('the same before this run and after it')
    expect(txt).toContain('What ACP can check')
  })

  it('mounts the scorecard itself, so the reference is the real capability data', async () => {
    const txt = (await render(PROPS)).textContent
    // CoverageScorecard's own lane wording — proves the panel is mounted here rather than
    // paraphrased into a second, driftable copy of the capability claim.
    expect(txt).toContain('Fully Assessed')
    expect(txt).toContain('Potential Issue')
    expect(txt).toContain('Remediation')
  })

  it('names a criterion with no method as neither a pass nor a failure', async () => {
    const txt = (await render(PROPS)).textContent
    expect(txt).toContain('neither a pass nor a failure')
  })
})

describe('the “unable to assess” explanation', () => {
  it('leads with both numbers and states the denominator they are taken over', async () => {
    const m = assessMetrics(FILES, { cap: CAPABILITY_FALLBACK, assessment: ASSESSMENT_FALLBACK })
    const txt = (await render(PROPS)).textContent
    expect(m.unableToAssess).toBeGreaterThan(0)
    expect(txt).toContain(`Why ${m.unableToAssess} of your ${m.selectedChecks} checks came back`)
    // A count is never rendered without the population it counts over.
    expect(txt).toContain(`${m.documentsAssessed} documents opened × ${m.coverageSelected} criteria`)
    expect(txt).toContain('One check is one criterion judged against one document')
  })

  it('states, in words, that they are not passes and not failures', async () => {
    const txt = (await render(PROPS)).textContent
    expect(txt).toContain('They are not passes and they are not failures')
    expect(txt).toContain('reporting them as passes would be the single most damaging thing')
  })

  it('prints the check arithmetic, and it sums on screen', async () => {
    const m = assessMetrics(FILES, { cap: CAPABILITY_FALLBACK, assessment: ASSESSMENT_FALLBACK })
    const txt = (await render(PROPS)).textContent
    expect(txt).toContain(`${m.checksEvaluated} checks evaluated + ${m.unableToAssess} with no method = ${m.selectedChecks} selected checks`)
    expect(m.checksEvaluated + m.unableToAssess).toBe(m.selectedChecks)
  })

  it('names WHICH criteria had no method, so the claim can be checked', async () => {
    const m = assessMetrics(FILES, { cap: CAPABILITY_FALLBACK, assessment: ASSESSMENT_FALLBACK })
    const txt = (await render(PROPS)).textContent
    expect(m.unassessableCriteria.length).toBeGreaterThan(0)
    expect(txt).toContain('No method for these formats')
    for (const sc of m.unassessableCriteria) expect(txt).toContain(sc)
  })

  it('when every check had a method it SAYS so, rather than rendering an empty panel', async () => {
    const m = assessMetrics(FULL_PROPS.files, { cap: FULL_PROPS.cap, assessment: FULL_ASSESSMENT })
    expect(m.unableToAssess).toBe(0)
    const txt = (await render(FULL_PROPS)).textContent
    expect(txt).toContain(`Every one of your ${m.selectedChecks} checks reached a verdict`)
    expect(txt).not.toContain('came back')
    // And it still refuses to read as conformance.
    expect(txt).toContain('not a claim that the documents conform')
  })
})

describe('scan traces sit behind a secondary action', () => {
  it('no trace chip is on the page until the operator asks for one', async () => {
    await render(PROPS)
    expect(container.querySelector('.tracechip')).toBe(null)
    expect(btn('Show scan traces')).toBeTruthy()
  })

  it('opening the action reveals the scan trace and one per document', async () => {
    await render(PROPS)
    await click(btn('Show scan traces'))
    const chips = container.querySelectorAll('.tracechip')
    // One session chip + one per document row, including the file that could not be opened.
    expect(chips.length).toBe(1 + FILES.length)
    expect(container.textContent).toContain('View this scan’s traces')
    expect(container.textContent).toContain('could not be opened')
  })

  it('renders no trace section at all when the run has no scan id', async () => {
    await render({ ...PROPS, scanId: null })
    expect(container.textContent).not.toContain('Scan traces')
    expect(container.textContent).toContain('What ACP can check')   // the rest of the page still renders
  })
})

describe('what this view is forbidden to show', () => {
  it('renders no percentage, no score and no time-or-effort estimate', async () => {
    await render(PROPS)
    await click(btn('Show scan traces'))
    const txt = container.textContent
    expect(txt).not.toMatch(/\d\s*%/)
    expect(txt).not.toMatch(/\bpercent/i)
    // No score is PRESENTED. The word survives in exactly one place — the sentence explaining why
    // the capability panel was moved off the results screen, where its count was misread as one —
    // and that sentence is the reason this page exists, so it is asserted rather than banned.
    expect(txt).not.toMatch(/score\W{0,3}\d/i)
    expect(txt).not.toMatch(/accessibility score|compliance score|overall score/i)
    expect(txt).toContain('read as this run')
    expect(txt).not.toMatch(/\b(hrs?|hours?|minutes?|per person|est\.)\b/i)
  })

  it('the back action is the caller’s, not a route this view invents', async () => {
    let backs = 0
    await render({ ...PROPS, onBack: () => { backs++ } })
    await click(btn('← Assessment results'))
    expect(backs).toBe(1)
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// Lane 2 — source assertions, for the properties the DOM cannot show.
//
// A rendered page cannot tell you WHERE a number came from, and "this count agrees with
// assessMetrics" passes just as happily against a second, independent computation that happens to
// agree on this fixture. These read the module instead.
// ───────────────────────────────────────────────────────────────────────────────────────────

describe('RunDetails.jsx source', () => {
  it('imports its numbers from assessMetrics.js', () => {
    expect(SRC).toMatch(/import\s*\{[^}]*assessMetrics[^}]*\}\s*from\s*'\.\/assessMetrics\.js'/)
  })

  it('never recomputes a count from the file list', () => {
    // The failure mode: a details page that re-derives "checks with no method" from files + the
    // capability map, agrees with the summary today, and drifts the first time either changes.
    // No iteration over raw files, no arithmetic over issues, anywhere in this module.
    expect(SRC).not.toMatch(/files\s*\.\s*(map|filter|reduce|forEach|some|every)\b/)
    expect(SRC).not.toMatch(/\.issues\b/)
    expect(SRC).not.toMatch(/\bassessmentFor\b|\bmodeFor\b|\bfindingLevel\b/)
    // `files` is handed to CoverageScorecard whole (a capability view of the estate's formats) and
    // otherwise only length-checked.
    expect(SRC).toMatch(/files=\{files\}/)
  })

  it('guards on the data before it renders anything', () => {
    expect(SRC).toMatch(/if \(!Array\.isArray\(files\) \|\| files\.length === 0\) return null/)
    expect(SRC).toMatch(/if \(!m\) return null/)
  })

  it('contains no percentage, score or effort arithmetic to reintroduce', () => {
    // Stripped of comments: the module's prose explains WHY the score and the effort estimate were
    // removed, and those words are meant to be there. Code is what must not carry them.
    const code = SRC.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(code).not.toMatch(/toFixed|Math\.round|\/\s*100|\*\s*100/)
    expect(code).not.toMatch(/%/)
    // No score is computed, read or stored — the word may appear in prose explaining its absence,
    // but never as an identifier or a property this module touches.
    expect(code).not.toMatch(/\bscore\s*[:=]|\.score\b|\bscore\(/i)
    expect(code).not.toMatch(/\bhrs?\b|\bminutes?\b|per person|reviewerTime|effort/i)
  })

  it('does not import from the modules other threads own', () => {
    // This component is mounted BY App; it must not reach into the results screen's own pieces,
    // or the two surfaces stop being separable.
    expect(SRC).not.toMatch(/from '\.\/(App|AssessSummary|AssessWorklist|AssessFileFindings|AssessRunner)\.jsx'/)
  })
})
