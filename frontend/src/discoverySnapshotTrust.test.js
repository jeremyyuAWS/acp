import { describe, it, expect } from 'vitest'
import { snapshotTrust, snapshotTrustMessage } from './discoverySnapshotTrust.js'

const run = (enumeration, extra = {}) => ({ scope: enumeration ? { enumeration } : {}, ...extra })

describe('snapshotTrust', () => {
  it('flags a truncated listing, and names truncation as the cause', () => {
    const v = snapshotTrust(run({ complete: false, truncated: true, files_found: 50000 }))
    expect(v).toEqual({ partial: true, reason: 'truncated', filesFound: 50000 })
  })

  it('flags an incomplete listing that was not truncated', () => {
    const v = snapshotTrust(run({ complete: false, truncated: false, files_found: 12 }))
    expect(v.partial).toBe(true)
    expect(v.reason).toBe('incomplete')
  })

  it('passes a complete listing', () => {
    expect(snapshotTrust(run({ complete: true, truncated: false, files_found: 3 })))
      .toEqual({ partial: false })
  })

  // The three ways a banner here would cry wolf. Each one would put a warning on a scan that is
  // fine, and a warning that fires on good scans stops being read on bad ones.
  describe('says nothing rather than guessing', () => {
    it('for a run predating the enumeration flag', () => {
      // Every scan older than the resilience work has no scope.enumeration. Reporting those as
      // incomplete would band the entire scan history.
      expect(snapshotTrust({ scope: { kind: 'drive', truncated: false } })).toBeNull()
      expect(snapshotTrust({ scope: {} })).toBeNull()
      expect(snapshotTrust({})).toBeNull()
      expect(snapshotTrust(null)).toBeNull()
    })

    it('for a failed run, which already has its own stronger banner', () => {
      expect(snapshotTrust(run({ complete: false, truncated: true }, { status: 'failed' })))
        .toBeNull()
    })

    it('when only published_at is missing', () => {
      // scan_runs.published_at is NOT stamped on a checkpoint-resumed scan (handlers skips
      // mark_published when _checkpoint_resume), so a run that crashed once, resumed and finished
      // correctly is unpublished too. Absence of the stamp must not read as a bad snapshot.
      const resumed = run({ complete: true, truncated: false, files_found: 9 },
                          { published_at: null })
      expect(snapshotTrust(resumed)).toEqual({ partial: false })
    })
  })

  it('tolerates a missing files_found rather than rendering NaN', () => {
    const v = snapshotTrust(run({ complete: false, truncated: true }))
    expect(v.filesFound).toBeNull()
    expect(snapshotTrustMessage(v).body).not.toMatch(/NaN|undefined|null/)
  })
})

describe('snapshotTrustMessage', () => {
  it('is silent for a complete listing and for no verdict', () => {
    expect(snapshotTrustMessage({ partial: false })).toBeNull()
    expect(snapshotTrustMessage(null)).toBeNull()
  })

  it('names the mechanism and the next step, not just "may be incomplete"', () => {
    const m = snapshotTrustMessage({ partial: true, reason: 'truncated', filesFound: 50000 })
    expect(m.body).toMatch(/50,000/)
    expect(m.body).toMatch(/cap/)
    expect(m.body).toMatch(/folders/)          // the action that actually resolves it
  })

  it('does not describe a truncated estate as the whole estate', () => {
    const m = snapshotTrustMessage({ partial: true, reason: 'truncated', filesFound: 10 })
    expect(m.title).toMatch(/not all of it/)
  })
})
