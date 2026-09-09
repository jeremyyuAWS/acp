import { createServer } from 'vite'
import { chromium, firefox, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), define: { 'import.meta.env.VITE_SIM': JSON.stringify('false') }, server: { host: '127.0.0.1', port: 0 } })
await server.listen()
try {
  for (const engine of [chromium, firefox]) {
    const browser = await engine.launch()
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
      const errors = []
      page.on('pageerror', e => errors.push(e.message))
      await page.route('**/*', route => {
        const request = route.request()
        if (request.method() !== 'GET') throw new Error('The fixture must never mutate application data')
        const url = new URL(request.url())
        if (url.pathname === '/scans/chain-scan/remediation/insights/chain-run') return route.fulfill({ json: {
          available: true, scan_id: 'chain-scan', batch_id: 'chain-run', coverage: 'complete', proposals: [], review_receipts: [],
          attempts: ['primary-model', 'first-fallback-model', 'second-fallback-model'].map((model, i) => ({ attempt_id: `attempt-${i}`, operation_id: 'saved-operation', file: 'Saved.pdf', purpose: i ? 'fallback' : 'draft', provider: 'recorded-provider', model, created_at: `2026-09-08T12:00:0${i}Z`, status: 'started' })),
          pagination: { limit: 100, offset: 0, has_more: false },
        } })
        if (url.origin === new URL(server.resolvedUrls.local[0]).origin) return route.continue()
        return route.abort()
      })
      await page.goto(server.resolvedUrls.local[0] + 'fixtures/recorded-chain.html')
      await page.getByRole('tab', { name: 'Live' }).click()
      const canvas = page.locator('.wf-graph-canvas')
      const second = page.locator('[data-node-id="configured:fallback_2"]')
      await expect(canvas.locator('[data-stage]')).toHaveCount(7)
      await expect(second).toContainText('Fallback 2')
      await expect(second).toContainText('Configured')
      await expect(page.locator('[data-stage=review]')).toContainText('recorded-reviewer')
      await expect(page.locator('.wf-graph-node-active,.wf-graph-edge-working')).toHaveCount(0)
      for (const state of ['processing_complete', 'failed', 'cancelled']) {
        await page.getByLabel('Saved state', { exact: true }).selectOption(state)
        await page.getByRole('tab', { name: 'Review' }).click()
        await page.getByRole('tab', { name: 'Live' }).click()
        await page.reload()
        await expect(second).toBeVisible()
        await page.locator('[data-node-id="configured:fallback_1"]').focus()
        await page.keyboard.press('ArrowRight')
        await expect(second).toBeFocused()
        await page.keyboard.press('Enter')
        const drawer = page.getByRole('dialog')
        await expect(drawer.locator('h3')).toContainText('second-fallback-model')
        await expect(drawer.locator('.attempt-story-timeline')).toContainText('second-fallback-model')
        await expect(drawer.locator('.attempt-story-timeline')).toContainText('primary-model')
        await expect(drawer.locator('.attempt-story-model-context')).toContainText('second-fallback-model')
        await page.keyboard.press('Escape')
        await expect(second).toBeFocused()
      }
      for (const width of [320, 768, 1280, 1440]) {
        await page.getByRole('tab', { name: 'Plan' }).click()
        await page.setViewportSize({ width, height: 1000 })
        await page.getByRole('tab', { name: 'Live' }).click()
        await page.waitForTimeout(1100)
        await expect(canvas).toBeVisible()
        const fits = await canvas.evaluate(element => {
          const bounds = element.getBoundingClientRect()
          return [...element.querySelectorAll('[data-stage]')].every(node => {
            const rect = node.getBoundingClientRect()
            return rect.width > 0 && rect.left >= bounds.left && rect.right <= bounds.right + 1 && rect.bottom <= bounds.bottom + 1 && node.scrollWidth <= node.clientWidth + 1
          })
        })
        if (!fits) console.log(width, JSON.stringify(await canvas.evaluate(element => ({ bounds: element.getBoundingClientRect().toJSON(), nodes: [...element.querySelectorAll('[data-stage]')].map(node => ({ text: node.textContent, rect: node.getBoundingClientRect().toJSON(), scrollWidth: node.scrollWidth, clientWidth: node.clientWidth })) }))))
        expect(fits).toBe(true)
      }
      if (process.env.ACP_CHAIN_SCREENSHOT) await page.locator('.wf-card').screenshot({ path: `${process.env.ACP_CHAIN_SCREENSHOT}-${engine.name()}.png` })
      await page.getByLabel('Second fallback saved in plan').uncheck()
      await expect(second).toHaveCount(0)
      await expect(canvas.locator('[data-stage]')).toHaveCount(6)
      await page.getByLabel('Second fallback saved in plan').check()
      await expect(second).toBeVisible()
      expect(errors).toEqual([])
      console.log(`${engine.name()}: configured second fallback + distinct reviewer, exact step drawer history, terminal/reload, 320–1440 hidden resize, disabled option passed`)
    } finally { await browser.close() }
  }
} finally { await server.close() }
