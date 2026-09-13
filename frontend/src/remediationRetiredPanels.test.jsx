import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
const here = dirname(fileURLToPath(import.meta.url))
import { expect, it } from 'vitest'
it('deliberately retires embedded delivery and run details while preserving restoration code', () => {
 const source = readFileSync(join(here,'Remediate.jsx'), 'utf8')
 for (const component of ['RemediationAutoRelease','RemediationReleaseAccess','RemediationRunDetails']) {
  expect(source).not.toContain(`<${component}`)
  expect(existsSync(join(here,`${component}.jsx`))).toBe(true)
 }
 expect(source).not.toContain('aria-label="Publish corrected copies"')
 expect(source).not.toContain('aria-label="Run details"')
 expect(source).not.toContain('Additional run information')
 expect(source).toContain('useAutomaticReleaseStatus(runId, impactScope, setAutomaticReleaseState)')
 const release = readFileSync(join(here,'Publish.jsx'),'utf8')
 expect(release).toContain('<ReleaseQuickActions')
 expect(release).toContain('<ReleaseReports')
})
