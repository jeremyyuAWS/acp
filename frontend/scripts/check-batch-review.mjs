import { chromium } from '@playwright/test'
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
      assert.equal(route.request().method(), 'GET', 'Fixture must never write to an API')
      assert.equal(new URL(route.request().url()).origin, origin, 'Fixture must remain local')
      return route.continue()
    })
    await page.goto(`${origin}/fixtures/batch-review.html`)
    await page.getByRole('button', { name: /Bulk approve ready proposals/ }).click()
    const panel = page.getByRole('region', { name: 'Select findings for approval' })
    assert.ok(await panel.getByRole('button', { name: 'Approve all ready (37)', exact: true }).isVisible())
    assert.equal(await panel.locator('input[type=checkbox]:disabled').count(), 0)
    await panel.getByRole('button', { name: 'Approve all ready (37)', exact: true }).click()
    assert.equal(await panel.locator('details[open]').count(), 0)
    await page.getByRole('tab', { name: /Fix manually/ }).click()
    assert.equal(await panel.isVisible(), false)
    assert.ok(await page.getByText('Manual issue', { exact: true }).filter({ visible: true }).first().isVisible())
    await page.getByRole('tab', { name: /Approve AI suggestions/ }).click()
    await page.getByRole('button', { name: /Bulk approve ready proposals/ }).click()
    assert.equal(await panel.getByRole('button', { name: /Confirm approval/ }).count(), 0)
    await panel.getByText('Inspect proposals or choose a subset (optional)', { exact: true }).click()
    await panel.getByRole('button', { name: 'Next batch page' }).click()
    assert.equal(await page.evaluate(() => window.fixtureDecisions.length), 0)
    await panel.getByRole('checkbox').first().check()
    await panel.getByRole('button', { name: 'Approve selected', exact: true }).click()
    assert.equal(await page.evaluate(() => window.fixtureDecisions.length), 0)
    await panel.getByRole('button', { name: 'Confirm approval of 1 findings' }).click()
    await page.waitForFunction(() => window.fixtureDecisions.length === 1)
    assert.equal(await page.evaluate(() => window.fixtureDecisions[0].id), 'finding-10')
    assert.ok(await panel.getByText('1 recorded · 0 not recorded · 0 uncertain').isVisible())
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
    assert.equal(overflow, false, `horizontal overflow at ${width}`)
    await page.screenshot({ path: `/tmp/acp-batch-${width}.png`, fullPage: true })
    await page.goto(`${origin}/fixtures/batch-review.html?applied=1`)
    await page.getByRole('button', { name: /Bulk approve ready proposals/ }).click()
    assert.ok(await panel.getByText('No proposals are ready for approval', { exact: false }).isVisible())
    assert.equal(await panel.getByRole('checkbox').count(), 0)
    assert.ok(await panel.getByRole('button', { name: 'View changes and next steps' }).isVisible())
    await page.close()
  }
  console.log('Desktop/mobile batch selection, preview, exact write, feedback and reduced-motion layout passed.')
} finally { await browser.close(); await server.close() }
