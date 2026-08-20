import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// A source sweep over the four R4/R7 modules, for claims that must never appear in them.
//
// A DOM test proves what a component renders for the fixtures it is given. It cannot prove a
// sentence is absent from every branch — a reassuring string on a path no fixture reaches still
// ships. These are the two claims this product has documented itself getting wrong, so they are
// checked against the source text rather than against a render.
//
// Every pattern below is applied to a KNOWN-BAD sample first. A sweep whose regex never matches
// anything is indistinguishable from a sweep that passed, and CLAUDE.md has that failure on record.

const HERE = dirname(fileURLToPath(import.meta.url))
const FILES = [
  'fixPreview.js',
  'RemediationFixPreview.jsx',
  'docRemediationProgress.js',
  'RemediationDocProgress.jsx',
]
const read = (f) => readFileSync(join(HERE, f), 'utf8')
const sources = FILES.map((f) => [f, read(f)])

// Strip line comments so a pattern quoted in a comment ("never print X") is not read as printing X.
const withoutComments = (s) => s.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')

describe('ADR 0010 — the drive claim', () => {
  // get_drive_mirror_enabled() is get_setting("drive_mirror_enabled", "true") != "false", so it
  // defaults TRUE: on a default deployment handlers.py mirrors the corrected copy into the drive's
  // mirror folder. Any blanket "your drive is untouched" is false there.
  const BAD = [
    /nothing\s+is\s+written\s+to\s+your\s+drive/i,
    /never\s+written\s+to\s+your\s+drive/i,
    /your\s+drive\s+is\s+(never\s+)?(touched|untouched|modified)/i,
    /no(thing)?\s+files?\s+are\s+written\s+to\s+(your|the)\s+drive/i,
  ]

  it('the patterns bite (positive control)', () => {
    const sample = 'Reassurance: nothing is written to your drive, and your drive is never touched.'
    expect(BAD.some((re) => re.test(sample))).toBe(true)
  })

  it('no module claims the customer’s drive is left untouched', () => {
    for (const [name, src] of sources) {
      const body = withoutComments(src)
      for (const re of BAD) expect(re.test(body), `${name} matched ${re}`).toBe(false)
    }
  })

  it('the destination sentence is driven by the setting, not hard-coded', () => {
    const s = read('fixPreview.js')
    expect(s).toMatch(/driveMirror\.enabled/)
    // Unread is its own branch, before the on/off branches.
    expect(s).toMatch(/enabled\s*==\s*null/)
    expect(s).toMatch(/known:\s*false/)
    // The folder is echoed from the setting; "Remediated" is never typed in as a literal.
    expect(s).toMatch(/driveMirror\.folder/)
    expect(withoutComments(s)).not.toMatch(/['"“]Remediated['"”]/)
  })
})

describe('ADR 0020 — Discover lists, it does not read', () => {
  // Discover runs classify_from_metadata and enqueues no analysis. Nothing at remediation time may
  // imply the file's content had been read before Assess.
  const BAD = [
    /during\s+discovery/i,
    /discover(y|ed)?\s+(read|opened|scanned|analys|analyz|inspect)/i,
    /(read|opened|scanned|analysed|analyzed)\s+(at|during|in)\s+discovery/i,
    /found\s+(this|it)\s+(during|at)\s+discovery/i,
  ]

  it('the patterns bite (positive control)', () => {
    const sample = 'We found this during discovery, when discovery opened the file.'
    expect(BAD.filter((re) => re.test(sample)).length).toBeGreaterThanOrEqual(2)
  })

  it('no module says discovery opened or read the document', () => {
    for (const [name, src] of sources) {
      const body = withoutComments(src)
      for (const re of BAD) expect(re.test(body), `${name} matched ${re}`).toBe(false)
    }
  })

  it('the pipeline rail declares no discovery stage', () => {
    const stages = read('docRemediationProgress.js')
      .match(/export const STAGES = \[[\s\S]*?\n\]/)[0]
    expect(stages).toBeTruthy()
    expect(stages).not.toMatch(/discover/i)
    expect(stages).not.toMatch(/inventor/i)
  })
})

describe('the spec’s decision rule — no generic Approve/Reject', () => {
  // docs/remediate-redesign-spec.md, change #5: "Remediation-specific decision actions (no generic
  // Approve/Reject)" and "Replace ambiguous 'Reject' with the specific action."
  it('the pattern bites (positive control)', () => {
    const sample = '<button>Approve</button><button>Reject</button>'
    expect(/>\s*(Approve|Reject)\s*</.test(sample)).toBe(true)
  })

  it('R4 renders no bare Approve or Reject control', () => {
    const s = withoutComments(read('RemediationFixPreview.jsx'))
    expect(s).not.toMatch(/>\s*(Approve|Reject)\s*</)
    expect(s).not.toMatch(/label:\s*['"](Approve|Reject)['"]/)
    // The specific actions the spec names instead.
    expect(s).toMatch(/Approve this wording/)
    expect(s).toMatch(/Mark resolved manually/)
    expect(s).toMatch(/Not applicable/)
  })
})

describe('R4 builds on the grounded renderer, not the illustrative one', () => {
  it('uses GroundedBeforeAfter and imports nothing from BeforeAfter.jsx', () => {
    // BeforeAfter.jsx's baFor() returns hand-written per-criterion markup ("3.1 : 1 · fails AA", a
    // "West / 38%" table) that belongs to no real document. It must not reach the remediation path.
    const s = read('RemediationFixPreview.jsx')
    expect(s).toMatch(/from '\.\/GroundedBeforeAfter\.jsx'/)
    for (const [name, src] of sources) {
      // Comments stripped: these modules explain in prose WHY baFor is unusable, and naming it
      // there is the opposite of calling it.
      const body = withoutComments(src)
      expect(body, `${name} imports BeforeAfter.jsx`).not.toMatch(/from '\.\/BeforeAfter\.jsx'/)
      expect(body, `${name} calls baFor`).not.toMatch(/\bbaFor\b/)
    }
  })

  it('R7 reuses the shipped stage precedence instead of restating it', () => {
    const s = read('docRemediationProgress.js')
    expect(s).toMatch(/import \{[^}]*workflowStatusOf[^}]*\} from '\.\/remediationInboxModel\.js'/)
    expect(s).toMatch(/workflowStatusOf\(f, decisions\)/)
  })
})

describe('neither module edits the files other PRs own', () => {
  it('nothing here imports Remediate.jsx or the surfaces claimed by open PRs', () => {
    const CLAIMED = [
      'Remediate.jsx', 'Overview.jsx', 'AssessSummary.jsx', 'AssessWorklist.jsx',
      'assessMetrics.js', 'ScanScopeWizard.jsx', 'Discover.jsx', 'DispositionRules.jsx',
    ]
    for (const [name, src] of sources) {
      for (const f of CLAIMED) {
        expect(src.includes(`./${f}'`), `${name} imports ${f}`).toBe(false)
      }
    }
  })
})
