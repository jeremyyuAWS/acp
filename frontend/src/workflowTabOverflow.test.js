import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'styles.css'), 'utf8')

describe('workflow tab overflow', () => {
  it('keeps every tab reachable in one horizontal strip at narrow widths', () => {
    const strip = css.match(/\.tabs\s*\{([^}]+)\}/)?.[1] || ''
    expect(strip).toContain('overflow-x: auto')
    expect(strip).toContain('overflow-y: hidden')
    expect(strip).toContain('max-width: 100%')
    expect(strip).toContain('scrollbar-width: thin')
  })

  it('does not shrink individual tabs until their labels become unreadable', () => {
    const tab = css.match(/\.tab\s*\{([^}]+)\}/)?.[1] || ''
    expect(tab).toContain('flex: 0 0 auto')
    expect(tab).toContain('scroll-snap-align: start')
  })
})
