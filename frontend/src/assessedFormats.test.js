/**
 * "Formats: DOCX, XLSX, PPTX, PDF" — and no statement of what they are the formats OF.
 *
 * The scan walks everything. `scanner._sp_list` builds two lists from one walk:
 *
 *     est_files.append({...})                    # every item found, whatever its type
 *     if Path(name).suffix.lower() in exts:      # .docx .pptx .xlsx .pdf .html .htm
 *         files.append(rec)                      # -> inventory row -> assessable later
 *
 * So a run has three populations — everything discovered, the supported extensions, and the
 * formats chosen for THIS run — and the review step named only the third, as a bare list, next to
 * a count of the first. A reader has no way to tell which population the four labels apply to, and
 * the reassuring reading is "all of them".
 *
 * A true list, a false conclusion — the same family as #479, #483, #491 and #502. The fix is not a
 * new number; it is saying what the numbers already on screen mean.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  ASSESSED_ROW_LABEL, SUPPORTED_EXTS, assessedFormatsLine, OTHER_TYPES_NOTE,
  footerFormatsPart, unscannableFormats,
} from './assessedFormats.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')
const LABELS = { docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', pdf: 'PDF' }

describe('the row label', () => {
  it('names both things these formats decide', () => {
    // "Formats" alone is a category, not a claim. The user asked for the two verbs specifically.
    expect(ASSESSED_ROW_LABEL).toMatch(/WCAG/)
    expect(ASSESSED_ROW_LABEL).toMatch(/assess/i)
    expect(ASSESSED_ROW_LABEL).toMatch(/remediat/i)
  })
})

describe('the format list', () => {
  it('renders the chosen formats', () => {
    expect(assessedFormatsLine(['docx', 'pdf'], LABELS)).toBe('DOCX, PDF')
  })

  it('says "None selected" rather than rendering blank', () => {
    // An empty row beside a document count reads as "all of them" — the same blank-means-everything
    // failure as the empty folder selection in #502.
    expect(assessedFormatsLine([], LABELS)).toBe('None selected')
    expect(assessedFormatsLine(null, LABELS)).toBe('None selected')
  })

  it('falls back to the raw name when a label is missing', () => {
    // A format present in the scan but absent from FMT_LABEL must still appear. Rendering
    // `undefined` would silently shorten the list the user is reconciling against.
    expect(assessedFormatsLine(['docx', 'html'], LABELS)).toBe('DOCX, HTML')
  })
})

describe('what happens to everything else', () => {
  it('says the other files are LISTED, not dropped', () => {
    // Stated positively about the estate. A reader who thinks unsupported files vanished cannot
    // reconcile Discover's estate count with this document count, and will assume one is wrong.
    expect(OTHER_TYPES_NOTE).toMatch(/listed in the inventory/i)
    expect(OTHER_TYPES_NOTE).toMatch(/unevaluated|not.*evaluat/i)
  })

  it('does not claim the other types are excluded from the scan', () => {
    expect(OTHER_TYPES_NOTE, 'the note says unsupported files are skipped, which they are not')
      .not.toMatch(/skipped|ignored|excluded/i)
  })
})

describe('the footer', () => {
  it('says the formats are ASSESSED, not merely counted', () => {
    // "4 formats" alone reads as a filter on what gets FOUND. It is a filter on what gets JUDGED.
    expect(footerFormatsPart(4)).toBe('4 formats assessed')
  })

  it('pluralises', () => {
    expect(footerFormatsPart(1)).toBe('1 format assessed')
  })
})

describe('a format the scanner cannot produce a row for', () => {
  it('finds none today, because the picker offers exactly what the scanner supports', () => {
    expect(unscannableFormats(['docx', 'xlsx', 'pptx', 'pdf'])).toEqual([])
  })

  it('would catch one if the picker gained a format the walker does not list', () => {
    // The guard's whole purpose. `exts` lives in Python and the picker in JS, with nothing
    // connecting them — a format added here but not there would be selected, listed in the review
    // step with confidence, and never assessed.
    expect(unscannableFormats(['docx', 'rtf'])).toEqual(['rtf'])
  })

  it('knows the extensions the scanner actually walks', () => {
    // Mirrors `exts` in scanner._sp_list. html is in the scanner's set and is NOT offered by the
    // picker — supported-but-unoffered is fine; offered-but-unsupported is the bug.
    for (const e of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) expect(SUPPORTED_EXTS).toContain(e)
  })
})

describe('the wizard actually uses this', () => {
  const src = read('ScanScopeWizard.jsx')

  it('labels the review row with the assessed/remediated wording', () => {
    expect(src).toMatch(/\{ASSESSED_ROW_LABEL\}/)
    expect(src, 'the bare "Formats" label is back').not.toMatch(/<dt className="muted">Formats<\/dt>/)
  })

  it('shows what happens to the other file types', () => {
    expect(src).toMatch(/\{OTHER_TYPES_NOTE\}/)
  })

  it('routes the footer through the assessed wording', () => {
    expect(src).toMatch(/footerFormatsPart\(nFormats\)/)
  })

  it('counts the same formats in both places, so they cannot disagree', () => {
    // nFormats and activeFormats are both SCOPE_FORMATS.filter(formatActive); if one ever stops
    // being, the footer and the review row start describing different runs.
    expect(src).toMatch(/const nFormats = SCOPE_FORMATS\.filter\(formatActive\)\.length/)
    expect(src).toMatch(/const activeFormats = SCOPE_FORMATS\.filter\(formatActive\)/)
  })
})
