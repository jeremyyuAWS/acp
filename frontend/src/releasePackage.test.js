import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const api = readFileSync(join(here, 'api.js'), 'utf8')
const publish = readFileSync(join(here, 'Publish.jsx'), 'utf8')

describe('Release ZIP package', () => {
  it('posts selected names through the authenticated API and saves one ZIP', () => {
    expect(api).toMatch(/export const previewReleasePackage/)
    expect(api).toMatch(/release\/package\/preview/)
    expect(api).toMatch(/export const downloadReleasePackage = \(scanId, files, packageName = '', options = \{\}\)/)
    expect(api).toMatch(/\/release\/package/)
    expect(api).toMatch(/headers: headers\(\{ 'Content-Type': 'application\/json' \}\)/)
    expect(api).toMatch(/package_name: packageName\.trim\(\)/)
    expect(api).toMatch(/downloadFormat === 'original'/)
    expect(api).toMatch(/preserve_hierarchy: options\.preserveHierarchy !== false/)
    expect(api).toMatch(/include_manifest: options\.includeManifest !== false/)
  })

  it('explains the package contents before download', () => {
    expect(publish).toMatch(/one ZIP package with the source folder structure and a release manifest/i)
    expect(publish).toMatch(/preserveHierarchy \? ' with the source folder structure' : ' in one flat folder'/)
    expect(publish).toMatch(/Download ZIP \(\$\{selectedReady\.length\}\)/)
    expect(publish).toMatch(/Download corrected file/)
    expect(publish).toMatch(/Include release manifest with checksums/)
    expect(publish).toMatch(/Also download scope-limited verification report/)
    expect(publish).toMatch(/Download preview/)
    expect(publish).toMatch(/packagePreview\.blockers/)
  })

  it('collects and validates package or destination names before review', () => {
    expect(publish).toMatch(/ZIP filename/)
    expect(publish).toMatch(/Release folder name/)
    expect(publish).toMatch(/validateDeliveryName/)
    expect(publish).toMatch(/disabled=\{Boolean\(deliveryNameError\) \|\| previewingRelease\}/)
    expect(publish).toMatch(/folderName: releasePreview\?\.folder_name \|\| releaseFolder\?\.name \|\| releaseFolderName\.trim\(\)/)
    expect(publish).toMatch(/retries keep the same destination/)
    expect(publish).toMatch(/Release folder: “\{confirm\.folderName\}”/)
  })
})
