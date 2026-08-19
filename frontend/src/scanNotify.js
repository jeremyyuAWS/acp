// "Notify me when complete" (progress redesign, slice 3c). The strongest control during a long run:
// let the user keep working and get pinged when the scan finishes, instead of watching a spinner —
// "Users should not feel obligated to remain on the page." Uses the browser Notification API, guarded
// so it is a NO-OP (never throws) wherever notifications are unavailable, denied, or the API misbehaves.

export function notificationsSupported() {
  return typeof window !== 'undefined' && typeof window.Notification !== 'undefined'
}

// Whether we can notify without prompting again: granted (yes), denied (no), default (not yet asked).
export function notifyPermission() {
  if (!notificationsSupported()) return 'unsupported'
  try { return window.Notification.permission } catch { return 'unsupported' }
}

// Ask once for permission and report whether a completion notification can be shown. Requests only when
// the state is 'default'; a denied or unsupported environment resolves false rather than nagging.
export async function armNotifyOnComplete() {
  if (!notificationsSupported()) return false
  try {
    const p = window.Notification.permission
    if (p === 'granted') return true
    if (p === 'denied') return false
    const res = await window.Notification.requestPermission()
    return res === 'granted'
  } catch {
    return false
  }
}

// Fire the completion notification. Returns true if one was actually shown. Never throws — a completing
// scan must not fail because a notification could not be posted.
export function notifyScanComplete({ assessed = 0, total = 0, review = 0 } = {}) {
  if (notifyPermission() !== 'granted') return false
  try {
    const body = review > 0
      ? `${assessed} of ${total} assessed · ${review} need review`
      : `${assessed} of ${total} assessed`
    // tag collapses repeats so a re-scan replaces the previous notice rather than stacking.
    new window.Notification('ACP scan complete', { body, tag: 'acp-scan-complete' })
    return true
  } catch {
    return false
  }
}
