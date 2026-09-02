import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

describe('full document preview', () => {
  it('requests a page render even when a finding has no element coordinates', () => {
    const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'RemediationPreview.jsx'), 'utf8')
    const pageView = src.slice(src.indexOf('function PageView'), src.indexOf('// One label/value line'))
    expect(pageView).toMatch(/if \(scanId\)/)
    expect(pageView).not.toMatch(/if \(scanId && hasVisualAnchor\(f\)\)/)
    expect(pageView).toMatch(/<Thumbnail scanId=\{scanId\}/)
  })
})
