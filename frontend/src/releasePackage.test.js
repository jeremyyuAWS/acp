import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const api = readFileSync(join(here, 'api.js'), 'utf8')
const publish = readFileSync(join(here, 'Publish.jsx'), 'utf8')

describe('Release ZIP package', () => {
  it('posts selected names through the authenticated API and saves one ZIP', () => {
    expect(api).toMatch(/export const downloadReleasePackage = \(scanId, files\)/)
    expect(api).toMatch(/\/release\/package/)
    expect(api).toMatch(/headers: headers\(\{ 'Content-Type': 'application\/json' \}\)/)
    expect(api).toMatch(/body: JSON\.stringify\(\{ files \}\)/)
    expect(api).toMatch(/a\.download = match\?\.\[1\] \|\| `acp-release-\$\{scanId\}\.zip`/)
  })

  it('explains the package contents before download', () => {
    expect(publish).toMatch(/One ZIP with the source folder structure and a release manifest/)
    expect(publish).toMatch(/packaged in one ZIP with folder structure and a manifest/)
    expect(publish).toMatch(/Download ZIP \(\$\{selectedReady\.length\}\)/)
  })
})
