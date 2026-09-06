import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const publish = readFileSync(join(here, 'Publish.jsx'), 'utf8')
const api = readFileSync(join(here, 'api.js'), 'utf8')

describe('authoritative release manifest', () => {
  it('downloads the persisted server manifest instead of rebuilding release evidence in the browser', () => {
    expect(api).toMatch(/export const getReleaseManifest/)
    expect(api).toMatch(/\/release\/manifest/)
    expect(publish).toMatch(/await getReleaseManifest\(run\.id\)/)
    expect(publish).not.toMatch(/documents:\s*Object\.values\(releaseResults\)/)
  })

  it('surfaces a download failure instead of silently producing incomplete JSON', () => {
    expect(publish).toMatch(/setManifestError/)
    expect(publish).toMatch(/role="alert"/)
  })
})
