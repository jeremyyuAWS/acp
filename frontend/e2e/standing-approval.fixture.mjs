import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser=await chromium.launch({headless:true})
try {
  for (const width of [1280,390]) {
    const page=await browser.newPage({viewport:{width,height:1100}})
    const errors=[]; page.on('pageerror',e=>errors.push(e.message))
    await page.goto(`${process.env.FIXTURE_URL || 'http://127.0.0.1:5196'}/fixtures/standing-approval.html`)
    const checkbox=page.getByRole('checkbox',{name:'Automatically approve eligible AI suggestions'})
    await checkbox.waitFor({state:'visible'})
    assert.equal(await checkbox.isChecked(),false)
    await checkbox.check()
    assert.equal(await checkbox.isChecked(),true)
    assert.equal(await page.evaluate(()=>window.fixturePolicies.at(-1).auto_approve_ai),true)
    assert.match(await page.locator('.remediation-auto-approval').innerText(),/including fallbacks, without more approval dialogs/)
    const summaries=page.locator('.remediation-plan-choices > details > summary')
    const styles=await summaries.evaluateAll(nodes=>nodes.map(el=>{const s=getComputedStyle(el);return [s.fontSize,s.fontWeight,s.lineHeight,s.fontFamily]}))
    assert.ok(styles.length>=2)
    assert.deepEqual(styles[0],styles[1])
    assert.deepEqual(styles[0].slice(0,3),['13px','600','19.5px'])
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
    assert.deepEqual(errors,[])
    await page.screenshot({path:`/tmp/acp-standing-${width}.png`,fullPage:true})
    await page.close()
  }
  console.log('Desktop and mobile standing approval, matching accordion typography, no overflow: passed')
} finally { await browser.close() }
