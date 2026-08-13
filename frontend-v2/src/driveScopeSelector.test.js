import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The Google Drive file-browser panel must offer the same "which criteria & formats to assess"
// control the Discover and Overview surfaces already do, so a tester who connects Drive and scans
// straight from the file list still gets to set scope first — the gap that made scope selection
// look SharePoint-only. It is wired by rendering <ScanScope/> inside the connected panel: the same
// self-contained editor that persists to the `scan_scope` setting, which the "Scan selected" run
// inherits server-side. No per-scan plumbing, exactly as from Discover.
//
// Source-level and COMMENT-STRIPPED, matching how this repo already tests GoogleDrive
// (driveArchive.test.js): the component is GIS-token-gated so it is asserted at the source level,
// and a naive substring match would also hit this very comment — so assert against code lines only.
const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) =>
  readFileSync(join(HERE, f), 'utf8')
    .split('\n')
    .filter((l) => {
      const t = l.trim()
      return !t.startsWith('//') && !t.startsWith('/*') && !t.startsWith('*') && !t.startsWith('{/*')
    })
    .join('\n')

describe('Drive browse panel offers the scope selector', () => {
  it('imports the shared ScanScope editor', () => {
    expect(code('GoogleDrive.jsx')).toMatch(/import ScanScope from '\.\/ScanScope\.jsx'/)
  })

  it('renders <ScanScope /> in the panel', () => {
    expect(code('GoogleDrive.jsx')).toMatch(/<ScanScope\s*\/>/)
  })

  // The v1 and v2 GoogleDrive.jsx are kept byte-identical (driveArchive.test.js), so the selector
  // must be present in both — a change to one without the other would fail parity anyway, but this
  // makes the intent explicit rather than incidental.
  it('is present in the v1 copy too', () => {
    const v1 = readFileSync(join(HERE, '..', '..', 'frontend', 'src', 'GoogleDrive.jsx'), 'utf8')
    expect(v1).toMatch(/<ScanScope\s*\/>/)
  })
})
