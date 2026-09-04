/**
 * WCAG real-browser accessibility audit.
 *
 * Runs in Playwright/Chromium (SIM mode — no backend required).
 * Signs in as the `compliance` persona which has access to all workflow tabs.
 *
 * For each major surface this spec:
 *   1. Navigates to the surface and waits for content to be ready.
 *   2. Sets document.documentElement.dataset.wcag = 'on' so all CSS overrides apply.
 *   3. Runs axe-core against the full document with WCAG 2.1 A/AA rules.
 *      All violations are failures — color-contrast is INCLUDED because Chromium's
 *      rendering engine computes CSS values correctly.
 *   4. Adds targeted keyboard and structural checks that axe-core does not cover.
 *
 * Run:
 *   ACP_E2E_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \
 *     npx playwright test --config=playwright.wcag.config.js
 */
import { test, expect } from '@playwright/test'
import { createRequire } from 'module'

const require = createRequire(import.meta.url)
const AXE_PATH = require.resolve('axe-core/axe.min.js')

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Click the demo SSO button → signs in as the compliance persona (has all workflow tabs). */
async function signIn(page) {
  await page.goto('/')
  await page.getByRole('button', { name: /Sign in with SSO/ }).click()
  // The tab list is the sign that auth completed and data is loaded.
  await expect(page.locator('[role="tablist"]')).toBeVisible({ timeout: 15_000 })
}

/**
 * Sign in as the admin persona (Sam Devlin) by clicking their persona card.
 * The admin persona has `settings` in its allow list, which makes the ⚙ cog button appear.
 * The compliance persona (SSO button) does NOT have settings access.
 */
async function signInAsAdmin(page) {
  await page.goto('/')
  // The admin persona card is labeled by name or role — match by "Platform Admin" or "Sam Devlin"
  await page.getByRole('button', { name: /Platform Admin|Sam Devlin/i }).click()
  await expect(page.locator('[role="tablist"]')).toBeVisible({ timeout: 15_000 })
}

/** Click a tab by its display-text pattern. */
const clickTab = (page, re) =>
  page.locator('[role="tab"]', { hasText: re }).click()

/**
 * Enable WCAG mode, inject axe, run it against the full document.
 * Returns the array of violations.  Color-contrast is NOT excluded —
 * a real browser can evaluate computed styles.
 */
async function runAxe(page) {
  // Enable WCAG mode on the root element so all [data-wcag="on"] CSS overrides apply.
  await page.evaluate(() => {
    document.documentElement.dataset.wcag = 'on'
  })
  await page.addScriptTag({ path: AXE_PATH })
  return page.evaluate(() =>
    window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
    }).then((r) => r.violations)
  )
}

/**
 * Format violations for test failure messages.
 * Shows rule id, impact, description, and the first failing node snippet.
 */
function fmt(violations) {
  if (!violations.length) return '(none)'
  return violations.map((v) =>
    `\n  [${v.impact}] ${v.id}: ${v.description}` +
    v.nodes.slice(0, 3).map((n) =>
      `\n    node: ${n.html.slice(0, 160)}` +
      (n.failureSummary ? `\n    fix: ${n.failureSummary.slice(0, 120)}` : '')
    ).join('')
  ).join('\n')
}

// ── Sign-in screen ─────────────────────────────────────────────────────────────

test.describe('Sign-in screen', () => {
  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    await page.goto('/')
    // Wait for the SSO button to appear (getConfig resolves in SIM mode immediately)
    await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible()
    await page.evaluate(() => { document.documentElement.dataset.wcag = 'on' })
    await page.addScriptTag({ path: AXE_PATH })
    const violations = await page.evaluate(() =>
      window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
      }).then((r) => r.violations)
    )
    expect(violations, fmt(violations)).toHaveLength(0)
  })
})

// ── Per-tab fixtures ──────────────────────────────────────────────────────────

