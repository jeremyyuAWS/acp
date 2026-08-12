import { describe, it, expect } from 'vitest'
import { releaseDestination, releaseDestinationPhrase, releaseConfirmLines } from './releasePolicy.js'

describe('releaseDestination (per file)', () => {
  it('sends a Drive-sourced file to the Drive mirror when it is enabled', () => {
    const d = releaseDestination({ driveFileId: 'abc', driveMirrorEnabled: true, driveMirrorFolder: 'Remediated' })
    expect(d.toDrive).toBe(true)
    expect(d.folder).toBe('Remediated')
    expect(d.label).toMatch(/Drive .*Remediated.* \+ Blob/)
  })
  it('falls back to Blob when the mirror is off, or the file is not from Drive', () => {
    expect(releaseDestination({ driveFileId: 'abc', driveMirrorEnabled: false }).toDrive).toBe(false)
    expect(releaseDestination({ driveFileId: null, driveMirrorEnabled: true }).toDrive).toBe(false)
    expect(releaseDestination({ driveFileId: null, driveMirrorEnabled: false }).label).toBe('Azure Blob')
  })
  it('defaults the folder name rather than printing "undefined"', () => {
    expect(releaseDestination({ driveFileId: 'x', driveMirrorEnabled: true }).folder).toBe('Remediated')
  })
})

describe('releaseDestinationPhrase (batch)', () => {
  it('names the Drive folder only when a Drive file is present AND the mirror is on', () => {
    expect(releaseDestinationPhrase({ anyDrive: true, driveMirrorEnabled: true, driveMirrorFolder: 'Fixed' }))
      .toBe('the Drive “Fixed” folder and a durable Azure Blob copy')
    expect(releaseDestinationPhrase({ anyDrive: true, driveMirrorEnabled: false }))
      .toBe('a durable Azure Blob copy (a download link)')
    expect(releaseDestinationPhrase({ anyDrive: false, driveMirrorEnabled: true }))
      .toBe('a durable Azure Blob copy (a download link)')
  })
})

describe('releaseConfirmLines (honesty guardrails)', () => {
  it('states the destination, the untouched original, the audit, and the non-certification', () => {
    const lines = releaseConfirmLines({ count: 3, anyDrive: true, driveMirrorEnabled: true, driveMirrorFolder: 'Remediated' })
    expect(lines[0]).toMatch(/corrected copy of these 3 documents to the Drive “Remediated” folder/)
    expect(lines.some((l) => /never overwritten/.test(l))).toBe(true)
    expect(lines.some((l) => /audit trail/.test(l))).toBe(true)
    // The one place "certify" may appear is the disclaimer — never as a positive claim.
    const certLines = lines.filter((l) => /certif/i.test(l))
    expect(certLines).toHaveLength(1)
    expect(certLines[0]).toMatch(/does not certify/)
  })
  it('uses singular wording for a single document', () => {
    const lines = releaseConfirmLines({ count: 1, anyDrive: false, driveMirrorEnabled: false })
    expect(lines[0]).toMatch(/corrected copy of this document to a durable Azure Blob copy/)
  })
})
