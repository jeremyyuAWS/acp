/**
 * WCAG CSS variable-usage regression guard.
 *
 * These tests verify that selectors which previously used failing hard-coded hex
 * colors now reference semantic CSS custom properties.  A regression here means
 * someone changed a selector back to a literal — the WCAG-mode override in
 * [data-wcag="on"] then silently stops working even though the UI renders fine in
 * the standard palette.
 *
 * How it works: styles.css is read as text and the relevant selector rules are
 * scanned for the expected `var(--token)` reference.  No DOM or React mount is
 * needed because we are auditing source text, not computed styles.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const css = readFileSync(
  resolve(import.meta.dirname, 'styles.css'),
  'utf8',
)

describe('semantic token usage — selectors must not hard-code colors that have a variable', () => {
  it('.atile-den uses var(--text-secondary) — not the literal #9aa2ac', () => {
    expect(css).toContain('.atile .atile-den')
    // the line must reference the variable, not the old literal
    const match = css.match(/\.atile \.atile-den\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--text-secondary)')
    expect(match[0]).not.toContain('#9aa2ac')
  })

  it('.assesslist li.pending .alstate uses var(--text-disabled) — not #B9B4C0', () => {
    const match = css.match(/\.assesslist li\.pending \.alstate\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--text-disabled)')
    expect(match[0]).not.toContain('#B9B4C0')
    expect(match[0]).not.toContain('#b9b4c0')
  })

  it('.covlvl uses var(--muted) — not the hardcoded #6c6470 that would bypass the WCAG toggle', () => {
    const match = css.match(/\.covlvl\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--muted)')
    // The literal must not appear (except as a comment or the :root definition)
    const covlvlLine = css.split('\n').find(l => l.includes('.covlvl {') || l.includes('.covlvl{'))
    if (covlvlLine) {
      expect(covlvlLine).not.toContain('#6c6470')
    }
  })

  it('global :focus-visible uses var(--focus-ring) — not a hardcoded hex', () => {
    // The global rule must reference the variable, not a literal colour.
    const match = css.match(/:focus-visible\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--focus-ring)')
    expect(match[0]).not.toMatch(/#[0-9a-fA-F]{6}/)
  })

  it('[data-wcag="on"] block overrides --text-secondary and --text-disabled', () => {
    const wcagBlock = css.match(/\[data-wcag="on"\]\s*\{[^}]+\}/)
    expect(wcagBlock).not.toBeNull()
    expect(wcagBlock[0]).toContain('--text-secondary')
    expect(wcagBlock[0]).toContain('--text-disabled')
  })

  it('--muted-fg is defined in :root (so JSX fallbacks resolve to --muted, not #8a8f98)', () => {
    const rootBlock = css.match(/:root\s*\{[\s\S]+?\}/)
    expect(rootBlock).not.toBeNull()
    expect(rootBlock[0]).toContain('--muted-fg')
  })

  it('--focus-ring is defined in :root', () => {
    const rootBlock = css.match(/:root\s*\{[\s\S]+?\}/)
    expect(rootBlock).not.toBeNull()
    expect(rootBlock[0]).toContain('--focus-ring')
  })

  it('--text-secondary is defined in :root', () => {
    const rootBlock = css.match(/:root\s*\{[\s\S]+?\}/)
    expect(rootBlock).not.toBeNull()
    expect(rootBlock[0]).toContain('--text-secondary')
  })

  it('--text-disabled is defined in :root', () => {
    const rootBlock = css.match(/:root\s*\{[\s\S]+?\}/)
    expect(rootBlock).not.toBeNull()
    expect(rootBlock[0]).toContain('--text-disabled')
  })
})

describe('status-token definitions in :root — must not regress to hard-coded values', () => {
  // Pin that the canonical hex values live in the token, not scattered through rules.
  // These tests fail if someone removes the token from :root or changes its value.
  it('--success-fg is defined in :root as #3B6D11', () => {
    expect(css).toMatch(/--success-fg:\s*#3B6D11/)
  })
  it('--success-fg-strong is defined in :root as #2F5310', () => {
    expect(css).toMatch(/--success-fg-strong:\s*#2F5310/)
  })
  it('--success-bg is defined in :root as #E7F0DC', () => {
    expect(css).toMatch(/--success-bg:\s*#E7F0DC/)
  })
  it('--warn-fg is defined in :root as #854F0B', () => {
    expect(css).toMatch(/--warn-fg:\s*#854F0B/)
  })
  it('--warn-bg is defined in :root as #FAEEDA', () => {
    expect(css).toMatch(/--warn-bg:\s*#FAEEDA/)
  })
  it('--info-fg is defined in :root as #1F5FA8', () => {
    expect(css).toMatch(/--info-fg:\s*#1F5FA8/)
  })
  it('--info-bg is defined in :root as #E2EDFB', () => {
    expect(css).toMatch(/--info-bg:\s*#E2EDFB/)
  })
  it('--error-fg is defined in :root as #B43A2A', () => {
    expect(css).toMatch(/--error-fg:\s*#B43A2A/)
  })
  it('--error-fg-strong is defined in :root as #A32D2D', () => {
    expect(css).toMatch(/--error-fg-strong:\s*#A32D2D/)
  })

  // Pin that the migrated selectors use tokens, not literal hex
  it('.readywarn uses var(--warn-fg) and var(--warn-bg) — not hard-coded hex', () => {
    const match = css.match(/\.readywarn\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--warn-fg)')
    expect(match[0]).toContain('var(--warn-bg)')
    expect(match[0]).not.toMatch(/#854F0B/i)
    expect(match[0]).not.toMatch(/#FAEEDA/i)
  })

  it('.err uses var(--info-fg) and var(--info-bg) — not hard-coded hex', () => {
    const match = css.match(/\.err\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--info-fg)')
    expect(match[0]).toContain('var(--info-bg)')
    expect(match[0]).not.toMatch(/#1F5FA8/i)
    expect(match[0]).not.toMatch(/#E2EDFB/i)
  })

  it('.certtitle uses var(--success-fg) — not hard-coded hex', () => {
    const match = css.match(/\.certtitle\s*\{[^}]+\}/)
    expect(match).not.toBeNull()
    expect(match[0]).toContain('var(--success-fg)')
    expect(match[0]).not.toMatch(/#3B6D11/i)
  })
})

describe('standard-mode token values must not have drifted', () => {
  it('--muted standard value is #6c6470', () => {
    expect(css).toMatch(/--muted:\s*#6c6470/)
  })
  it('--bg standard value is #faf8fb', () => {
    expect(css).toMatch(/--bg:\s*#faf8fb/)
  })
  it('--plum standard value is #46303F', () => {
    expect(css).toMatch(/--plum:\s*#46303F/)
  })
  it('--ink standard value is #2b2330', () => {
    expect(css).toMatch(/--ink:\s*#2b2330/)
  })
})
