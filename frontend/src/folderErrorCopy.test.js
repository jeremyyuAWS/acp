/**
 * A raw provider error, rendered straight at the user — and the rewrite that would have lied.
 *
 * What was on screen in the New-scan wizard on 2026-08-20:
 *
 *   ⚠️ Could not load folders
 *   Microsoft Graph error: Client error '400 Bad Request' for url 'https://graph.microsoft.c…
 *   C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_iMGlvE5bq1X9RbBtVHxKCWcp/items/…
 *
 * The obvious rewrite is "your connection may need to be refreshed". Applied to THAT error it
 * would have been wrong: the 400 came from a URL we built ourselves (#501), not an expired token.
 * The user would have been sent to re-authorise a working connection while the real bug stayed
 * hidden behind a plausible sentence — #483's "stop guessing 'unreadable'" in a new place.
 *
 * So these cases pin the classification, and the one that matters most is the negative: a 400 must
 * NOT produce reconnect advice.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { friendlyFolderError, actionLabel, SKELETON_ROWS } from './folderErrorCopy.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

// The real thing, verbatim from production.
const REAL_400 = "Microsoft Graph error: Client error '400 Bad Request' for url "
  + "'https://graph.microsoft.com/v1.0/drives/b!C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_"
  + "iMGlvE5bq1X9RbBtVHxKCWcp/items/b!C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_iMGlvE5bq1X9"
  + "RbBtVHxKCWcp/01UABC/children?$select=id,name,folder,parentReference&$top=200'"

describe('the error that prompted this', () => {
  it('does NOT tell the user to reconnect a working connection', () => {
    // THE case. Actionable and wrong is worse than general and honest.
    const e = friendlyFolderError(REAL_400, 'SharePoint')
    expect(e.action, 'a malformed request was blamed on the credential').not.toBe('reconnect')
    expect(e.body).not.toMatch(/re-authoris|reconnect/i)
  })

  it('says something the reader can act on', () => {
    const e = friendlyFolderError(REAL_400, 'SharePoint')
    expect(e.title).toMatch(/couldn’t load your folders/i)
    expect(e.body).toMatch(/SharePoint/)
    expect(e.body).toMatch(/moved or deleted|report this/i)
  })

  it('keeps no drive id or URL in the user-facing sentence', () => {
    // The raw text stays available behind the disclosure; it does not belong on the first screen.
    const e = friendlyFolderError(REAL_400, 'SharePoint')
    const shown = `${e.title} ${e.body}`
    expect(shown).not.toMatch(/graph\.microsoft\.com/)
    expect(shown).not.toMatch(/C4KL1AKEIU2Bh5cDUao2FK/)
    expect(shown).not.toMatch(/\$select|\$top/)
  })
})

describe('the cases that ARE the credential', () => {
  it('classifies a 401 as needing a reconnect', () => {
    const e = friendlyFolderError('Error: 401 Unauthorized', 'SharePoint')
    expect(e.action).toBe('reconnect')
    expect(e.body).toMatch(/re-authoris/i)
  })

  it('classifies a 403 and an expired token the same way', () => {
    expect(friendlyFolderError('403 Forbidden').action).toBe('reconnect')
    expect(friendlyFolderError('token_expired').action).toBe('reconnect')
  })

  it('labels the button for the remedy it is offering', () => {
    expect(actionLabel('reconnect')).toBe('Reconnect source')
    expect(actionLabel('retry')).toBe('Try again')
    expect(actionLabel('report')).toBe('Try again')
  })
})

describe('transport and the unknown', () => {
  it('treats a network failure as temporary', () => {
    expect(friendlyFolderError('TypeError: fetch failed').action).toBe('retry')
    expect(friendlyFolderError('504 Gateway Timeout').action).toBe('retry')
  })

  it('names NO cause when it cannot classify one', () => {
    // The honest fallback: what happened, one safe action, no invented reason.
    const e = friendlyFolderError('something entirely novel', 'SharePoint')
    expect(e.action).toBe('retry')
    expect(e.body).toMatch(/Something went wrong/)
    expect(e.body, 'a cause was invented for an unclassified error')
      .not.toMatch(/re-authoris|expired|moved or deleted/i)
  })

  it('survives null and undefined rather than throwing', () => {
    for (const bad of [null, undefined, '']) {
      expect(friendlyFolderError(bad).title).toMatch(/couldn’t load/i)
    }
  })
})

describe('the picker actually uses this', () => {
  // The classifier being right proves nothing about anything calling it — the #491 lesson. The DOM
  // half is in folderErrorState.test.jsx; these pin the wiring.
  const src = read('FolderPicker.jsx')

  it('renders the classified error, not the raw one, as the message', () => {
    expect(src).toMatch(/friendlyFolderError\(err, sourceName\)/)
    expect(src, 'the raw error is still the headline').not.toMatch(/marginBottom: 4 \}\}>\s*\{err\}/)
  })

  it('keeps the raw text reachable behind a disclosure', () => {
    // Hiding it entirely would cost support the only thing that identifies the failure.
    expect(src).toMatch(/Technical details/)
    expect(src).toMatch(/<pre[^>]*>\{err\}<\/pre>/)
  })

  it('offers a retry that re-runs the same load', () => {
    expect(src).toMatch(/onClick=\{\(\) => load\(current\.id\)\}/)
  })

  it('shows skeleton rows rather than an empty box while loading', () => {
    expect(src).toMatch(/SKELETON_ROWS/)
    expect(src, 'the old centred "Loading…" is back').not.toMatch(/>\s*Loading…\s*</)
  })

  it('uses a screen-reader class this codebase actually defines', () => {
    // `visually-hidden` is not defined here; using it would render the loading text visibly — an
    // accessibility product shipping a visible string meant to be announced only.
    expect(read('styles.css')).toMatch(/\.sronly\s*\{/)
    expect(src).toMatch(/className="sronly"/)
  })
})

describe('the skeleton', () => {
  it('is more than one row, or it reads as a single stuck item', () => {
    expect(SKELETON_ROWS).toBeGreaterThan(2)
  })
})
