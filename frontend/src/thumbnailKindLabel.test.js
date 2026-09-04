import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('P2 — "Describe THIS image" context-aware zoom label (ADR 0018 Slice 3 extension)', () => {
  it('Thumbnail accepts a kindLabel prop and defaults it to null', () => {
    const src = read('Thumbnail.jsx')
    expect(src).toMatch(/kindLabel\s*=\s*null/)
  })

  it('zoom button reads "Zoom to <kind>" when kindLabel is given, "Zoom to object" otherwise', () => {
    const src = read('Thumbnail.jsx')
    expect(src).toMatch(/kindLabel \? `⤢ Zoom to \$\{kindLabel\}`/)
    expect(src).toMatch(/'⤢ Zoom to object'/)
  })

  it('zoom button reads "Hide <kind>" when zoomed and kindLabel given, "Hide close-up" otherwise', () => {
    const src = read('Thumbnail.jsx')
    expect(src).toMatch(/kindLabel \? `Hide \$\{kindLabel\}`/)
    expect(src).toMatch(/'Hide close-up'/)
  })

  it('crop figure aria-label names the kind when given, falls back to generic', () => {
    const src = read('Thumbnail.jsx')
    expect(src).toMatch(/kindLabel \? `Close-up of the flagged \$\{kindLabel\}`/)
    expect(src).toMatch(/'Close-up of the flagged object'/)
  })

  it('EvidenceCard passes kindLabel derived from imgKind to the hero Thumbnail', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/kindLabel=\{imgKind\?\.label\?\.toLowerCase\(\)/)
  })
})
