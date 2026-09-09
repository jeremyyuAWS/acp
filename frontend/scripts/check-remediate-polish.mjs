// Isolated fixture: real worktree components and CSS, no shared preview or API mutation.
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  page.setDefaultTimeout(10_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixtureOrigin = new URL(server.resolvedUrls.local[0]).origin
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    assert.equal(route.request().method(), 'GET', 'Fixture must never mutate application data')
    if (url.origin === fixtureOrigin && !url.pathname.startsWith('/scans/') && !url.pathname.startsWith('/api/')) return route.continue()
    return route.fulfill({ json: { available: false, scan_id: 'fixture', batch_id: 'fixture-batch', attempts: [], proposals: [], review_receipts: [] } })
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
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(`${server.resolvedUrls.local[0]}fixtures/remediate-polish.html?mode=review`)
  const review = page.locator('#review-fixture')
  const queueRow = review.locator('.rinbox-row').first()
  const ratio = await queueRow.evaluate(element => {
    const rgb = value => value.match(/[\d.]+/g)?.map(Number)
    const luminance = color => rgb(color).slice(0, 3).map(value => {
      const channel = value / 255
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
    }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
    let parent = element
    let background = 'rgb(255, 255, 255)'
    while (parent) {
      const value = getComputedStyle(parent).backgroundColor
      if (rgb(value)?.length === 3 || rgb(value)?.[3] > 0) { background = value; break }
      parent = parent.parentElement
    }
    const colors = [luminance(getComputedStyle(element).color), luminance(background)].sort((a, b) => b - a)
    return (colors[0] + .05) / (colors[1] + .05)
  })
  assert.ok(ratio >= 4.5, `Review queue text contrast must reach 4.5:1; got ${ratio}`)
  assert.equal(await review.locator('.rinbox-document-toggle').first().evaluate(element => getComputedStyle(element).color), await queueRow.evaluate(element => getComputedStyle(element).color), 'Document group headers use the same readable foreground')
  const sourceDisclosure = review.getByText('Show full source', { exact: true })
  await sourceDisclosure.focus()
  await page.keyboard.press('Enter')
  await expect(sourceDisclosure.locator('..')).toHaveJSProperty('open', true)
  assert.ok((await sourceDisclosure.locator('..').textContent()).includes('Full source ending.'))
  await page.keyboard.press('Space')
  await expect(sourceDisclosure.locator('..')).toHaveJSProperty('open', false)
  assert.equal(await sourceDisclosure.evaluate(element => element === document.activeElement), true)
  const collapsedText = await review.locator('.remediation-detail-content').innerText()
  assert.ok(collapsedText.length < 2200, `Visible decision content stays compact (${collapsedText.length} characters)`)
  for (const width of [320, 375, 768]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(100)
    const back = review.getByRole('button', { name: /Back to queue/ })
    if (await back.isVisible()) await back.click()
    await review.locator('.rinbox-row').first().click()
    const comparison = review.locator('.remediation-comparison')
    assert.equal(await comparison.isVisible(), true)
    assert.equal(await comparison.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
    assert.equal(await review.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true, `${width}px: review has no horizontal overflow`)
    await sourceDisclosure.focus()
    await page.keyboard.press('Enter')
    await expect(sourceDisclosure.locator('..')).toHaveJSProperty('open', true)
    await page.keyboard.press('Enter')
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.waitForTimeout(100)
  }
  if (process.env.ACP_POLISH_SCREENSHOT) {
    await review.locator('h2').scrollIntoViewIfNeeded()
    await page.screenshot({ path: process.env.ACP_POLISH_SCREENSHOT })
  }
  assert.deepEqual(errors, [])
  console.log('Remediate fixture passed: real Card keyboard activation, Escape/focus return, 320–1280px graph layout, reduced motion, review contrast, and full-source keyboard disclosures.')
} finally {
  await browser.close()
  await server.close()
}
