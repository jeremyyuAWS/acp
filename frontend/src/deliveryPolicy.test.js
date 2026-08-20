import { describe, it, expect } from 'vitest'
import {
  MIRROR, DEFAULT_MIRROR_FOLDER, mirrorState, mirrorFolder, sourceKind, fileDelivery,
  destinationLine, destinationLabel, deliverySummary, summaryLine, replaceNote, COPY_GUARANTEE,
} from './deliveryPolicy.js'

const driveFile = (name) => ({ file: name, drive_file_id: 'gd-' + name })
const spFile = (name) => ({ file: name, sp_item_id: 'sp-' + name })
const localFile = (name) => ({ file: name })

const ON = { drive_mirror_enabled: true, drive_mirror_folder: 'Remediated' }
const OFF = { drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' }

describe('mirrorState — the setting has three states, and the third is not false', () => {
  it('reads a real boolean as ON or OFF', () => {
    expect(mirrorState(ON)).toBe(MIRROR.ON)
    expect(mirrorState(OFF)).toBe(MIRROR.OFF)
  })

  // The whole point of the module. api/store.py:4020 defaults the setting to TRUE, so an unread
  // setting rendered as "off" tells the customer their files are staying out of their Drive when
  // the shipped default puts them in it.
  it('reads an unfetched / failed / keyless settings object as UNREAD, never as OFF', () => {
    expect(mirrorState(null)).toBe(MIRROR.UNREAD)
    expect(mirrorState(undefined)).toBe(MIRROR.UNREAD)
    expect(mirrorState({})).toBe(MIRROR.UNREAD)
    expect(mirrorState({ drive_mirror_folder: 'Remediated' })).toBe(MIRROR.UNREAD)
  })

  it('does not coerce truthy/falsy non-booleans into an answer', () => {
    // A string "false" from a mis-shaped payload must not read as a disabled mirror, and a
    // string "true" must not read as an enabled one. Neither is a boolean; neither is an answer.
    expect(mirrorState({ drive_mirror_enabled: 'false' })).toBe(MIRROR.UNREAD)
    expect(mirrorState({ drive_mirror_enabled: 'true' })).toBe(MIRROR.UNREAD)
    expect(mirrorState({ drive_mirror_enabled: 0 })).toBe(MIRROR.UNREAD)
    expect(mirrorState({ drive_mirror_enabled: 1 })).toBe(MIRROR.UNREAD)
  })
})

describe('mirrorFolder', () => {
  it('is null while the setting is unread — the name is not guessed', () => {
    expect(mirrorFolder(null)).toBeNull()
    expect(mirrorFolder({})).toBeNull()
  })

  it("uses the backend's own default once the setting has been read", () => {
    // api/store.py:4028 — get_setting("drive_mirror_folder", "Remediated").
    expect(mirrorFolder({ drive_mirror_enabled: true })).toBe(DEFAULT_MIRROR_FOLDER)
    expect(mirrorFolder({ drive_mirror_enabled: false, drive_mirror_folder: '  ' })).toBe(DEFAULT_MIRROR_FOLDER)
  })

  it('honours an admin-renamed folder rather than hardcoding "Remediated"', () => {
    expect(mirrorFolder({ drive_mirror_enabled: true, drive_mirror_folder: 'WCAG fixed' })).toBe('WCAG fixed')
  })
})

describe('sourceKind — the automatic mirror is a Drive-source behaviour', () => {
  it('classifies by the id the remediate job actually requires', () => {
    // api/handlers.py:459 — no drive_file_id, no _remediate_file, no mirror.
    expect(sourceKind(driveFile('a.docx'))).toBe('drive')
    expect(sourceKind(spFile('b.docx'))).toBe('sharepoint')
    expect(sourceKind(localFile('c.docx'))).toBe('other')
    expect(sourceKind(null)).toBe('other')
  })
})

describe('fileDelivery', () => {
  it('always promises the durable copy — that is the must-succeed write', () => {
    // api/handlers.py:659 — the Blob upload runs before, and independently of, the mirror gate.
    for (const settings of [ON, OFF, null]) {
      for (const f of [driveFile('a'), spFile('b'), localFile('c')]) {
        expect(fileDelivery(f, settings).durableCopy).toBe(true)
      }
    }
  })

  it('carries the mirror state through for a Drive-sourced file, in all three states', () => {
    expect(fileDelivery(driveFile('a'), ON).mirror).toBe(MIRROR.ON)
    expect(fileDelivery(driveFile('a'), OFF).mirror).toBe(MIRROR.OFF)
    expect(fileDelivery(driveFile('a'), null).mirror).toBe(MIRROR.UNREAD)
  })

  it('reports the mirror as inapplicable — definitely, not unknown — for a non-Drive source', () => {
    // Not reading the setting; reading the code path. _remediate_file never runs for these, so
    // "no automatic Drive copy" stays true even when the setting is unread.
    const sp = fileDelivery(spFile('b'), null)
    expect(sp.mirrorApplies).toBe(false)
    expect(sp.mirror).toBe(MIRROR.OFF)
    expect(sp.folder).toBeNull()
  })

  it('offers replace-in-place only where a write scope exists for it', () => {
    // frontend/src/sharepointScopes.js:22-24 — this build requests no *.ReadWrite scope.
    expect(fileDelivery(driveFile('a'), ON).replaceAvailable).toBe(true)
    expect(fileDelivery(spFile('b'), ON).replaceAvailable).toBe(false)
    expect(fileDelivery(localFile('c'), ON).replaceAvailable).toBe(false)
  })
})

describe('destinationLine — the sentence that gets quoted back at us', () => {
  it('names the Drive folder when the mirror is ON', () => {
    const line = destinationLine(fileDelivery(driveFile('a'), { drive_mirror_enabled: true, drive_mirror_folder: 'Fixed' }))
    expect(line).toContain('“Fixed”')
    expect(line).toContain('alongside the original')
  })

  it('says the mirror is off when it is off, without denying the durable copy', () => {
    const line = destinationLine(fileDelivery(driveFile('a'), OFF))
    expect(line).toContain('ACP storage')
    expect(line).toMatch(/mirror is switched off/i)
  })

  it('claims nothing in either direction while the setting is unread', () => {
    const line = destinationLine(fileDelivery(driveFile('a'), null))
    expect(line).toMatch(/has not been read/i)
    // No folder name and no verdict — an unread setting must not produce either.
    expect(line).not.toContain('Remediated')
    expect(line).not.toMatch(/switched off/i)
    // The Drive clause must stay hypothetical. "Whether a copy is also written … depends on" is
    // the shape that is allowed; a bare "a second copy is written" is the shape that is not, so
    // the assertion is on the conditional framing rather than on the verb.
    expect(line).toMatch(/whether a copy is also written/i)
    expect(line).not.toMatch(/and a second copy/i)
  })

  it('never interpolates a null folder name', () => {
    for (const settings of [ON, OFF, null, {}]) {
      for (const f of [driveFile('a'), spFile('b'), localFile('c')]) {
        const d = fileDelivery(f, settings)
        expect(destinationLine(d)).not.toContain('null')
        expect(destinationLabel(d)).not.toContain('null')
        expect(destinationLine(d)).not.toContain('undefined')
      }
    }
  })
})

// The banned sentence, asserted against the strings that MAKE the destination claim — not against
// a whole rendered screen, which would also sweep up explanatory copy that is allowed to discuss
// Drive writes. See DeliveryPanel.test.jsx for the DOM-scoped counterpart.
describe('the false version of this promise is never produced', () => {
  const BANNED = [
    /nothing is written to your drive/i,
    /no files? (?:are|is) written to your drive/i,
    /acp does(?:n't| not) write (?:anything )?to your drive/i,
    /your drive is (?:never )?(?:un)?touched/i,
  ]

  it('holds for every destination string in every mirror state', () => {
    const claims = []
    for (const settings of [ON, OFF, null, {}, { drive_mirror_enabled: true, drive_mirror_folder: 'Fixed' }]) {
      for (const f of [driveFile('a'), spFile('b'), localFile('c')]) {
        const d = fileDelivery(f, settings)
        claims.push(destinationLine(d), destinationLabel(d))
      }
      claims.push(summaryLine(deliverySummary([driveFile('a'), spFile('b')], settings)))
    }
    claims.push(COPY_GUARANTEE)
    for (const claim of claims) {
      for (const banned of BANNED) expect(claim).not.toMatch(banned)
    }
  })
})

describe('COPY_GUARANTEE — unconditional, and scoped to what was verified', () => {
  it('states the copy-not-in-place guarantee without reference to any setting', () => {
    expect(COPY_GUARANTEE).toMatch(/works on a copy/i)
    expect(COPY_GUARANTEE).toMatch(/not edited in place/i)
    // It is a constant precisely so it cannot vary by configuration; nothing about Drive, the
    // mirror, or a folder belongs in it.
    expect(COPY_GUARANTEE).not.toMatch(/mirror|folder|blob|drive/i)
  })
})

describe('deliverySummary — missing data is not measured zero', () => {
  const files = [driveFile('a'), driveFile('b'), spFile('c')]

  it('counts the Drive-bound copies when the setting says they are going', () => {
    const s = deliverySummary(files, ON)
    expect(s.total).toBe(3)
    expect(s.driveSourced).toBe(2)
    expect(s.toDrive).toBe(2)
  })

  it('counts zero when the mirror is genuinely off — that IS a measurement', () => {
    expect(deliverySummary(files, OFF).toDrive).toBe(0)
  })

  it('reports null, not 0, when the setting has not been read', () => {
    const s = deliverySummary(files, null)
    expect(s.toDrive).toBeNull()
    expect(s.toDrive).not.toBe(0)
    expect(s.mirror).toBe(MIRROR.UNREAD)
    expect(s.folder).toBeNull()
  })

  it('still measures zero when no file in the batch could be mirrored at all', () => {
    // Nothing unknown here even with the setting unread: none of these files takes the Drive path.
    const s = deliverySummary([spFile('c'), localFile('d')], null)
    expect(s.driveSourced).toBe(0)
    expect(s.toDrive).toBe(0)
  })

  it('promises the durable copy for every file regardless of the setting', () => {
    for (const settings of [ON, OFF, null]) {
      expect(deliverySummary(files, settings).toDurableCopy).toBe(3)
    }
  })
})

describe('summaryLine', () => {
  it('gives the Drive count when the mirror is on', () => {
    expect(summaryLine(deliverySummary([driveFile('a'), driveFile('b')], ON)))
      .toMatch(/2 of them are also written into the “Remediated” folder/)
  })

  it('says the mirror is off when it is off', () => {
    expect(summaryLine(deliverySummary([driveFile('a')], OFF))).toMatch(/mirror is switched off/i)
  })

  it('defers rather than guesses when the setting is unread', () => {
    const line = summaryLine(deliverySummary([driveFile('a')], null))
    expect(line).toMatch(/has not been read/i)
    expect(line).not.toMatch(/switched off/i)
    expect(line).not.toContain('Remediated')
  })

  it('makes no Drive claim at all for a batch with no Drive-sourced file', () => {
    const line = summaryLine(deliverySummary([spFile('c')], null))
    expect(line).toBe('1 corrected copy in ACP storage, to download from here.')
  })
})

describe('replaceNote', () => {
  it('is null when nothing in the batch can be replaced', () => {
    expect(replaceNote([fileDelivery(spFile('b'), ON), fileDelivery(localFile('c'), ON)])).toBeNull()
    expect(replaceNote([])).toBeNull()
  })

  it('describes replacement as separate from remediation, and names the archive', () => {
    const note = replaceNote([fileDelivery(driveFile('a'), ON)])
    expect(note).toMatch(/separate action/i)
    expect(note).toMatch(/never part of remediation/i)
    expect(note).toContain('_mova-originals')
    // Fail-closed, per GoogleDrive.jsx archiveOriginal: a failed archive abandons the write.
    expect(note).toMatch(/abandons the write/i)
  })
})
