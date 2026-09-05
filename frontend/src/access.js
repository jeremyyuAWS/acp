// What the signed-in user may see, decided in one place.
//
// The server hands the SPA an access payload (GET /me/access, and the same object on
// /workspace/bootstrap's `me.access`). This module turns it into the four questions the UI asks:
// which tabs to render, what number each carries, where to send someone who has landed somewhere
// they may not be, and whether a call to action says "Start" or "View".
//
// THIS IS NOT A SECURITY CONTROL AND MUST NOT BE READ AS ONE. Every route enforces its own
// capability server-side (PRD §11); this only decides what to OFFER. The PRD opens by saying so —
// "Hiding a tab alone is not considered a security control" — and the practical consequence is
// the direction this file fails in:
//
//     NO ACCESS PAYLOAD  ->  EVERYTHING IS VISIBLE.
//
// which looks like fail-open and is the correct behaviour for a surface that is not the control.
// `access` is absent for a signed-out shell, during the first render before bootstrap answers, in
// SIM mode, and against a server built before this feature. Blanking the navigation in any of
// those would be a UI that breaks itself while protecting nothing — the server still refuses
// whatever the user clicks. The fail-CLOSED direction lives where it can actually deny: the
// resolver in api/workspace_roles.py, which answers "nothing" when it cannot establish a role.
//
// The distinction that makes both correct: an ABSENT payload means "not told", a payload with a
// tab set to `hidden` means "told: no". Only the second hides anything here.

export const HIDDEN = 'hidden'
export const VIEW = 'view'
export const OPERATE = 'operate'

// Tabs this feature does not govern (PRD §6 lists ten; these are not among them). `acr` is
// authorized per-report by its own boundary, and `graph` was simply never specified — see
// UNGOVERNED_TABS in api/workspace_rbac.py, which pins the same two server-side. They are always
// visible, so a role cannot accidentally hide a surface nobody decided to govern.
export const UNGOVERNED = new Set(['acr', 'graph'])

/** The access level for one tab key: 'hidden' | 'view' | 'operate'. */
export function levelFor(access, key) {
  if (UNGOVERNED.has(key)) return OPERATE
  const tabs = access?.tabs
  if (!tabs) return OPERATE                    // not told — see the header
  const level = tabs[key]
  // A key the payload does not mention is a tab this build has that the server does not know
  // about. Treated as ungoverned rather than hidden: hiding it would make a NEWER frontend lose
  // surfaces against an older API, which is a broken deploy rather than a permission decision.
  return level === undefined ? OPERATE : level
}

export const isVisible = (access, key) => levelFor(access, key) !== HIDDEN
export const canOperate = (access, key) => levelFor(access, key) === OPERATE
export const isViewOnly = (access, key) => levelFor(access, key) === VIEW

/** Does the user hold this capability? Used for the actions a tab's level does not decide. */
export function hasCapability(access, capability) {
  const caps = access?.capabilities
  if (!caps) return true                       // not told — see the header
  return caps.includes(capability)
}

/**
 * The tabs to render, renumbered so the workflow reads 1..n over what is actually there.
 *
 * PRD §10: "Workflow numbering should remain logical among visible tabs." Without this a role
 * that hides Discover renders a workflow starting at step 2, which tells the user they have
 * missed something rather than that it was never theirs to do. Utility tabs (step 0) keep 0.
 *
 * Takes the TABS table rather than importing it, so this module stays free of App.jsx and can be
 * tested against a small fixture.
 */
export function visibleTabs(access, tabs) {
  let step = 0
  return tabs
    .filter(([key]) => isVisible(access, key))
    .map(([key, label, rg, originalStep]) => [
      key, label, rg, originalStep > 0 ? ++step : 0, levelFor(access, key),
    ])
}

/**
 * Where to send someone whose current view is not open to them (PRD §10).
 *
 * Returns the first VISIBLE tab in workflow order, or null when nothing is visible at all —
 * which is a real state (an unassigned user under enforcement) and must not be papered over with
 * a default, because sending them to a tab they cannot open produces a redirect loop.
 */
