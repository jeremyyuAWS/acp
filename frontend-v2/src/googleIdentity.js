// Who the Google access token belongs to.
//
// Three call sites fetched this URL and none checked the response. `fetch` only rejects on a
// network failure — a 401 from an expired or wrong-scoped token is a perfectly good response, so
// `.json()` succeeded and handed back Google's ERROR body. What each caller did with that:
//
//   SignIn.jsx        onSignedIn({ id: me.email, … })  →  signed in as `undefined`
//   Integrations.jsx  onConnect('google', me.email || '')  →  connected as ''
//   GoogleDrive.jsx   setUser(u) + sessionStorage  →  the error object cached as the user
//
// The identity is not cosmetic: it is the tenant key the estate is scoped by. Signing someone in
// as undefined is worse than not signing them in, and every one of those call sites ALREADY had
// a correct error path — SignIn even renders "Could not retrieve your Google profile". None of
// them ever ran, because nothing threw.
//
// A tiny module rather than a function on GoogleDrive.jsx: SignIn is the first screen, and it
// should not pull the whole Drive browser into the initial bundle to ask who you are.

const USERINFO = 'https://www.googleapis.com/oauth2/v2/userinfo'

export async function googleUserInfo(accessToken) {
  const r = await fetch(USERINFO, { headers: { Authorization: 'Bearer ' + accessToken } })
  if (!r.ok) {
    // 401/403 here is the token, not the person. Naming that is the difference between "try
    // again" and "your Google sign-in did not grant the profile scope".
    throw new Error(r.status === 401 || r.status === 403
      ? `Google refused the profile request (HTTP ${r.status}) — the access token is expired or `
        + 'was granted without the email/profile scope.'
      : `Google profile lookup failed (HTTP ${r.status}).`)
  }
  const me = await r.json()
  // A 200 with no email is the same failure wearing a success code, and email is the field every
  // caller keys on. Rejecting here means no caller has to remember to check.
  if (!me?.email) throw new Error('Google returned a profile with no email address.')
  return me
}
