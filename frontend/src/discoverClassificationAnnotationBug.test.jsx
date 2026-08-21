import { createElement, act } from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { NO_CLASSIFICATION_TITLE } from './classificationData.js'
import { annotate } from './ontology.js'

// Found live, 2026-08-21, on a real 170-file scan: the "How this works" copy and the exposure
// chart claimed a Deep-scan classification that never ran — exactly the false reading
// discoverClassificationAbsent.test.jsx exists to prevent, back after the fix that prevented it.
//
// Root cause: App.jsx passes Discover the ANNOTATED file list (ontology.annotate(scan.files)),
// and annotate() back-fills `department`/`tags` from a FILENAME GUESS (classifyByName) on every
// file that lacks them — which is every real file, always. So by the time
// hasClassificationData(files) ran, every real file already had a non-empty department, and the
// "was this estate really classified" check could never again see the true, empty, pre-annotation
// answer. The fix threads a second prop, `rawFiles` (the pre-annotation records), and checks THAT
// instead — defaulting to `files` so a caller that never passes it (every pre-existing test,
// including discoverClassificationAbsent.test.jsx's) keeps today's behaviour exactly.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

const REAL_SCAN_FILES = Array.from({ length: 12 }, (_, i) => ({
  file: `20230413_10121${i}.pptx`, type: 'PPTX', status: 'discovered', score: null,
}))

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], busy: false, onScan: () => {}, ...props }))
  })
  return container.textContent
}
afterEach(() => unmountAll())

describe('the annotate() filename guess must not defeat the classification-honesty check', () => {
  it('annotate() really does back-fill department/tags on every one of these — pinning the trap', () => {
    // If this ever stops being true (annotate() changes to leave real files alone), the bug this
    // test guards against can no longer occur via this path, and the test above should be revisited.
    const annotated = annotate(REAL_SCAN_FILES, null)
    expect(annotated.every((f) => typeof f.department === 'string' && f.department.length > 0)).toBe(true)
  })

  it('reads as classified when only the annotated array is available (the bug, reproduced)', async () => {
    const annotated = annotate(REAL_SCAN_FILES, null)
    // No rawFiles passed — but files itself already carries a guessed department on every row.
    // This is what App.jsx did before the fix, and it must NOT be what App.jsx does now.
    const t = await mount({ files: annotated })
    expect(t).not.toContain(NO_CLASSIFICATION_TITLE)
  })

  it('reads as UNCLASSIFIED when rawFiles carries the true pre-annotation records', async () => {
    const annotated = annotate(REAL_SCAN_FILES, null)
    const t = await mount({ files: annotated, rawFiles: REAL_SCAN_FILES })
    expect(t).toContain(NO_CLASSIFICATION_TITLE)
    expect(t).not.toMatch(/department & exposure come from the classification on each document/i)
  })

  it('still reads as classified when rawFiles itself carries real data', async () => {
    const realDept = [{ file: 'a.docx', department: 'Legal', tags: ['legal-hold'] }]
    const t = await mount({ files: annotate(REAL_SCAN_FILES, null), rawFiles: realDept })
    expect(t).not.toContain(NO_CLASSIFICATION_TITLE)
  })
})