export function firstPermittedTab(access, tabs) {
  const found = tabs.find(([key]) => isVisible(access, key))
  return found ? found[0] : null
}

/**
 * The label and destination for a workflow call to action, or null when there is nowhere to go.
 *
 * PRD §10 asks for three things and they are one decision: a CTA must not lead to a hidden tab;
 * a view-only destination says "View" rather than "Start"; and the wording has to match what the
 * user will actually be able to do when they arrive. Getting the first two right and the third
 * wrong is worse than not gating at all — the button works, and it lied about what it does.
 */
export function ctaFor(access, key, { start, view } = {}) {
  const level = levelFor(access, key)
  if (level === HIDDEN) return null
  return { to: key, label: level === OPERATE ? (start ?? 'Start') : (view ?? 'View'), level }
}

/**
 * Why a restricted screen is being shown, in words a person can act on (PRD §10).
 *
 * Names the missing permission and nothing else. It must not describe what is behind the tab —
 * "3 documents await your review in Remediate" tells somebody without access to Remediate both
 * that it exists and how much is in it, which is the leak §10's notification rule is also about.
 */
/**
 * Is this person waiting for an administrator to give them a role?
 *
 * A DIFFERENT ANSWER FROM "RESTRICTED", which is why it is a separate question. Restricted means
 * a role was chosen and this tab is not in it. Pending means nobody has chosen yet: the server
 * created their record on first sign-in (just-in-time roster creation) on a deployment that
 * configures no default role, so the honest thing to show is that they are in the queue — not
 * that they lack a permission, which invites them to ask for the wrong thing.
 *
 * Read off an explicit server flag rather than inferred from "no role and no tabs". Those two are
 * also true of a suspended user and of a role id whose row has gone missing, and telling someone
 * whose access was deliberately withdrawn that they are awaiting approval would be worse than
 * saying nothing.
 */
export const isAccessPending = (access) => Boolean(access?.pending)

/**
 * May this user open Platform settings?
 *
 * `settings` IS A GOVERNED TAB — api/workspace_rbac.TABS lists it with the other nine — and it is
 * the only one the SPA renders as a MODAL rather than a pane. So `visibleTabs` never covers it,
 * and until 2026-09-05 nothing else did: App.jsx's gear, its click handler and the modal all
 * tested `me.allow` alone, the legacy persona list, which App.jsx unions with EVERY tab key under
 * the temporary 2026-09-04 navigation policy. `settings: hidden` was therefore true of four
 * built-in roles — Compliance Manager, Remediation Reviewer, Analyst, Viewer — and meant nothing
 * for any of them.
 *
 * Not an escalation: People and Roles management is gated server-side on `people.manage` /
 * `roles.manage`, and the destructive actions are owner-only. But a tab the role says is hidden
 * was fully reachable, which is exactly what the `navigation` rung exists to make untrue.
 *
 * BOTH SOURCES, and they genuinely disagree. `me.allow` is narrower than the RBAC payload in SIM
 * and demo personas (sim.js gives `settings` to one of four), and the payload is narrower than
 * `me.allow` under a real role. Requiring both means this can only ever hide the panel from
 * somebody who could already see it — never reveal it to somebody who could not — which is the
 * only safe direction for a change that ships ahead of the rollout it serves.
 *
 * Lives here rather than in App.jsx because this is the module that decides what the UI offers,
 * and because a predicate inside a 2000-line component cannot be tested with both inputs held.
 */
export const canOpenSettings = (me, access) =>
  Boolean(me?.allow?.includes('settings')) && isVisible(access, 'settings')

export function restrictionReason(access, key, label) {
  const name = label || key
  if (!access?.enforced) return `${name} is not available in this workspace.`
  const role = access?.role?.name
  return role
    ? `${name} is not part of your ${role} role. Ask an administrator if you need access to it.`
    : `You have no workspace role yet, so ${name} is not available. Ask an administrator to assign you one.`
}
