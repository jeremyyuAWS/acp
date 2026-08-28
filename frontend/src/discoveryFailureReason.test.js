import { describe, it, expect } from 'vitest'
import { discoveryFailureReason } from './discoveryFailureReason.js'

const decision = (action, detail, extra = {}) => ({ action, detail, ...extra })

describe('discoveryFailureReason', () => {
  it('returns null for no decisions at all', () => {
    expect(discoveryFailureReason(null)).toBeNull()
    expect(discoveryFailureReason(undefined)).toBeNull()
    expect(discoveryFailureReason([])).toBeNull()
  })

  it('surfaces the single-flight conflict message verbatim', () => {
    const detail = "Discovery already active for source 'drive': scan abc123 is still running"
    const rows = [decision('scan.discover_conflict', detail)]
    expect(discoveryFailureReason(rows)).toBe(detail)
  })

  it('surfaces a generic listing-failure message', () => {
    const detail = 'listing drive failed: HttpError 401 invalid_grant'
    const rows = [decision('scan.discover_failed', detail)]
    expect(discoveryFailureReason(rows)).toBe(detail)
  })

  it('surfaces the suspicious-zero message', () => {
    const detail = 'listing returned 0 files but previous scan xyz found 170; refusing to publish suspicious zero'
    const rows = [decision('scan.suspicious_zero', detail)]
    expect(discoveryFailureReason(rows)).toBe(detail)
  })

  it('surfaces the unreachable-zero message', () => {
    const detail = 'listing returned 0 files and the source could not be read (403); refusing to publish an unverified empty estate'
    const rows = [decision('scan.unreachable_zero', detail)]
    expect(discoveryFailureReason(rows)).toBe(detail)
  })

  it('ignores unrelated scan.* kinds — matches by allowlist, not by prefix', () => {
    const rows = [
      decision('scan.discovered', 'discovery completed'),
      decision('scan.drive_unusable', 'drive api disabled for this account'),
    ]
    expect(discoveryFailureReason(rows)).toBeNull()
  })

  it('ignores per-file entries even when the action name matches — ignore is wrong, this checks the `file` guard', () => {
    // A per-file decision would never actually carry one of the FAILURE_KINDS actions in
    // practice, but the `!d.file` guard is what makes that impossible rather than incidental —
    // pin it directly so a future kind added to the allowlist can't reintroduce the mistake.
    const rows = [decision('scan.discover_failed', 'per-file, not the whole run', { file: 'a.docx' })]
    expect(discoveryFailureReason(rows)).toBeNull()
  })

  it('picks the most recent match when the log carries more than one (rows are ts DESC from the API)', () => {
    const rows = [
      decision('scan.discover_failed', 'second attempt failed too'),
      decision('scan.discover_failed', 'first attempt failed'),
    ]
    expect(discoveryFailureReason(rows)).toBe('second attempt failed too')
  })

  it('returns null when a decision has an empty detail rather than rendering an empty banner', () => {
    const rows = [decision('scan.discover_failed', '')]
    expect(discoveryFailureReason(rows)).toBeNull()
  })
})
