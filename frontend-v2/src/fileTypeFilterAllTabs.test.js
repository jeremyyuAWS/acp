/**
 * The file-type filter is ONE rule, applied once, for every tab.
 *
 * It used to live inside Discover as an inline `files.filter(...)`, so the choice applied to the
 * inventory and to nothing after it. App handed the unfiltered list to Assess, Remediate,
 * Publish, Overview, Monitor and the Knowledge Graph — so an operator who scoped to .docx saw a
 * docx-only inventory, then a full estate on every screen that followed. Reported live: PDFs
 * scored and counted after the filter excluded them.
 *
 * A filter that stops applying one tab later is worse than no filter: every downstream number
 * describes a different population than the screen the operator set it on, and nothing says so.
 *
 * These are unit tests on the extracted rule rather than a render of App — App pulls in d3, the
 * whole tab set and a scan lifecycle, and none of that is what makes this correct.
 */
import { describe, it, expect } from 'vitest'
import { visibleForFileTypes } from './FileTypeConfig.jsx'

const FILES = [
  { file: 'a.docx', type: 'docx' },
  { file: 'b.pdf', type: 'pdf' },
  { file: 'c.pptx', type: 'pptx' },
  { file: 'd.xlsx', type: 'xlsx' },
]
const names = (fs) => fs.map((f) => f.file).sort()


describe('visibleForFileTypes', () => {
  it('drops only the types explicitly set false', () => {
    const out = visibleForFileTypes(FILES, { docx: true, pdf: false, pptx: false, xlsx: false })
    expect(names(out)).toEqual(['a.docx'])
  })

  it('treats an empty config as no restriction', () => {
    // A fresh workspace has written nothing. Filtering everything out would show an empty estate
    // and read as a broken scan rather than an unset preference.
    expect(names(visibleForFileTypes(FILES, {}))).toEqual(names(FILES))
    expect(names(visibleForFileTypes(FILES, null))).toEqual(names(FILES))
    expect(names(visibleForFileTypes(FILES, undefined))).toEqual(names(FILES))
  })

  it('allows a type the config has never heard of', () => {
    // `!== false`, not `=== true`. Custom extensions and formats added after a config was written
    // must not be silently hidden by it — the config records exclusions, not an allow-list.
    const out = visibleForFileTypes([...FILES, { file: 'e.rtf', type: 'rtf' }], { pdf: false })
    expect(names(out)).toContain('e.rtf')
    expect(names(out)).not.toContain('b.pdf')
  })

  it('does not mutate or reorder the input', () => {
    const before = [...FILES]
    const out = visibleForFileTypes(FILES, { pdf: false })
    expect(FILES).toEqual(before)
    expect(out.map((f) => f.type)).toEqual(['docx', 'pptx', 'xlsx'])
  })

  it('can exclude everything, and says so by returning nothing', () => {
    // Distinct from the empty-config case above: an operator who unticked every type has made a
    // choice, and it is not the same as having made none.
    const out = visibleForFileTypes(FILES, { docx: false, pdf: false, pptx: false, xlsx: false })
    expect(out).toEqual([])
  })
})
