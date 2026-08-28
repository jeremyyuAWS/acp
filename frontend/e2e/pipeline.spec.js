import { test, expect } from '@playwright/test'
import { signIn, tab, runDiscovery } from './helpers.js'

// The corpus scripts/e2e-api.sh builds: three oracle PDFs. The PDF analyser is pure Python and
// vendored in-repo, so this holds on a clean checkout with no .NET build and no Google
// credentials. See that script for why the corpus is PDF-only.
const CORPUS_SIZE = 3
const API = `http://127.0.0.1:${process.env.ACP_E2E_API_PORT || '8078'}`

// One test, one scan. Splitting the DOM assertions from the scan-record ones would mean running
// the whole pipeline twice for the second half's sake — and would leave two scans in the store,
// so reading "the" scan back would depend on list ordering.
test('a local scan runs discover → assess and produces WCAG findings', async ({ page }) => {
  // Guards the whole suite. In SIM mode api.js serves synthetic fixtures from sim.js and never
  // opens a socket, and because SIM renders through the SAME components, every DOM assertion
  // below still passes — a fully green run that proves nothing. So record what the page actually
  // requested and fail if the backend was never involved.
  const apiCalls = []
  page.on('request', (r) => { if (r.url().startsWith(API)) apiCalls.push(r.url()) })

  await signIn(page)
  await tab(page, /Discover/).click()

  await runDiscovery(page)

  // Three mutually exclusive states share this section, distinguished only by their label:
  // "Discovery in progress" / "Discovery stopped" / "Discovery complete".
  await expect(page.getByRole('region', { name: 'Discovery complete' }))
    .toBeVisible({ timeout: 120_000 })

  // The count is what ties this to OUR corpus. SIM's synthetic estate is thousands of files, so
  // this line can only come from a real scan of .e2e/corpus. Wording is "files inventoried", not
  // "files discovered" — PR #884 (structured-row completion card) renamed it and updated
  // discoverCompleteSummary.test.jsx to match, but left this E2E assertion on the old copy, so
  // it has silently timed out on every main-branch CI run since (visible from commit 0d456ebc
  // onward).
  await expect(page.getByText(`${CORPUS_SIZE} files inventoried`, { exact: true })).toBeVisible({ timeout: 30_000 })

  const assessTab = tab(page, /Assess/)
  await expect(assessTab).toBeVisible()
  await assessTab.click()
  // Text is "Assess N documents" — the count is derived, so match the class, not the label.
  // This button stays disabled while any file is excluded, which is why the corpus is uniformly
  // eligible; a mixed one parks the run here with no error, just a button that never enables.
  await page.locator('button.assesssetup-run').click()

  // There is no "Assessment complete" string anywhere; the summary panel appearing IS the
  // signal. The -failed and -empty variants carry the same class, so the metric label below is
  // what separates a finished run from a collapsed one.
  await expect(page.locator('section.assesssummary')).toBeVisible({ timeout: 300_000 })
  await expect(page.getByText('Documents assessed')).toBeVisible()

  expect(apiCalls.length, 'no request reached the backend — is VITE_SIM=false set?')
    .toBeGreaterThan(0)
  expect(apiCalls.some((u) => u.includes('/scans?source=local')),
    'no local scan was dispatched').toBe(true)

  // Read the finished scan back from the API the browser just drove. Asserting on the record as
  // well as the panel is deliberate: a scan that finalized without the analyser ever running
  // still renders a summary, and no amount of DOM text distinguishes that from a real one.
  const scan = await page.evaluate(async (api) => {
    const list = await fetch(`${api}/scans`).then((r) => r.json())
    return fetch(`${api}/scans/${list[0].id}`).then((r) => r.json())
  }, API)

  expect(scan.run.assessed_at).toBeTruthy()
  expect(scan.files).toHaveLength(CORPUS_SIZE)
  expect(scan.files.filter((f) => typeof f.score === 'number'),
    'a file came back without a score').toHaveLength(CORPUS_SIZE)

  // pdf-untagged.pdf is an oracle fixture whose whole purpose is to trip this rule.
  const untagged = scan.files.find((f) => f.file === 'pdf-untagged.pdf')
  expect(untagged.issues.map((i) => i.rule_id)).toContain('pdf.tagged')
})
