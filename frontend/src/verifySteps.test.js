import { describe, it, expect } from 'vitest'
import { verifySteps, appFor, defaultPlatform } from './verifySteps.js'

describe('appFor', () => {
  it('maps extensions to the native app', () => {
    expect(appFor('report.docx')).toBe('Word')
    expect(appFor('data.xlsx')).toBe('Excel')
    expect(appFor('deck.pptx')).toBe('PowerPoint')
    expect(appFor('brief.pdf')).toBe('Acrobat')
    expect(appFor('page.html')).toBe(null)
    expect(appFor('')).toBe(null)
  })
})

describe('verifySteps', () => {
  it('gives app-specific steps for a criterion with a native path', () => {
    const info = verifySteps('1.1.1', 'x.docx', 'win')
    expect(info.app).toBe('Word')
    expect(info.steps.length).toBeGreaterThan(0)
    expect(info.steps.join(' ')).toMatch(/Alt Text/i)
    expect(info.checker).toMatch(/Check Accessibility/i)
  })

  it('changes with the platform (mac vs win) for language', () => {
    const win = verifySteps('3.1.1', 'x.docx', 'win')
    const mac = verifySteps('3.1.1', 'x.docx', 'mac')
    expect(win.steps.join(' ')).toMatch(/Review ▸ Language/i)   // Windows path
    expect(mac.steps.join(' ')).toMatch(/Tools ▸ Language/i)    // macOS path
    expect(win.steps).not.toEqual(mac.steps)
  })

  it('falls back to only the checker line when there is no crisp native step', () => {
    // 1.4.5 (images-of-text) has no one-click Office check → steps null, checker present.
    const info = verifySteps('1.4.5', 'x.docx', 'win')
    expect(info.steps).toBe(null)
    expect(info.checker).toMatch(/Check Accessibility/i)
  })

  it('returns null for an unknown file format', () => {
    expect(verifySteps('1.1.1', 'page.html', 'win')).toBe(null)
    expect(verifySteps('1.1.1', 'weird.zip', 'win')).toBe(null)
  })

  it('gives Acrobat the bookmark path for PDF 2.4.1', () => {
    const info = verifySteps('2.4.1', 'x.pdf', 'win')
    expect(info.app).toBe('Acrobat')
    expect(info.steps.join(' ')).toMatch(/Bookmark/i)
  })
})

describe('defaultPlatform', () => {
  it('returns mac or win', () => {
    expect(['mac', 'win']).toContain(defaultPlatform())
  })
})
