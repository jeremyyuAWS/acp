import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// FileTypeConfig CLAIMED to exclude types from "the remediation queue and scoring". It did not:
// every consumer traced back to Discover, where it filtered the visible rows and nothing else.
// An operator who switched DOCX off believed DOCX was excluded from remediation, and then got
// remediation proposals for it.
//
// Meanwhile scan_scope's format axis gates assessment for real, server-side, in _rule_outcome.
// Two controls, one apparent question, and only one of them did anything.
//
// The four document formats now write scan_scope. The rest stay a Discover view filter, because
// the engine has no scope axis for them — and the panel says which is which instead of claiming
// one behaviour for both.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')
const SRC = () => read('FileTypeConfig.jsx')

describe('the four document formats are gated for real', () => {
  it('writes scan_scope rather than only localStorage', () => {
    const s = SRC()
    expect(s).toContain("import { getSettings, updateSettings } from './api.js'")
    expect(s).toMatch(/updateSettings\(\{ scan_scope:/)
  })

  it('reads their state from the server, not from localStorage', () => {
    // Two stores for one fact is what made this panel lie. The scoped formats have exactly one
    // source of truth now, and it is the one the engine reads.
    const s = SRC()
    expect(s).toMatch(/getSettings\(\)\.then/)
    expect(s).toMatch(/parseStoredScope\(st\?\.scan_scope/)
  })

  it('builds the scope from the GENERATED universe, never a typed list', () => {
    // SCOPE_UNIVERSE is emitted from the backend's own tables with a CI drift guard, so this
    // cannot offer or withhold a pair the engine does not have.
    const s = SRC()
    expect(s).toContain("import { SCOPE_UNIVERSE } from './scopePresets.js'")
    expect(s).not.toMatch(/\[\s*'1\.1\.1'\s*,/)
  })

  it('refuses to save an empty selection', () => {
    // `{}` means NO RESTRICTION on the backend, so an all-off panel would assess everything
    // while showing everything off — the exact inversion ScanScope.jsx refuses.
    const s = SRC()
    expect(s).toMatch(/allowed\.size === 0/)
    expect(s).toMatch(/no restriction/i)
  })

  it('trusts the server echo, not its own request', () => {
    // SIM builds its response from the request, so a request-shaped answer must never read as
    // a save.
    expect(SRC()).toMatch(/res\?\.simulated/)
  })

  it('cannot fire two scope writes at once', () => {
    // These send a full scope map; two racing clicks would let arrival order decide the result.
    const s = SRC()
    expect(s).toMatch(/disabled=\{busy\}/)
  })
})

describe('the view-only types keep their old behaviour', () => {
  it('html, video and audio do not write the server', () => {
    // gen_scope_presets.py excludes html from _DOC_FORMATS deliberately ("this configures a
    // DOCUMENT engagement") and never had video/audio. A toggle that wrote nothing while
    // claiming to gate would be the original bug again, pointing the other way.
    const s = SRC()
    expect(s).toMatch(/SCOPED_EXTS = new Set\(\['pdf', 'docx', 'pptx', 'xlsx'\]\)/)
    expect(s).toMatch(/if \(!SCOPED_EXTS\.has\(ext\)\)/)
  })
})

describe('the panel says what each control actually does', () => {
  it('no longer claims the local toggles gate remediation', () => {
    const s = SRC()
    expect(s).not.toContain('toggling off only removes them from the remediation queue and scoring')
  })

  it('says the scoped toggles are platform-wide, not per-browser', () => {
    // The one property an operator would otherwise get wrong: this is a localStorage-shaped
    // control that now changes what everyone gets.
    expect(SRC()).toMatch(/platform-wide setting, not a preference for this browser/)
  })

  it('warns that switching one off from an unrestricted state creates an explicit scope', () => {
    // Going from "no restriction" to a map means a criterion added in a later release is not
    // picked up automatically. That is a real consequence of a single click.
    expect(SRC()).toMatch(/restricted === false/)
    expect(SRC()).toMatch(/not picked up automatically/)
  })
})
