// Isolated fixture: real worktree components and CSS, no shared preview or API mutation.
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from '@playwright/test'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', route => {
    assert.equal(route.request().method(), 'GET', 'Fixture must never mutate application data')
    return route.fulfill({ json: { available: false, attempts: [], proposals: [], review_receipts: [] } })
  })
  await page.goto(`${server.resolvedUrls.local[0]}fixtures/remediate-polish.html`)
  const first = page.locator('[data-stage=first]')
  const next = page.locator('[data-stage=next]')
  await first.waitFor()
  await first.focus()
  await page.keyboard.press('ArrowRight')
  assert.equal(await next.evaluate(element => element === document.activeElement), true)
  assert.equal(await page.getByRole('dialog').count(), 0, 'Arrow navigation must not open a drawer')
  for (const activation of ['Enter', 'Space', 'click']) {
    if (activation === 'click') await next.click()
    else await page.keyboard.press(activation)
    const dialog = page.getByRole('dialog', { name: 'Stage evidence and costs' })
    await dialog.waitFor()
    assert.equal(await dialog.evaluate(element => element.contains(document.activeElement)), true)
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    assert.equal(await next.evaluate(element => element === document.activeElement), true, 'Closing returns focus to the inspected stage')
  }
  for (const width of [320, 375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(150)
    const geometry = await page.locator('.wf-graph-canvas').evaluate(canvas => {
      const bounds = canvas.getBoundingClientRect()
      return { width: bounds.width, nodes: [...canvas.querySelectorAll('[data-stage]')].map(node => {
        const rect = node.getBoundingClientRect()
        return { left: rect.left - bounds.left, right: rect.right - bounds.left, bottom: rect.bottom - bounds.top, canvasHeight: bounds.height, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }
      }) }
    })
    for (const node of geometry.nodes) {
      assert.ok(node.left >= 0 && node.right <= geometry.width + 1, `${width}px: node stays in canvas`)
      assert.ok(node.bottom <= node.canvasHeight + 1, `${width}px: node fits canvas height`)
      assert.ok(node.scrollWidth <= node.clientWidth + 1, `${width}px: recorded identity wraps`)
    }
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.waitForTimeout(50)
  assert.equal(await page.locator('.react-flow__edge.animated').count(), 0)
  assert.equal(await first.evaluate(element => getComputedStyle(element).transitionDuration), '0s')
  assert.ok((await first.textContent()).includes('Request dispatched'), 'Reduced motion preserves the activity fact')
  assert.deepEqual(errors, [])
  console.log('Remediate fixture passed: real Card keyboard activation, Escape/focus return, 320–1280px graph layout, and reduced motion.')
} finally {
  await browser.close()
  await server.close()
}
