import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The "Assess a single file · without connecting a source" panel is gone from Discover, on request.
//
// Recorded rather than left implicit, because the removal costs more than a collapsed box: that
// panel was the app's ONLY mount of Upload. Upload folded into Discover when v2 dropped its
// top-level tab (#151), so with the panel gone there is no route to ad-hoc single-file assessment
// at all. Someone reading Upload.jsx later will find a complete, tested component and reasonably
// assume it is live. It is not.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Comments stripped: the comment EXPLAINING a removal necessarily quotes what it removed, so a
// whole-file ban matches its own protected explanation. That has failed on correct code four times
// in this repo.
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('the single-file upload panel is gone from Discover', () => {
  it('renders neither the panel nor its copy', () => {
    const d = code('Discover.jsx')
    expect(d).not.toMatch(/<Upload\b/)
    expect(d).not.toContain('Assess a single file')
    expect(d).not.toContain('without connecting a source')
    // The stripper must not be what makes this pass.
    expect(d).toContain('export default function Discover')
    expect(d.length).toBeGreaterThan(2000)
  })

  it('drops the import and the prop that fed it', () => {
    const d = code('Discover.jsx')
    expect(d).not.toMatch(/import Upload from/)
    // onCertified reached nothing once the panel went; a prop threaded to a dead mount is the kind
    // of leftover that makes the next reader think the feature is still wired.
    expect(d).not.toMatch(/onCertified/)
  })

  it('and App stops passing it', () => {
    expect(code('App.jsx')).not.toMatch(/onCertified=/)
  })
})

describe('what the removal actually costs', () => {
  it('Upload.jsx is now mounted nowhere', () => {
    // Asserted, not assumed. An unmounted component reads as shipped on every status list — the
    // failure this codebase hit three times in one evening, in the other direction.
    //
    // Upload.jsx is deliberately NOT deleted: restoring the panel is one commit, and deleting a
    // working capability is a bigger decision than removing a panel. When that decision is taken,
    // this case goes with the file.
    expect(existsSync(join(here, 'Upload.jsx'))).toBe(true)
    const screens = ['App.jsx', 'Discover.jsx', 'Overview.jsx', 'Settings.jsx', 'Integrations.jsx']
      .filter((f) => existsSync(join(here, f)))
      .filter((f) => /<Upload\s*[/>]/.test(code(f)))
    expect(screens, 'if Upload is mounted again, delete this test').toEqual([])
  })

  it('Publish still handles the list nothing populates any more', () => {
    // certifiedDocs was written only by that panel. It is still READ by Publish, which defaults it
    // to [] — so the effect is that externally-certified documents never appear there, which is a
    // consequence of removing upload rather than a fault. Pinned so the empty default is not
    // "tidied" away later on the assumption something fills it.
    expect(read('Publish.jsx')).toMatch(/certified = \[\]/)
    expect(code('App.jsx')).toMatch(/certified=\{certifiedDocs\}/)
  })

  it('the workspace reset still has the setter it calls', () => {
    // Narrowing the destructure to `const [certifiedDocs]` made resetWorkspace's
    // setCertifiedDocs([]) a ReferenceError. Caught before it shipped; pinned so it cannot come
    // back the next time someone notices the setter "looks unused".
    const s = code('App.jsx')
    expect(s).toMatch(/const \[certifiedDocs, setCertifiedDocs\] = useState\(\[\]\)/)
    expect(s).toMatch(/setCertifiedDocs\(\[\]\)/)
  })
})
