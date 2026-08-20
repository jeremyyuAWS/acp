// A raw provider error, rendered straight at the user.
//
// From the New-scan wizard on 2026-08-20, inside the folder browser:
//
//   ⚠️ Could not load folders
//   Microsoft Graph error: Client error '400 Bad Request' for url 'https://graph.microsoft.c…
//   C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_iMGlvE5bq1X9RbBtVHxKCWcp/items/…
//
// Three problems at once: it reads as a broken product, it leaks drive ids and internal URL
// structure to anyone looking at the screen, and it tells the person nothing they can act on.
//
// WHAT THIS DOES NOT DO IS GUESS. The obvious rewrite — "your connection may need to be
// refreshed" — would have been WRONG about that exact error: the 400 was a malformed URL we built
// ourselves (#501), not an expired token. Telling the user to reconnect would have sent them to
// re-authorise a connection that was working perfectly, and the real bug would have stayed hidden
// behind a plausible sentence. That is the #483 defect ("stop guessing 'unreadable'") in a new
// place: an invented cause is worse than a stated absence, because it is actionable and wrong.
//
// So the cause is CLASSIFIED from the error, and where it cannot be classified the copy says the
// load failed and offers a retry — without naming a reason nobody established.

/** Auth failures: the one case where "reconnect" is genuinely the remedy. */
const AUTH = /\b(401|403)\b|unauthori[sz]ed|forbidden|invalid[_ -]?grant|token[_ -]?expired|expired/i
/** The caller's request was malformed or the item is gone — not something the user can fix. */
const REQUEST = /\b(400|404)\b|bad request|not found/i
/** Transport: worth retrying as-is. */
const NETWORK = /network|timeout|timed out|fetch failed|econnreset|502|503|504|gateway/i

/**
 * Turn a raw error into something a person can act on.
 *
 * Returns `{ title, body, action }` where `action` is one of:
 *   'retry'     — try the same thing again
 *   'reconnect' — the credential is the problem
 *   'report'    — we built a bad request; retrying will not help
 *
 * `sourceName` names the provider in the sentence ("SharePoint", "Google Drive") so the reader
 * knows which connection is being talked about when several are wired up.
 */
export function friendlyFolderError(raw, sourceName = 'the source') {
  const text = String(raw || '')
  if (AUTH.test(text)) {
    return {
      title: 'We couldn’t load your folders',
      body: `Your ${sourceName} connection needs to be re-authorised. Reconnect the source and try again.`,
      action: 'reconnect',
    }
  }
  if (REQUEST.test(text)) {
    // Deliberately NOT "check your connection". A 400 is ours; a 404 means the folder moved or was
    // deleted. Neither is fixed by re-authorising, and saying so would waste the user's time on
    // the wrong remedy — which is exactly what happened to the error this module was written for.
    return {
      title: 'We couldn’t load your folders',
      body: `${capitalise(sourceName)} rejected the request for this folder. It may have been moved or `
        + 'deleted — go back a level and try another, or report this if it keeps happening.',
      action: 'report',
    }
  }
  if (NETWORK.test(text)) {
    return {
      title: 'We couldn’t load your folders',
      body: `Could not reach ${sourceName}. This is usually temporary.`,
      action: 'retry',
    }
  }
  // Unclassified. Says what happened and offers the one safe action, and NAMES NO CAUSE — the
  // technical detail is one click away for whoever can read it.
  return {
    title: 'We couldn’t load your folders',
    body: `Something went wrong retrieving the folder list from ${sourceName}.`,
    action: 'retry',
  }
}

const capitalise = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)

/** The label on the primary recovery button, matched to the classified cause. */
export const actionLabel = (action) => (action === 'reconnect' ? 'Reconnect source' : 'Try again')

/**
 * How many skeleton rows to show while loading.
 *
 * An empty bordered box reads as "this folder has no subfolders" — a fact the picker states
 * elsewhere in the same space, and the reading that leads somebody to give up narrowing and scan
 * everything. Rows that are visibly placeholders say "not yet" instead of "none".
 */
export const SKELETON_ROWS = 5
