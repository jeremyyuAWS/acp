import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ headless: true })
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    await page.goto('http://127.0.0.1:5187/fixtures/batch-review.html')
    await page.getByRole('button', { name: 'Select findings for batch approval', exact: true }).click()
    const panel = page.getByRole('region', { name: 'Select findings for approval' })
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
    await page.close()
  }
  console.log('Desktop/mobile batch selection, preview, exact write, feedback and reduced-motion layout passed.')
} finally { await browser.close() }
