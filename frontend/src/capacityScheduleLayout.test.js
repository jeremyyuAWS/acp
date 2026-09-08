import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'capacity-schedule.css'), 'utf8')

describe('scheduling workspace visual contract', () => {
  it('uses a distinct elevated editor with a sticky action footer', () => {
    expect(css).toMatch(/\.capacity-editor\s*\{[^}]*box-shadow:/s)
    expect(css).toMatch(/\.capacity-editor__footer\s*\{[^}]*position:\s*sticky[^}]*bottom:\s*0/s)
  })

  it('renders a seven-day preview and collapses cleanly on narrow screens', () => {
    expect(css).toMatch(/\.capacity-week__days\s*\{[^}]*repeat\(7,/s)
    expect(css).toMatch(/max-width:\s*720px[\s\S]*\.capacity-week__days\s*\{[^}]*repeat\(4,/s)
    expect(css).toMatch(/max-width:\s*720px[\s\S]*\.capacity-steps\s*\{[^}]*grid-template-columns:\s*1fr/s)
  })

  it('honors reduced-motion preferences', () => {
    expect(css).toMatch(/prefers-reduced-motion:\s*reduce/)
  })
})
