import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const api = readFileSync(join(here, 'api.js'), 'utf8')
const publish = readFileSync(join(here, 'Publish.jsx'), 'utf8')

describe('Release ZIP package', () => {
  it('posts selected names through the authenticated API and saves one ZIP', () => {
    expect(api).toMatch(/export const downloadReleasePackage = \(scanId, files, packageName = ''\)/)
    expect(api).toMatch(/\/release\/package/)
    expect(api).toMatch(/headers: headers\(\{ 'Content-Type': 'application\/json' \}\)/)
    expect(api).toMatch(/package_name: packageName\.trim\(\)/)
    expect(api).toMatch(/requestedName \? `\$\{requestedName\}\.zip`/)
  })

  it('explains the package contents before download', () => {
    expect(publish).toMatch(/one ZIP package with the source folder structure and a release manifest/i)
    expect(publish).toMatch(/\.zip” with folder structure and a manifest/)
    expect(publish).toMatch(/Download ZIP \(\$\{selectedReady\.length\}\)/)
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
