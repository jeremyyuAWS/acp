import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import EstateProgressPanel from './EstateProgressPanel.jsx'
import EstateCoverage from './EstateCoverage.jsx'
import { handleWorkflowTabKeyDown } from './workflowTabs.js'
import { readFileSync } from 'node:fs'

afterEach(unmountAll)

describe('FastPass production regressions', () => {
  it('keeps pending-work table rows semantic and puts the action on one button', async () => {
    const onGo = vi.fn()
    const { root, container } = createTestRoot()
    await act(async () => root.render(createElement(EstateProgressPanel, {
      inventory: { discovered: 10, assessment_eligible: 4 }, analysed: 1, needFix: 1,
      certifiable: 0, published: 0, errorCount: 0, files: [], estateFiles: [], onGo,
    })))
    const pending = [...container.querySelectorAll('section')]
      .find((node) => node.getAttribute('aria-label') === 'Pending work by stage')
    expect(pending.querySelector('tr[role="button"]')).toBeNull()
    const review = [...pending.querySelectorAll('button')].find((button) => button.textContent.includes('Review exclusions'))
    expect(review).toBeTruthy()
    expect(review.getAttribute('aria-label')).toContain('6 pending in Eligibility review')
    await act(async () => review.click())
    expect(onGo).toHaveBeenCalledWith('discover')
  })

  it('uses the FastPass-compliant text color for estate section headings', async () => {
    const { root, container } = createTestRoot()
    await act(async () => root.render(createElement(EstateCoverage, {
      inventory: { discovered: 10, assessment_eligible: 4, by_age: { under_1_year: 10 } },
    })))
    const headings = [...container.querySelectorAll('h4')]
    expect(headings.length).toBeGreaterThan(0)
    for (const heading of headings) expect(heading.style.color).toBe('var(--muted-text, #6f727a)')
  })

  it('keeps every review-queue badge severity on a contrast-safe palette', () => {
    const css = readFileSync('src/styles.css', 'utf8')
    expect(css).toMatch(/\.hitlbell-high \.hitlbell-badge \{ background: #C5452C; \}/)
    expect(css).toMatch(/\.hitlbell-medium \.hitlbell-badge \{ background: #8A5A00; \}/)
    expect(css).toMatch(/\.hitlbell-low \.hitlbell-badge \{ background: #596579; \}/)
  })

  it('moves and activates tabs with arrows while skipping disabled tabs', () => {
    const tablist = document.createElement('div')
    tablist.setAttribute('role', 'tablist')
    const tabs = ['Overview', 'Discover', 'Assess'].map((label) => {
      const button = document.createElement('button')
      button.setAttribute('role', 'tab')
      button.textContent = label
      tablist.append(button)
      return button
    })
    tabs[1].disabled = true
    document.body.append(tablist)
    const click = vi.spyOn(tabs[2], 'click')
    const preventDefault = vi.fn()
    handleWorkflowTabKeyDown({ key: 'ArrowRight', currentTarget: tabs[0], preventDefault })
    expect(document.activeElement).toBe(tabs[2])
    expect(click).toHaveBeenCalledOnce()
    expect(preventDefault).toHaveBeenCalledOnce()
    tablist.remove()
  })
})
