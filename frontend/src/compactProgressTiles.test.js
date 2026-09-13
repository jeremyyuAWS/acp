import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'
const source = file => readFileSync(new URL(file, import.meta.url),'utf8')
it('matches Assess Metric surfaces and typography while retaining subdued fills and reduced motion',()=>{
 const assess=source('./AssessSummary.jsx'), documents=source('./RemediationProgressSummary.css')
 // The retained Document progress component still uses the older Assess activity cells.
 expect(source('./styles.css')).toMatch(/\.atile\s*\{[^}]*background: #f7f9fb; border: 1px solid #e6eaef; border-radius: 9px; padding: 14px 16px;/)
 expect(documents).toContain('background:#f7f9fb')
 expect(documents).toContain('opacity:.025')
 // New live measures share the current AssessSummary Metric dimensions and theme tokens.
 expect(assess).toContain("border: '1px solid var(--line)', borderRadius: 12, padding: '12px 14px', background: 'var(--surface)'")
 expect(assess).toContain('fontSize: 26, fontWeight: 700')
 for(const file of ['./file-coverage.css','./workflow-outcome-tiles.css']) {
  const rules=source(file)
  expect(rules).toContain('background:var(--surface)')
  expect(rules).toContain('border:1px solid var(--line)')
  expect(rules).toContain('border-radius:12px')
  expect(rules).toContain('padding:12px 14px')
  expect(rules).toContain('font-size:26px')
  expect(rules).toContain('font-weight:700')
  expect(rules).toContain('prefers-reduced-motion:reduce')
 }
 expect(source('./workflow-outcome-tiles.css')).toContain('opacity:.025')
 expect(source('./workflow-outcome-tiles.css')).toContain('--tile-accent:#2F7D32')
 expect(source('./workflow-outcome-tiles.css')).toContain('--tile-accent:#8a5a00')
})
