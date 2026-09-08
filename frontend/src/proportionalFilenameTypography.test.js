import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(join(here, 'styles.css'), 'utf8')
const lifecycle = readFileSync(join(here, 'LifecycleEvidencePanel.jsx'), 'utf8')
const reconciliation = readFileSync(join(here, 'remediation-reconciliation.css'), 'utf8')

describe('document-name typography', () => {
  it('uses the proportional product face for human-facing document names', () => {
    for (const selector of ['fname', 'assessfname', 'alname']) {
      expect(styles).toMatch(new RegExp(`\\.${selector}\\s*\\{[^}]*font-family:\\s*inherit`, 's'))
    }
    expect(lifecycle).toContain('<b className="fname">{file.file}</b>')
  })

  it('keeps actual machine paths and identifiers monospace', () => {
    expect(styles).toMatch(/\.machine-value\s*\{[^}]*font-family:\s*var\(--font-mono\)/s)
    expect(lifecycle).toContain('className="muted machine-value">{file.path')
  })

  it('lets reconciliation cards inherit the same application typeface', () => {
    expect(reconciliation).not.toMatch(/-apple-system|BlinkMacSystemFont|Segoe UI|Roboto/)
    expect(reconciliation.match(/font-family:\s*inherit/g)).toHaveLength(3)
  })
})
