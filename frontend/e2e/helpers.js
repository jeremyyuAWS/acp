import { expect } from '@playwright/test'

// The app has no router — `view` is plain React state and nothing is reflected in the URL, so
// there is no deep link to a tab and no way to restore a session across a reload. Every spec
// starts at `/` and clicks in from the sign-in screen.
export async function signIn(page) {
  await page.goto('/')
  // "Sign in with SSO" is the demo-auth branch (SignIn.jsx renders it when /config reports
  // auth:"demo", i.e. no ACP_GOOGLE_CLIENT_ID on the backend). It signs in as the `compliance`
  // persona, the only one whose `allow` list carries both discover and assess.
  await page.getByRole('button', { name: /Sign in with SSO/ }).click()
  await expect(tab(page, /Discover/)).toBeVisible()
}

// Tab accessible names concatenate the label with its subtitle span ("Discover inventory ·
// classify"), and a completed tab gains a visually-hidden "completed: " prefix. Both break
// exact-name matching, so match on substring instead.
export const tab = (page, re) => page.locator('[role="tab"]', { hasText: re })

// Every scan entry point routes through App.requestScan, which only opens this modal; the
// wizard's last forward click is the sole thing that dispatches a scan.
export async function runDiscovery(page) {
  await page.getByRole('button', { name: 'Re-scan all sources' }).click()
  const modal = page.getByRole('dialog', { name: 'New discovery' })
  await expect(modal).toBeVisible()
  // Three steps: source/folders → lifecycle rules → review, where forward means "run".
  for (let i = 0; i < 3; i += 1) await modal.locator('[data-wizard-forward]').click()
  await expect(modal).toBeHidden()
}
