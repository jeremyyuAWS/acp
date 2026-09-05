import { firstPermittedTab, isAccessPending, restrictionReason } from './access.js'

// The screen someone sees when they open a tab their role does not include (PRD §10).
//
// WHY A SCREEN AND NOT A SILENT REDIRECT. §10 asks for both — "ACP redirects to the first
// permitted tab" and "a direct link to a restricted tab displays an Access restricted screen" —
// and they are not the same event. Being bounced with no explanation is indistinguishable from
// the app losing your place: a reviewer who follows a colleague's link to Remediate and lands on
// Overview has learned nothing, and will click the link again. So an explicit navigation gets
// this screen, and only the app's own default view redirects (App.jsx), because nobody chose it.
//
// IT SAYS WHAT IS MISSING AND NOTHING ELSE. §10: "identifies the missing permission without
// exposing protected data." That rules out the helpful-looking version — "Remediate · 3 documents
// await review" — which tells someone without access both that the tab exists and how much is
// behind it. The name of the tab is already in the shipped JavaScript; its contents are not.
export default function AccessRestricted({ access, tabKey, label, tabs, onGo }) {
  // ACCESS PENDING IS NOT ACCESS RESTRICTED, and this is the branch the owner asked for on
  // 2026-09-05: "if no default is configured, show 'Access pending' instead of a broken or empty
  // application." A person who arrived through just-in-time roster creation on a deployment that
  // holds new arrivals has every tab hidden, so without this they would meet a screen headed
  // "Access restricted" naming a permission they were never denied — and would go and argue about
  // the wrong thing with the wrong person. They are in a queue, and the screen says so.
  if (isAccessPending(access)) {
    return (
      <section className="access-restricted" role="status" aria-live="polite">
        <h2 className="access-restricted-hd">Access pending</h2>
        <p className="access-restricted-why">
          Your account is set up and an administrator has been asked to give you a role. Nothing in
          this workspace opens until then.
        </p>
        <p className="muted access-restricted-none">
          Signing in again will not change this. An administrator assigns roles from
          Administration → People.
        </p>
      </section>
    )
  }

  const target = firstPermittedTab(access, tabs)
  const targetLabel = target ? (tabs.find(([k]) => k === target) || [])[1] : null
  return (
    <section className="access-restricted" role="status" aria-live="polite">
      <h2 className="access-restricted-hd">Access restricted</h2>
      <p className="access-restricted-why">{restrictionReason(access, tabKey, label)}</p>
      {target ? (
        <button type="button" onClick={() => onGo(target)}>Go to {targetLabel}</button>
      ) : (
        // No permitted tab at all is a real state, not a bug: an unassigned or suspended user
        // under enforcement. Offering a button here would send them somewhere equally closed and
        // bounce them straight back, so it says what to do instead of pretending there is a way on.
        <p className="muted access-restricted-none">
          There is nothing in this workspace open to you yet. An administrator can assign you a
          role from Administration → People.
        </p>
      )}
    </section>
  )
}
