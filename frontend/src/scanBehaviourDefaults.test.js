/**
 * What a scan does when nobody touches a switch.
 *
 * The Scan behaviour group has four toggles. Three started off and `incremental` started on, so
 * the default scan was a mix — and the one that was on is invisible in the result: an incremental
 * scan that skips a file reports a score for it either way, carried over from the previous run.
 * Nothing on screen distinguishes "scored now" from "scored last time under the same rubric".
 *
 * From 2026-08-19 the group starts uniformly off, so the baseline scan is the plainest one:
 * nothing skipped, nothing inferred, and the toggles read as additions to a known starting point
 * rather than as a set whose initial state has to be checked before the numbers mean anything.
 *
 * `exclude_remediated` IS THE DELIBERATE EXCEPTION and stays on. Off, ACP re-discovers its own
 * Remediated/ output as source documents: the file count grows with every remediation and files
 * show "remediated ✓" on a scan that remediated nothing (provenance.py lists five ways
 * folder-based exclusion breaks and this is the mildest). That is a wrong number pointing at MORE
 * coverage — the direction nobody re-checks — so it is not a symmetry worth having.
 *
 * Asserted against App.jsx's TEXT rather than by mounting App, for the same reason the CI wiring
 * tests read ci.yml: mounting the whole application to read four initial useState values pulls in
 * the entire provider tree, and a failure there would report as anything but "a default moved".
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = readFileSync(join(HERE, 'App.jsx'), 'utf8')

// [state name, expected initial value, why it is that way]
const DEFAULTS = [
  ['deepScan', 'false', 'PII extraction doubles scan time; it is opt-in'],
  ['queuedScan', 'false', 'session-scoped is the pilot default'],
  ['incremental', 'false',
   'a skipped file still reports a score, so the skip is invisible in the result'],
  ['excludeRemediated', 'true',
   "off, ACP re-ingests its own Remediated/ output — a count that grows and reads as more coverage"],
]

describe('the Scan behaviour group starts from a known baseline', () => {
  for (const [name, expected, why] of DEFAULTS) {
    it(`${name} defaults to ${expected} — ${why}`, () => {
      const m = APP.match(new RegExp(`const \\[${name}, set\\w+\\] = useState\\((\\w+)\\)`))
      expect(m, `no useState declaration found for ${name} in App.jsx`).toBeTruthy()
      expect(m[1]).toBe(expected)
    })
  }

  it('leaves exactly one of the four on, and it is the safety one', () => {
    // Stated as a whole-group property so "turn them all off" cannot quietly take
    // exclude_remediated with it. That request was made on 2026-08-19 and this is the one
    // deliberately held back — a decision worth more than a comment.
    //
    // READ OUT OF App.jsx, not out of DEFAULTS above. Filtering the table would compare a
    // constant to itself: green forever, including while the source said the opposite. The first
    // draft of this test did exactly that and was caught by mutating the source and watching this
    // case keep passing — "a check that cannot fail is indistinguishable from a check that
    // passed" (CLAUDE.md).
    const on = DEFAULTS
      .map(([name]) => [name, APP.match(new RegExp(`const \\[${name}, set\\w+\\] = useState\\((\\w+)\\)`))])
      .filter(([, m]) => m && m[1] === 'true')
      .map(([name]) => name)
    expect(on).toEqual(['excludeRemediated'])
  })
})
