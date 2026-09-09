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
      assert.equal(route.request().method(), 'GET', 'Preview must not dispatch paid work')
      assert.equal(new URL(route.request().url()).origin, origin)
      return route.continue()
    })
    await page.goto(`${origin}/fixtures/generation-chain.html`)
    const disclosure = page.locator('.remediation-generation-chain')
    await expect(disclosure).not.toHaveAttribute('open', '')
    const summary = disclosure.locator('summary')
    await summary.focus(); await page.keyboard.press('Enter')
    const toggle = page.getByRole('checkbox', { name: 'Enable a second fallback' })
    await expect(toggle).not.toBeChecked()
    assert.equal(await page.evaluate(() => window.fixturePolicies.length), 0)
    await toggle.check()
    await expect(page.getByLabel('Second fallback model')).toHaveValue('0')
    const chain = await page.evaluate(() => window.fixturePolicies.at(-1).generation_chain)
    assert.deepEqual(chain.steps.map(step => step.step_id), ['primary', 'fallback_1', 'fallback_2'])
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
    await page.screenshot({ path: `/tmp/acp-generation-chain-${width}.png`, fullPage: true })
    await page.goto(`${origin}/fixtures/generation-chain.html?unavailable`)
    await page.locator('.remediation-generation-chain summary').click()
    await expect(toggle).toBeDisabled()
    await expect(page.getByText('This scope has no supported slide-title findings.')).toBeVisible()
    assert.equal(await page.evaluate(() => window.fixturePolicies.length), 0)
    await page.close()
  }
  console.log('Desktop/mobile generation options, keyboard disclosure, exact chain, unavailable gate, and no-paid-preview checks passed.')
} finally { await browser.close(); await server.close() }
