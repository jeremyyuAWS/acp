import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'
const css = file => readFileSync(new URL(file, import.meta.url),'utf8')
it('uses the Assess card dimensions and subdued surfaces while retaining faint animated fills',()=>{
 const assess=css('./styles.css'), documents=css('./RemediationProgressSummary.css'), outcomes=css('./workflow-outcome-tiles.css')
 expect(assess).toMatch(/\.atile\s*\{[^}]*background: #f7f9fb; border: 1px solid #e6eaef; border-radius: 9px; padding: 14px 16px;/)
 for(const rules of [documents,outcomes]) {
  expect(rules).toContain('background:#f7f9fb')
  expect(rules).toContain('border:1px solid #e6eaef')
  expect(rules).toContain('font-size:28px')
  expect(rules).toContain('opacity:.025')
  expect(rules).toContain('prefers-reduced-motion:reduce')
 }
})