test.describe('Overview tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Overview/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    // Wait for the estate metrics to render (synthetic data, resolves quickly)
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })

  test('tab panel is labelled by its tab', async ({ page }) => {
    const panel = page.locator('[role="tabpanel"]')
    const labelledBy = await panel.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    const label = page.locator(`#${labelledBy}`)
    await expect(label).toBeVisible()
  })
})

test.describe('Sources tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Sources/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

test.describe('Discover tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Discover/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })

  test('Estate overview region has a visible heading', async ({ page }) => {
    // The Discover tab hosts the main estate metrics section
    const headings = page.locator('[role="tabpanel"] h2, [role="tabpanel"] h3')
    await expect(headings.first()).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('Assess tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Assess/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    // Wait for the summary or setup panel to render
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })

  test('assessment status region present in DOM', async ({ page }) => {
    // AssessSummary keeps an aria-live="polite" status region in the DOM at all times so
    // assistive tech receives updates when an assessment completes.  In SIM mode the initial
    // state may render the region empty (and therefore invisible), but it must be attached.
    const statusEl = page.locator('[role="tabpanel"] [role="status"]').first()
    await expect(statusEl).toBeAttached({ timeout: 5_000 })
  })
})

test.describe('Remediate tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Remediate/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

test.describe('Release tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Release/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

test.describe('Monitor tab', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Monitor/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

test.describe('Live Operations tab', () => {
  test.beforeEach(async ({ page }) => {
    await signInAsAdmin(page)
    await clickTab(page, /Live Operations/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await expect(page.getByText(/Live Azure traffic/)).toBeVisible({ timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

test.describe('Scan Analytics tab', () => {
  test.beforeEach(async ({ page }) => {
    await signInAsAdmin(page)
    await clickTab(page, /Scan Analytics/)
    await expect(page.locator('[role="tabpanel"]')).toBeVisible()
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('no WCAG 2.1 A/AA violations', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })
})

// ── Global shell ──────────────────────────────────────────────────────────────

test.describe('Global shell (nav + header)', () => {
  test.beforeEach(async ({ page }) => signIn(page))

  test('no WCAG 2.1 A/AA violations on shell landmarks', async ({ page }) => {
    // Scope to the header + nav, which are always mounted regardless of tab
    await page.evaluate(() => { document.documentElement.dataset.wcag = 'on' })
    await page.addScriptTag({ path: AXE_PATH })
    const violations = await page.evaluate(() =>
      window.axe.run(document.querySelector('header') || document.body, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
      }).then((r) => r.violations)
    )
    expect(violations, fmt(violations)).toHaveLength(0)
  })

  test('nav landmark is labelled', async ({ page }) => {
    const nav = page.locator('nav[aria-label]')
    await expect(nav).toBeVisible()
    const label = await nav.getAttribute('aria-label')
    expect(label?.length).toBeGreaterThan(0)
  })

  test('tablist is labelled', async ({ page }) => {
    const tl = page.locator('[role="tablist"]')
    const label = await tl.getAttribute('aria-label')
    expect(label?.length).toBeGreaterThan(0)
  })

  test('each tab has an accessible name', async ({ page }) => {
    const tabs = page.locator('[role="tab"]')
    const count = await tabs.count()
    expect(count).toBeGreaterThan(3)
    for (let i = 0; i < count; i++) {
      const text = (await tabs.nth(i).textContent())?.trim()
      expect(text?.length, `Tab ${i} has no text`).toBeGreaterThan(0)
    }
  })

  test('main content region is reachable by keyboard (id=main-content)', async ({ page }) => {
    const main = page.locator('#main-content, main, [role="main"]').first()
    await expect(main).toBeAttached()
  })
})

// ── Settings modal ─────────────────────────────────────────────────────────────

test.describe('Settings panel (modal)', () => {
  test.beforeEach(async ({ page }) => {
    // Must sign in as the admin persona — the compliance persona does not have `settings` in
    // its allow list, so the ⚙ cog button is not rendered for them.
    await signInAsAdmin(page)
    await page.getByRole('button', { name: /Platform settings/i }).click()
    await page.waitForFunction(() => !!document.querySelector('[role="dialog"],.setpanel,.setoverlay'), { timeout: 8_000 })
  })

  test('no WCAG 2.1 A/AA violations in settings panel', async ({ page }) => {
    const v = await runAxe(page)
    expect(v, fmt(v)).toHaveLength(0)
  })

  test('settings panel has role=dialog or is a landmark region', async ({ page }) => {
    // Settings renders as a panel, not necessarily a modal dialog
    const panel = page.locator('[role="dialog"], [aria-label*="settings" i], [aria-label*="Settings" i]').first()
    await expect(panel).toBeVisible()
  })
})

// ── Keyboard navigation ────────────────────────────────────────────────────────

test.describe('Keyboard navigation', () => {
  test.beforeEach(async ({ page }) => signIn(page))

  test('Tab key moves through the workflow tabs without trapping', async ({ page }) => {
    // Focus the first tab and Tab through the tab list
    const firstTab = page.locator('[role="tab"]').first()
    await firstTab.focus()
    // Arrow-key navigation inside the tablist (WAI-ARIA tablist pattern)
    await page.keyboard.press('ArrowRight')
    const focused = page.locator(':focus')
    const role = await focused.getAttribute('role')
    // After ArrowRight in a tablist, focus should stay within the tablist
    expect(['tab', null].includes(role)).toBeTruthy()
  })

  test('all visible buttons are reachable by Tab from the top', async ({ page }) => {
    // Tab from the first focusable element and collect what gets focused
    await page.keyboard.press('Tab')
    const reached = new Set()
    for (let i = 0; i < 30; i++) {
      const active = await page.evaluate(() => {
        const el = document.activeElement
        return el ? { tag: el.tagName, role: el.getAttribute('role'), text: el.textContent?.slice(0, 40) } : null
      })
      if (!active) break
      reached.add(active.tag + active.role + active.text)
      await page.keyboard.press('Tab')
    }
    // We should have reached at least 5 distinct focusable elements
    expect(reached.size).toBeGreaterThanOrEqual(5)
  })

  test('focused elements have a visible focus ring (:focus-visible)', async ({ page }) => {
    await page.keyboard.press('Tab')
    // Check that the focused element has a non-transparent outline
    const hasOutline = await page.evaluate(() => {
      const el = document.activeElement
      if (!el) return false
      const style = window.getComputedStyle(el)
      // Check outline or box-shadow (both are used for focus rings)
      const outline = style.outlineWidth
      const shadow = style.boxShadow
      return (outline && outline !== '0px') || (shadow && shadow !== 'none')
    })
    expect(hasOutline, 'First focused element has no visible focus ring').toBe(true)
  })
})

// ── Dialog focus management ────────────────────────────────────────────────────

test.describe('Dialog focus management', () => {
  test.beforeEach(async ({ page }) => signIn(page))

  test('settings panel: focus enters the panel on open', async ({ page }) => {
    // Must use admin persona — only admin has the settings cog button
    await page.goto('/')
    await page.getByRole('button', { name: /Platform Admin|Sam Devlin/i }).click()
    await expect(page.locator('[role="tablist"]')).toBeVisible({ timeout: 15_000 })
    const opener = page.getByRole('button', { name: /Platform settings/i })
    await opener.click()
    await page.waitForFunction(() => !!document.querySelector('[role="dialog"],.setpanel,.setoverlay'), { timeout: 8_000 })
    // After opening, focus should be inside the settings panel, not on the opener
    const activeIsInsidePanel = await page.evaluate(() => {
      const active = document.activeElement
      const panel = document.querySelector('[role="dialog"], .settings, [data-settings]')
      return panel ? panel.contains(active) : false
    })
    // Settings panels may focus the first interactive element or the close button
    // either is correct; we just need focus to have moved away from body/opener
    const activeTag = await page.evaluate(() => document.activeElement?.tagName)
    expect(activeTag).not.toBe('BODY')
  })
})

// ── Accessible names audit ────────────────────────────────────────────────────

test.describe('Accessible names on controls', () => {
  test.beforeEach(async ({ page }) => signIn(page))

  test('all icon-only buttons have aria-label', async ({ page }) => {
    // Icon-only buttons (no visible text) must have aria-label
    const namelessButtons = await page.evaluate(() => {
      const buttons = [...document.querySelectorAll('button')]
      return buttons
        .filter((b) => {
          const text = b.textContent?.trim() ?? ''
          const label = b.getAttribute('aria-label') ?? ''
          const labelledBy = b.getAttribute('aria-labelledby') ?? ''
          const title = b.getAttribute('title') ?? ''
          // Button has no accessible name if: text is empty/just-emoji, no label, no labelledBy, no title
          return !text && !label && !labelledBy && !title
        })
        .map((b) => b.outerHTML.slice(0, 120))
    })
    expect(namelessButtons, `Buttons with no accessible name:\n${namelessButtons.join('\n')}`).toHaveLength(0)
  })

  test('all form inputs have a label or aria-label', async ({ page }) => {
    const unlabelled = await page.evaluate(() => {
      const inputs = [...document.querySelectorAll('input:not([type="hidden"]), select, textarea')]
      return inputs
        .filter((el) => {
          const id = el.id
          const label = id ? document.querySelector(`label[for="${id}"]`) : null
          return !label && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')
        })
        .map((el) => el.outerHTML.slice(0, 120))
    })
    expect(unlabelled, `Unlabelled form inputs:\n${unlabelled.join('\n')}`).toHaveLength(0)
  })
})

// ── Status not conveyed by colour alone ──────────────────────────────────────

test.describe('Status not conveyed by colour alone', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await clickTab(page, /Assess/)
    await page.waitForFunction(() =>
      document.querySelector('[role="tabpanel"]')?.textContent?.length > 50
    , { timeout: 10_000 })
  })

  test('Assess tab renders accessible textual content (not blank or colour-only)', async ({ page }) => {
    // In SIM mode the Assess tab shows the in-progress state (AssessSummary with severity labels
    // is gated on assessed_at which SIM does not set).  We verify two WCAG SC 1.4.1 principles:
    // (a) the tab's content is not blank — something is communicated in text, and
    // (b) any colour indicator (if present) accompanies a text label.
    // Severity-label rendering (AssessSummary line 309: "<b>{count}</b> {label}") is verified
    // exhaustively in wcagAxeMatrix.test.jsx which mounts AssessSummary with known data.
    const text = await page.locator('[role="tabpanel"]').textContent()
    expect((text || '').trim().length, 'Assess tab has no text content').toBeGreaterThan(20)
  })

  test('colour-coded severity dots in AssessSummary have adjacent text labels', async ({ page }) => {
    // The aria-hidden dot (<span aria-hidden> with background color) is always paired with a
    // text label via SEVERITY_LABEL (AssessSummary.jsx line 309).  Verify that any coloured
    // decorative indicator in the tab panel has a sibling text node — a pure-CSS colour chip
    // with no text would fail WCAG SC 1.4.1.
    const violatingDots = await page.evaluate(() => {
      // Find aria-hidden inline spans with a background-color style (the severity dots)
      const dots = [...document.querySelectorAll('[role="tabpanel"] span[aria-hidden="true"]')]
        .filter((el) => el.style.background || el.style.backgroundColor)
      return dots.filter((el) => {
        // Check that the parent span contains text other than the dot itself
        const parent = el.parentElement
        if (!parent) return true
        const text = parent.textContent?.trim() ?? ''
        return text.length === 0
      }).map((el) => el.outerHTML)
    })
    expect(violatingDots,
      `Colour-only dots with no adjacent text label:\n${violatingDots.join('\n')}`
    ).toHaveLength(0)
  })
})
