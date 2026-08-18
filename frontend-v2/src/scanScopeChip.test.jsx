/**
 * The per-scan scope chip (R6 / Phase 3b), DOM-level, mounting the real component.
 *
 * What it guards:
 *   - the chip states WHAT this scan covered from the run's FROZEN `scan_scope` (criteria count +
 *     doc types) AND the file boundary — read from the run, not the live global scope;
 *   - a null `scan_scope` reads as the WHOLE core ("all N criteria"), never as an empty scope;
 *   - the change-scope-&-re-scan affordance is present and its impact estimate quantifies the
 *     criteria the current scope would ADD or DROP vs what this scan used;
 *   - re-scan dispatches the run's source through onScan.
 *
 * activeScope is mocked so the criteria universe and the "current" global scope are deterministic
 * (the real bindings are server-driven live-`let`s). DOM-level, not browser-level: this repo's
 * preview server runs vite rooted at the SHARED checkout whatever worktree you are in, so a browser
 * check of a worktree change exercises code that does not contain it (see CLAUDE.md).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

// Four-criterion core; the "current" agreed scope covers two of them. Chosen so that a scan
// frozen to three criteria drops one and adds none vs the current scope.
vi.mock('./activeScope.js', () => ({
  CORE_SCS: new Set(['1.1.1', '1.4.3', '2.4.4', '2.4.6']),
  SCOPE_SCS: new Set(['1.1.1', '1.4.3']),
  SCOPE_LABEL: 'agreed scope',
}))

const { default: ScanScopeChip } = await import('./ScanScopeChip.jsx')

const RUN = (over = {}) => ({
  id: 'run-1',
  source: 'drive',
  scan_scope: { '1.1.1': ['docx'], '1.4.3': ['docx', 'pdf'], '2.4.4': ['pdf'] },
  scope: { kind: 'folder', folder_name: 'UTSW DEMO V2', kept: 4,
           inventory: { discovered: 10, assessment_eligible: 7 } },
  ...over,
})

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeChip, { run: RUN(), fileCount: 4, onScan: vi.fn(), busy: false, ...props }))
  })
  return container
}

const clickText = async (container, text) => {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))
  expect(btn, `button "${text}" not found`).toBeTruthy()
  await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  return btn
}

describe('ScanScopeChip', () => {
  it('states the frozen criteria scope, its doc types, and the file boundary', async () => {
    const c = await mount()
    const t = c.textContent
    expect(t).toContain('3 of 4 criteria')     // frozen scan_scope, from the run
    expect(t).toContain('docx, pdf')           // union of the map's formats
    expect(t).toContain('UTSW DEMO V2')        // the file boundary (run.scope), reused chip
  })

  it('a null scan_scope reads as the whole core, not an empty scope', async () => {
    const c = await mount({ run: RUN({ scan_scope: null }) })
    expect(c.textContent).toContain('all 4 criteria')
    // and it is NOT flagged as a narrowed scope
    const chip = [...c.querySelectorAll('.scopechip')].find((e) => e.textContent.includes('all 4 criteria'))
    expect(chip.className).not.toContain('narrow')
  })

  it('hides the re-scan panel until the affordance is opened', async () => {
    const c = await mount()
    expect(c.querySelector('.scanscope-rescan')).toBeNull()
    await clickText(c, 'Change scope')
    expect(c.querySelector('.scanscope-rescan')).toBeTruthy()
  })

  it('impact estimate quantifies the criteria the current scope drops, over the affected files', async () => {
    const c = await mount()
    await clickText(c, 'Change scope')
    const panel = c.querySelector('.scanscope-rescan').textContent
    expect(panel).toContain('2')                 // current scope assesses 2 criteria
    expect(panel).toContain('3')                 // this scan used 3
    expect(panel).toContain('dropping 1 (2.4.4)')
    expect(panel).toContain('7 assessable files')
    // and it names the deferred backend gap rather than inventing a per-file delta
    expect(panel).toContain('no dry-run preview endpoint')
  })

  it('says so when the current scope matches the scan, rather than warning about nothing', async () => {
    const c = await mount({ run: RUN({ scan_scope: { '1.1.1': ['docx'], '1.4.3': ['docx'] } }) })
    await clickText(c, 'Change scope')
    const panel = c.querySelector('.scanscope-rescan').textContent
    expect(panel).toContain('matches this scan')
    expect(panel).not.toContain('dropping')
  })

  it('re-scan dispatches the run source through onScan', async () => {
    const onScan = vi.fn()
    const c = await mount({ onScan })
    await clickText(c, 'Change scope')
    await clickText(c, 'Re-scan with current scope')
    expect(onScan).toHaveBeenCalledWith('drive')
  })

  it('renders nothing without a run', async () => {
    const c = await mount({ run: null })
    expect(c.textContent).toBe('')
  })
})
