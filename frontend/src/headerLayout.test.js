import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('compact application header', () => {
  it('moves identity actions into one account menu', () => {
    expect(app).toContain('className="header-menu account-menu"')
    expect(app).toContain('switch account')
    expect(app).toContain('sign out')
    expect(app).toContain('Platform settings')
  })

  it('groups global display controls under Accessibility', () => {
    expect(app).toContain('Accessibility and AI preferences')
    expect(app).toContain('High-contrast palette')
    expect(app).toContain('AI assistance')
  })

  it('keeps consequential workspace context visible', () => {
    expect(app).toContain('className="header-context"')
    expect(app).toContain('documents</span>')
    expect(app).toContain('context-verified')
  })
})
