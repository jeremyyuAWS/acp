import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const api = readFileSync(join(here, 'api.js'), 'utf8')
const publish = readFileSync(join(here, 'Publish.jsx'), 'utf8')

describe('Release destination preview', () => {
  it('uses an authenticated read-only preview before the review step', () => {
    expect(api).toMatch(/export const previewReleaseDestination/)
    expect(api).toMatch(/\/release\/preview/)
    expect(publish).toMatch(/await previewReleaseDestination/)
    expect(publish).toMatch(/Checking destination…/)
    expect(publish).toMatch(/setBuilderStep\(3\)/)
  })

  it('shows exact paths, create-or-reuse behavior, and collision blockers', () => {
    expect(publish).toMatch(/Exact destination preview/)
    expect(publish).toMatch(/item\.destination_path/)
    expect(publish).toMatch(/item\.action === 'reuse'/)
    expect(publish).toMatch(/releasePreview\.collision_policy/)
    expect(publish).toMatch(/releasePreview\.blockers/)
    expect(publish).toMatch(/!releasePreview\?\.can_release/)
  })

  it('carries the previewed folder into the actual publish request', () => {
    expect(publish).toMatch(/folderName: releasePreview\?\.folder_name/)
  })
})
