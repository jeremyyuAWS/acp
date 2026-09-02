// A COMPANION FILE is the third thing a proposal's value can be, and the review card treats it
// as none of the other two.
//
//   content       alt text. Written INTO the document by an applier.
//   explain_only  a PDF structure map. CONFIRMED — read-only, and approving sends no value.
//   companion     a caption file. EDITED by the reviewer, delivered as a separate file.
//
// #1177 shipped captions under `explain_only`, which is right about the certify gate (no applier
// writes a .vtt into an .mp4) and wrong about the reviewer: the card told them "speech recognition
// mishears names, numbers and homophones" and then gave them a read-only box whose contents would
// have been discarded anyway. These pin the three places that decided that.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'EvidenceCard.jsx'), 'utf8')

describe('a companion row is authored, not merely confirmed', () => {
  it('has its own predicate rather than riding the explain-only branch', () => {
    // Folding it into `explainOnly` is precisely what made the caption card read-only, so the
    // separation is the fix and not a stylistic preference.
    expect(src).toMatch(
      /const companionRow = proposalList\.length > 0 && proposalList\.every\(\(p\) => p\.companion_file\)/)
    expect(src).toMatch(/const explainOnly = proposalList\.length > 0 && proposalList\.every\(\(p\) => p\.explain_only\)/)
  })

  it('is editable — a machine transcript a reviewer is told to check must be changeable', () => {
    // `editable` excludes explainOnly and decorativeRow and must NOT exclude companionRow; the
    // trailing clause is what admits a caption card, whose SC is not a classic value-fix.
    const line = src.match(/const editable = [^\n]*\n[^\n]*/)[0]
    expect(line).toContain('!explainOnly')
    expect(line).toContain('!decorativeRow')
    expect(line).not.toContain('!companionRow')
    expect(line).toContain('companionRow')
  })

  it('sends the reviewer\'s text on approval, so the correction is not discarded', () => {
    // approve_proposal_values is the ONLY thing that records the edited text. Suppressing the
    // values here (as the explain-only branch does, correctly, for a structure map) loses the
    // correction silently — the machine's draft and the corrected file are both valid WebVTT.
    const gate = src.match(/const approvedValues = \([^)]*\)/)[0]
    expect(gate).toContain('!explainOnly')
    expect(gate).not.toContain('companionRow')
  })
})

describe('the artefact can be obtained', () => {
  it('offers a download addressed to the item, not to a caller-supplied filename', () => {
    // No filename in the URL: the name comes from the stored row, so nothing a caller sends can
    // reach the Content-Disposition header. The traversal surface is closed at the route.
    expect(src).toMatch(/href=\{`\/hitl\/queue\/\$\{encodeURIComponent\(item\.id\)\}\/companion`\}/)
    expect(src).toMatch(/companionRow && item\?\.id &&/)
  })

  it('uses a plain anchor rather than a scripted download', () => {
    // The endpoint sets Content-Disposition, so the browser saves it under the right name with no
    // script — which is also what makes it work for a keyboard user and a screen reader without
    // the focus handling a blob download would need.
    const block = src.slice(src.indexOf('evcard-companion-download'))
    expect(block.slice(0, 600)).toMatch(/<a href=/)
    expect(block.slice(0, 600)).not.toMatch(/fetch\(|createObjectURL/)
  })

  it('does not gate the download on approval', () => {
    // A reviewer checking a transcript against the audio needs the file in a player BEFORE
    // deciding. Requiring approval first would make them approve it to find out whether they
    // should, which is the wrong way round.
    const block = src.slice(src.indexOf('evcard-companion-download') - 400)
    expect(block.slice(0, 900)).not.toMatch(/status === 'approved'/)
  })
})
