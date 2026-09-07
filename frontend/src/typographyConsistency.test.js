import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const root = path.dirname(new URL(import.meta.url).pathname)

describe('machine-value typography across workflow tabs', () => {
  it('defines one complete monospace stack and a reusable numeric utility', () => {
    const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8')
    expect(css).toMatch(/--font-mono:\s*ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas/)
    expect(css).toMatch(/\.machine-value[^}]+font-family:\s*var\(--font-mono\)/s)
    expect(css).toMatch(/\.machine-value[^}]+font-variant-numeric:\s*tabular-nums/s)
  })

  it('uses the shared token instead of tab-specific monospace stacks', () => {
    const files = fs.readdirSync(root).filter((name) => name.endsWith('.jsx'))
    const source = files.map((name) => fs.readFileSync(path.join(root, name), 'utf8')).join('\n')
    expect(source).not.toMatch(/fontFamily:\s*['"]monospace['"]/) 
    expect(source).not.toMatch(/fontFamily:\s*['"]ui-monospace/)
    expect(source).not.toContain('var(--mono,')
  })

  it('keeps lifecycle prose sans and applies monospace only to evidence values', () => {
    const panel = fs.readFileSync(path.join(root, 'LifecycleEvidencePanel.jsx'), 'utf8')
    const card = fs.readFileSync(path.join(root, 'CanonicalStageCard.jsx'), 'utf8')
    expect(panel).toContain('className="muted machine-value"')
    expect(card.match(/className="machine-value"/g)).toHaveLength(3)
  })
})
