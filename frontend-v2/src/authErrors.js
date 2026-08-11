// Turn a raw MSAL / Entra sign-in error into one plain sentence a non-admin can act on.
//
// The demo-killers during rollout were the raw strings — "popup_window_error", a bare
// "AADSTS50020: ...", "interaction_in_progress" — shown verbatim on the login screen. Sign-in is
// the very first thing a user hits, and these read as "the app is broken" when the real cause is
// almost always "wrong account" or "browser blocked the popup". This maps the common ones to
// guidance and, for anything unrecognised, keeps the AADSTS code (which IS useful to an admin)
// rather than a wall of text.
export function friendlyAuthError(e) {
  const code = (e && e.errorCode) || ''
  const msg = (e && (e.errorMessage || e.message)) || ''
  const aadsts = (msg.match(/AADSTS\d+/) || [])[0] || ''

  // ── browser / interaction, before we ever reach Microsoft ──
  if (code === 'user_cancelled') return 'Sign-in cancelled.'
  if (code === 'popup_window_error' || code === 'empty_window_error')
    return 'Your browser blocked the sign-in pop-up. Allow pop-ups for this site, then try again.'
  if (code === 'interaction_in_progress')
    return 'A previous sign-in is still finishing — give it a moment, then try again.'

  // ── wrong account / wrong tenant (by far the most common in practice) ──
  if (aadsts === 'AADSTS50020' || /does not exist in tenant/i.test(msg))
    return 'That account isn’t set up for this app. Sign in with the work account provided for ACP — not your everyday email.'
  if (aadsts === 'AADSTS700016' || /was not found in the directory/i.test(msg))
    return 'You’re signed in with a different work account. Choose “Use another account” and pick the one provided for ACP.'

  // ── consent / configuration (admin actions) ──
  if (aadsts === 'AADSTS65001' || aadsts === 'AADSTS90094' || /consent/i.test(msg))
    return 'This app needs your Microsoft 365 admin to approve its permissions. Ask your admin to grant consent, then try again.'
  if (aadsts === 'AADSTS50011' || /redirect uri/i.test(msg))
    return 'Sign-in isn’t configured for this web address yet — please contact your administrator.'
  if (aadsts === 'AADSTS50158' || /conditional access/i.test(msg))
    return 'Your organization’s security policy blocked this sign-in. Try from a managed device, or contact IT.'
  if (aadsts === 'AADSTS50126' || /invalid username or password/i.test(msg))
    return 'That username or password wasn’t recognized.'

  // ── fallback: an AADSTS code is worth surfacing (an admin can look it up) ──
  if (aadsts) return `Microsoft sign-in failed (${aadsts}). If it keeps happening, share this code with your administrator.`
  return msg || 'Microsoft sign-in failed. Please try again.'
}
