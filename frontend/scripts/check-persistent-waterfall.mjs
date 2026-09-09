import { createServer } from 'vite'
import { chromium, firefox, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { host: '127.0.0.1', port: 0 } })
await server.listen()
try {
  for (const engine of [chromium, firefox]) {
    const browser = await engine.launch()
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.route('**/*', route => {
        const request = route.request()
        if (new URL(request.url()).hostname !== '127.0.0.1' || !['GET', 'HEAD'].includes(request.method())) return route.abort()
        return route.continue()
      })
      await page.goto(`${server.resolvedUrls.local[0]}fixtures/persistent-waterfall.html`)
      await page.waitForTimeout(1100) // Mount while Plan is visible and the graph is hidden.
      await page.getByRole('tab', { name: 'Live' }).click()
      const graph = page.locator('.wf-graph-canvas')
      const stage = page.locator('[data-stage=first]')
      await expect(stage).toBeVisible()
      await expect(page.locator('.wf-card .attempt-story')).toHaveCount(0)
      for (const state of ['processing_complete', 'failed', 'cancelled', 'paused', 'stalled']) {
        await page.getByLabel('Saved run state').selectOption(state)
        await expect(stage).toBeVisible()
        await expect(page.locator('.wf-graph-edge-working')).toHaveCount(0)
        await expect(page.locator('.wf-graph-node-active')).toHaveCount(0)
        await page.getByRole('tab', { name: 'Review' }).click()
        await page.getByRole('tab', { name: 'Live' }).click()
        await page.reload()
        await expect(page.getByLabel('Saved run state')).toHaveValue(state)
        await expect(stage).toBeVisible()
        await stage.focus()
        await page.keyboard.press('Enter')
        await expect(page.getByRole('dialog')).toContainText('recorded-model-v1')
        await expect(page.getByRole('dialog').locator('.attempt-story')).toBeVisible()
        await page.keyboard.press('Escape')
        await expect(page.getByRole('dialog')).toHaveCount(0)
        await expect(stage).toBeFocused()
      }
      for (const width of [320, 768, 1280]) {
        await page.getByRole('tab', { name: 'Plan' }).click()
        await page.setViewportSize({ width, height: 900 })
        await page.getByRole('tab', { name: 'Live' }).click()
        await page.waitForTimeout(1200)
        await expect(graph).toBeVisible()
        await expect(graph.locator('[data-stage]')).toHaveCount(5)
        const dimensions = await graph.evaluate(canvas => {
          const bounds = canvas.getBoundingClientRect()
          return [...canvas.querySelectorAll('[data-stage]')].every(node => {
            const r = node.getBoundingClientRect()
            return r.width > 0 && r.left >= bounds.left && r.right <= bounds.right + 1 && r.bottom <= bounds.bottom + 1
          })
        })
        expect(dimensions).toBe(true)
      }
      await page.getByLabel('Saved run state').selectOption('processing_complete')
      if (process.env.ACP_PERSISTENT_SCREENSHOT) await page.locator('.wf-card').screenshot({ path: `${process.env.ACP_PERSISTENT_SCREENSHOT}-${engine.name()}.png` })
      // CSS/measurement faults must never leave a dotted-only canvas indefinitely.
      const fault = await page.addStyleTag({ content: '.react-flow__node { visibility:hidden !important }' })
      await expect(page.getByRole('list', { name: 'Saved run stages' })).toBeVisible()
      await stage.click()
      await expect(page.getByRole('dialog')).toContainText('recorded-model-v1')
      await page.keyboard.press('Escape')
      await fault.evaluate(node => node.remove())
      await page.getByRole('button', { name: 'Retry diagram' }).click()
      await expect(graph).toBeVisible()
      await expect(stage).toBeVisible()
      await page.getByLabel('Saved run', { exact: true }).selectOption('multiple')
      await expect(graph.locator('[data-stage]')).toHaveCount(6)
      const second = graph.locator('[data-stage=next]').last()
      await second.click()
      await expect(page.getByRole('dialog').locator('h3')).toContainText('fallback-model-two')
      await expect(page.getByRole('dialog').locator('.attempt-story-model-context')).toContainText('second-provider · fallback-model-two')
      await page.keyboard.press('Escape')
      await expect(second).toBeFocused()
      await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
      await page.getByRole('button', { name: 'Reset view', exact: true }).click()
      await expect(graph).toBeVisible()
      if (process.env.ACP_PERSISTENT_SCREENSHOT) await page.locator('.wf-card').screenshot({ path: `${process.env.ACP_PERSISTENT_SCREENSHOT}-${engine.name()}-multiple.png` })
      await page.getByLabel('Saved run', { exact: true }).selectOption('legacy')
      await expect(page.locator('.wf-graph-caption')).toContainText('Activity history unavailable')
      await expect(stage).not.toContainText('recorded-model-v1')
      await expect(stage).toBeVisible()
      await page.getByRole('button', { name: 'View activity', exact: true }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.keyboard.press('Escape')
      const unmeasured = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await unmeasured.addInitScript(() => {
        const Native = window.ResizeObserver
        window.ResizeObserver = class extends Native {
          constructor(callback) { super((entries, observer) => {
            const delivered = entries.filter(entry => !entry.target.classList.contains('react-flow__node'))
            if (delivered.length) callback(delivered, observer)
          }) }
        }
      })
      await unmeasured.goto(`${server.resolvedUrls.local[0]}fixtures/persistent-waterfall.html?mode=live`)
      await expect(unmeasured.locator('.wf-graph-canvas [data-stage=first]')).toBeVisible()
      await expect(unmeasured.locator('.react-flow__edge')).toHaveCount(4)
      await unmeasured.close()
      expect(errors).toEqual([])
      console.log(`${engine.name()}: hidden mount/reveal, terminal transitions, saved reload, drawer/focus, 320/768/1280, rendering fault/retry, legacy scope passed`)
    } finally { await browser.close() }
  }
} finally { await server.close() }
