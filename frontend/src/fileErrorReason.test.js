/**
 * The drawer says why, or admits it does not know — it never guesses.
 *
 * On 2026-08-19 the drawer read "Could not analyse — file unreadable" over 22 SharePoint documents
 * that had never been fetched at all: the download was routed to the Google Drive client with a
 * Graph item id (#481). The sentence asserted two things the record does not support — that the
 * file was READ, and that the FILE was at fault — and it sent the investigation at the documents
 * while the bug sat in the plumbing.
 *
 * The reason was recorded the whole time, per file, by handlers:
 *
 *     log_decision("system", "scan.file_error", …, detail=f"{type(e).__name__}: {e}"[:200])
 *
 * These cases pin the three states apart and, above all, pin the refusal: when the log has nothing,
 * the drawer must SAY nothing was recorded rather than fall back to the old guess. A confident
 * wrong sentence costs more than a visible gap — that is the whole lesson of the incident.
 */
import { describe, it, expect } from 'vitest'
import { errorReasonFor, noFindingsLine, looksLikeFetchFailure } from './fileErrorReason.js'

const row = (over = {}) => ({
  action: 'scan.file_error', file: 'a.docx', ts: '2026-08-19T23:00:00Z',
  detail: 'HttpError: <HttpError 404 when requesting …>', ...over,
})

describe('finding the recorded reason', () => {
  it('returns the detail logged for that file', () => {
    expect(errorReasonFor([row()], 'a.docx')).toMatch(/404/)
  })

  it('does not borrow another file’s reason', () => {
    // The failure mode with teeth: a real message, attached to the wrong document, is more
    // misleading than no message — it reads as evidence about this file.
    expect(errorReasonFor([row({ file: 'other.docx' })], 'a.docx')).toBe(null)
  })

  it('ignores decision rows that are not file errors', () => {
    // The log carries every consequential action — scan mode, HITL review, settings changes.
    expect(errorReasonFor([{ action: 'pii.copied_forward', file: 'a.docx', detail: '3 items' }],
                          'a.docx')).toBe(null)
  })

  it('takes the newest attempt when a file failed more than once', () => {
    const rows = [row({ ts: '2026-08-19T22:00:00Z', detail: 'first: stale' }),
                  row({ ts: '2026-08-19T23:30:00Z', detail: 'second: current' })]
    expect(errorReasonFor(rows, 'a.docx')).toMatch(/current/)
  })

  it('survives an absent, empty or malformed log rather than throwing', () => {
    // The drawer renders before the fetch resolves, and a reason panel that throws takes the whole
    // document record with it — strictly worse than the sentence it was improving.
    for (const bad of [null, undefined, [], [null], [{}]]) {
      expect(errorReasonFor(bad, 'a.docx')).toBe(null)
    }
  })
})

describe('the sentence', () => {
  it('is unchanged for a document that simply has no findings', () => {
    expect(noFindingsLine('clean', null)).toBe('No findings — clean.')
    expect(noFindingsLine('certifiable', null)).toBe('No findings — clean.')
  })

  it('states the recorded reason when there is one', () => {
    const line = noFindingsLine('unanalysable', 'HttpError: 404 when requesting files/01ABC')
    expect(line).toMatch(/Could not process this file/)
    expect(line).toMatch(/404 when requesting/)
  })

  it('says the reason was NOT recorded rather than guessing "unreadable"', () => {
    // THE case. This exact fallback is what misdirected the 2026-08-19 investigation.
    const line = noFindingsLine('unanalysable', null)
    expect(line, 'the drawer guessed at a cause it does not have')
      .not.toMatch(/unreadable/i)
    expect(line).toMatch(/No reason was recorded/)
    expect(line).toMatch(/fetch or analysis/)
  })

  it('never claims the file was ANALYSED, because it may never have been fetched', () => {
    // `status='error'` is handlers' catch-all over the whole download+analyse block, so "could not
    // analyse" asserts a step that may not have been reached.
    for (const reason of ['HttpError: 404', null]) {
      expect(noFindingsLine('unanalysable', reason)).not.toMatch(/could not analyse/i)
    }
  })
})

describe('orienting the reader without overclaiming', () => {
  it('recognises the shapes that mean the source, not the document', () => {
    for (const r of ['HttpError: <HttpError 404 …>', 'ReadTimeout: timed out',
                     "AttributeError: 'NoneType' object has no attribute 'files'"]) {
      expect(looksLikeFetchFailure(r)).toBe(true)
    }
  })

  it('does not claim a parse failure is a fetch failure', () => {
    expect(looksLikeFetchFailure('PackageNotFoundError: not a Word file')).toBe(false)
    expect(looksLikeFetchFailure(null)).toBe(false)
  })
})
