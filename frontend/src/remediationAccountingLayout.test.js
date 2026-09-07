import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'remediation-reconciliation.css'), 'utf8')

describe('remediation accounting layout', () => {
  it('gives the KPI band the full component width', () => {
    expect(css).toMatch(/\.remops-reconciliation\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column/s)
    expect(css).toMatch(/\.remops-reconciliation > dl\s*\{[^}]*width:\s*100%/s)
    expect(css).toMatch(/grid-template-columns:\s*repeat\(5, minmax\(0, 1fr\)\)/)
  })

  it('uses a professional proportional face and responsive KPI grids', () => {
    expect(css).toMatch(/\.remops-reconciliation dd\s*\{[^}]*font-family:\s*-apple-system/s)
    expect(css).toMatch(/max-width:\s*1050px[\s\S]*repeat\(3, minmax\(0, 1fr\)\)/)
    expect(css).toMatch(/max-width:\s*760px[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/)
    expect(css).toMatch(/max-width:\s*480px[\s\S]*grid-template-columns:\s*1fr/)
  })
})
