import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The "could not be read" KPI on Discover is the exact example this feature was asked for — pins
// that it's actually wrapped with the glossary tooltip, not just that Term.jsx exists somewhere.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'DiscoveryResults.jsx'), 'utf8')

describe('the "could not be read" stat carries its glossary definition', () => {
  it('imports Term and wraps the unreadable label with it', () => {
    expect(src).toMatch(/import Term from '\.\/Term\.jsx'/)
    expect(src).toMatch(/<Term k="unreadable">could not be read<\/Term>/)
  })
})
