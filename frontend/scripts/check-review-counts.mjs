import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { host: '127.0.0.1', port: 0 } })
await server.listen()
const origin = new URL(server.resolvedUrls.local[0]).origin
const browser = await chromium.launch({ headless: true })
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    await page.route('**/*', route => {
      assert.equal(route.request().method(), 'GET')
      assert.equal(new URL(route.request().url()).origin, origin)
      return route.continue()
    })
    await page.goto(`${origin}/fixtures/review-counts.html`)
    await expect(page.locator('[title="346 review items requiring attention"]')).toBeVisible()
    await expect(page.locator('[data-testid="rem-run-summary"]')).toContainText('299 need approval')
    await expect(page.getByRole('tab', { name: 'Approve AI suggestions 299', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Fix manually 47', exact: true })).toBeVisible()
    await expect(page.getByText('2,000 of 2,400 applied-change records loaded.', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: /Bulk approve ready proposals/ }).click()
    await expect(page.getByRole('button', { name: 'Approve all ready (299)', exact: true })).toBeVisible()
    assert.equal(await page.evaluate(() => window.fixtureWrites), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
    assert.equal((await page.locator('body').textContent()).includes('2299 documents'), false)
    await page.screenshot({ path: `/tmp/acp-review-counts-${width}.png`, fullPage: true })
    await page.close()
  }
  console.log('Desktop/mobile review-item units, 299 approvals, 47 manual items, capped detail disclosure and no-write checks passed.')
} finally { await browser.close(); await server.close() }
