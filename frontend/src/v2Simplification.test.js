import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The v2 redesign's first rule is that the app stops being busy. That is a claim about what
// is ABSENT, and absence is exactly what no other test can notice: re-adding a tab breaks
// nothing, so it would come back one convenience at a time and nobody would see a failure.
//
// Source-level rather than rendered, deliberately. Mounting <App> to prove a tab is missing
// needs the whole provider/mock stack, and a mount that silently fails to render the tab bar
// at all would PASS such a test — the strongest possible false green for an assertion about
// absence. Reading the source is the same posture drawerFindingsClaim.test.jsx takes with CSS.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('v2 simplification: removed surfaces stay removed', () => {
  it('has no Upload tab in the workflow nav', () => {
    const app = read('App.jsx')
    // The TABS table is the nav. A row for upload is what put it in the tab bar.
    expect(app).not.toMatch(/\[\s*'upload'\s*,/)
    expect(app).not.toMatch(/view === 'upload'/)
    // …and it must not creep back into the default privilege list either, which is what
    // decides whether a tab is offered at all.
    const allow = app.match(/allow:\s*\[([^\]]*)\]/)
    expect(allow, 'default allow list not found in App.jsx').toBeTruthy()
    expect(allow[1]).not.toContain("'upload'")
  })

  // SUPERSEDED 2026-08-21. This case read "keeps the ad-hoc file path, folded into Discover" and
  // asserted that Upload was still mounted there. Its reasoning was sound and is worth preserving
  // verbatim, because it is the thing that changed rather than the thing that was wrong:
  //
  //     Removing the TAB must not remove the CAPABILITY — that would be a feature deletion
  //     wearing a simplification's clothes. Upload still ships, one level down.
  //
  // v2 removed the Upload TAB (#151) and deliberately kept the capability one level down, as the
  // "Assess a single file · without connecting a source" panel on Discover. On 2026-08-21 the owner
  // asked for that panel to be removed, having been told it was the app's only mount of Upload and
  // that removing it takes ad-hoc single-file assessment out of the product.
  //
  // So this is now a feature deletion, openly, rather than one wearing a simplification's clothes —
  // which is exactly the distinction the original case existed to force. The assertion is inverted
  // rather than deleted, so the decision stays visible and reversible.
  //
  // Upload.jsx is NOT deleted. discoverUploadRemoved.test.jsx records that it is mounted nowhere.
  it('no longer offers the ad-hoc file path — removed on request, not simplified away', () => {
    expect(existsSync(join(HERE, 'Upload.jsx')), 'the component is kept, so this is one commit to reverse').toBe(true)
    expect(read('Discover.jsx')).not.toContain("import Upload from './Upload.jsx'")
    expect(read('Discover.jsx')).not.toMatch(/<Upload\b/)
  })

  it('has no Validation coverage, Business ontology or Permissions tab in Settings', () => {
    const s = read('Settings.jsx')
    for (const label of ['Validation coverage', 'Business ontology', 'Permissions']) {
      expect(s, `Settings.jsx still offers "${label}"`).not.toContain(`>${label}</button>`)
    }
    for (const key of ['validation', 'ontology', 'permissions']) {
      expect(s, `Settings.jsx still renders the '${key}' panel`).not.toMatch(
        new RegExp(`tab === '${key}'`))
    }
  })

  it('drops What’s Changed from Overview', () => {
    expect(read('Overview.jsx')).not.toContain('WhatsChanged')
  })

  it('deletes the components nothing imports any more', () => {
    // Left on disk they are dead weight in a redesign whose whole complaint is component
    // count — and dead components get re-imported by whoever greps for a name.
    for (const f of ['WcagCoverage.jsx', 'Ontology.jsx', 'WhatsChanged.jsx']) {
      expect(existsSync(join(HERE, f)), `${f} should have been deleted`).toBe(false)
    }
  })

  it('keeps RolePrivilege.jsx, because the panel and the loader are different things', () => {
    // The Permissions EDITOR is gone; loadRolePrivileges still gates me.allow and is imported
    // by App.jsx. Deleting the file to "finish the job" would take the gate with it.
    expect(existsSync(join(HERE, 'RolePrivilege.jsx'))).toBe(true)
    expect(read('App.jsx')).toContain("loadRolePrivileges")
  })

  it('leaves the ontology DATA path intact', () => {
    // Only the editor left. App still annotates the corpus from whatever was last published,
    // and the PDF report still describes it — removing those was never asked for.
    expect(read('App.jsx')).toContain('loadPublished')
    expect(existsSync(join(HERE, 'ontology.js'))).toBe(true)
  })
})
