import { describe, it, expect, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

const { default: CoverageScorecard } = await import('./CoverageScorecard.jsx')

let container, root
beforeEach(() => { container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container) })

const render = async (files) => { await act(async () => { root.render(createElement(CoverageScorecard, { files })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

describe('CoverageScorecard renders the capability view', () => {
  it('an all-.xlsx estate shows 11 assessable (gaps closed), scoped to .xlsx', async () => {
    await render([{ file: 'book.xlsx', type: 'xlsx' }])
    const txt = container.textContent
    expect(txt).toContain('what we can assess')
    expect(txt).toContain('.xlsx')                 // scoped to the estate's file type
    expect(txt).toContain('Assessable')
    // headline numbers present — xlsx is now fully covered for what applies
    expect(txt).toContain('11')
    expect(txt).toContain('deterministic')
  })

  it('expands an .html estate showing the assessable set and the needs-AT keyboard criteria', async () => {
    await render([{ file: 'page.html', type: 'html' }])
    await click(btnByText('Show all'))
    const txt = container.textContent
    expect(txt).toContain('1.4.3')                 // an assessable criterion
    expect(txt).toContain('2.1.1')                 // a keyboard criterion
    expect(txt).toContain('needs AT testing')       // the AT rendering path (no gaps remain)
  })

  it('toggling to all-document criteria grows the total beyond 20', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    expect(container.textContent).toContain('20-core')
    await click(btnByText('20-core'))              // switch off documents → all document criteria
    // /N shows a total > 20 somewhere in the stat denominators
    expect(/\/(2[1-9]|[3-9]\d)/.test(container.textContent)).toBe(true)
  })
})
