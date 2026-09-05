// The SPA's half of workspace roles: which tabs render, numbered how, and what the buttons say.
//
// THE ASYMMETRY THIS FILE PINS, because it looks like a bug until you know why:
//
//     no access payload  ->  everything visible        (this file, the UI)
//     no resolvable role ->  nothing at all            (api/workspace_roles.py, the server)
//
// Opposite directions, both correct, because they are answering different questions. The UI is
// not the security control — PRD §11 — so an absent payload (signed out, first render, SIM mode,
// an older API) must not blank the navigation: that breaks the app while protecting nothing,
// since the server refuses whatever gets clicked anyway. The server, which IS the control, treats
// "cannot establish a role" as a refusal.
//
// The distinction that makes both hold: ABSENT means "not told"; a tab explicitly set to `hidden`
// means "told: no". Only the second hides anything here, and the tests below check both halves —
// because a implementation that hid things when not told would pass every test written about
// hiding, and take the app down for every signed-out visitor.
import { describe, it, expect } from 'vitest'
import { levelFor, isVisible, canOperate, isViewOnly, hasCapability, visibleTabs, firstPermittedTab, ctaFor, restrictionReason, UNGOVERNED, canOpenSettings } from './access.js'

// The shape App.jsx's TABS has: [key, label, rubric-gloss, workflow step].
const TABS = [
  ['overview', 'Overview', 'at a glance', 0],
  ['integrations', 'Sources', 'connect sources', 0],
  ['discover', 'Discover', 'inventory · classify', 1],
  ['assess', 'Assess', 'score vs WCAG', 2],
  ['remediate', 'Remediate', 'fix issues', 3],
  ['publish', 'Release', 'approve & deploy', 4],
  ['monitor', 'Monitor', 'track compliance', 5],
  ['liveops', 'Live Operations', 'Azure traffic', 0],
  ['analytics', 'Scan Analytics', 'compare scans', 0],
  ['acr', 'Conformance', 'ACR / VPAT', 0],
]

/** A Remediation Reviewer, as GET /me/access actually returns one. */
const reviewer = {
  enforced: true,
  role: { id: 'remediation-reviewer', name: 'Remediation Reviewer' },
  tabs: {
    overview: 'view', integrations: 'view', discover: 'view', assess: 'view',
    remediate: 'operate', publish: 'view', monitor: 'view',
    liveops: 'hidden', analytics: 'view', settings: 'hidden',
  },
  capabilities: ['remediate.view', 'remediate.run', 'remediate.review', 'reports.export'],
}

const nothing = { enforced: true, role: null, tabs: Object.fromEntries(
  ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor',
   'liveops', 'analytics', 'settings'].map((k) => [k, 'hidden'])), capabilities: [] }

// ── not told vs told no ───────────────────────────────────────────────────────

describe('an absent payload shows everything', () => {
  it.each([null, undefined, {}, { enforced: false }])('renders every tab for %o', (access) => {
    expect(visibleTabs(access, TABS)).toHaveLength(TABS.length)
    expect(isVisible(access, 'remediate')).toBe(true)
    expect(canOperate(access, 'remediate')).toBe(true)
  })

  it('grants every capability when not told', () => {
    // The UI asks this to decide whether to render a button. Answering "no" while the server has
    // said nothing would remove working controls from every signed-out or SIM-mode session.
    expect(hasCapability(null, 'release.publish')).toBe(true)
    expect(hasCapability({}, 'anything.at.all')).toBe(true)
  })

  it('hides only what it was explicitly told to hide', () => {
    expect(isVisible(reviewer, 'liveops')).toBe(false)
    expect(isVisible(reviewer, 'remediate')).toBe(true)
    expect(hasCapability(reviewer, 'release.publish')).toBe(false)
  })

  it('treats a tab the payload never mentions as ungoverned, not hidden', () => {
    // A newer frontend against an older API. Hiding the tab it does not know about would turn a
    // version skew into a user losing surfaces, which is a broken deploy dressed up as a
    // permission decision.
    expect(isVisible(reviewer, 'a-tab-shipped-later')).toBe(true)
  })
})

describe('the two ungoverned tabs stay reachable', () => {
  it.each([...UNGOVERNED])('%s is visible even when everything else is hidden', (key) => {
    expect(isVisible(nothing, key)).toBe(true)
    expect(canOperate(nothing, key)).toBe(true)
  })

  it('matches the set the server pins', () => {
    // api/workspace_rbac.py's UNGOVERNED_TABS. Two lists, one fact: if they diverge, a tab is
    // governed on one side and not the other, and which one wins depends on where you look.
    expect([...UNGOVERNED].sort()).toEqual(['acr', 'graph'])
  })
})

// ── the three levels ──────────────────────────────────────────────────────────

describe('levels', () => {
  it('separates seeing from doing', () => {
    expect(isVisible(reviewer, 'assess')).toBe(true)
    expect(canOperate(reviewer, 'assess')).toBe(false)
    expect(isViewOnly(reviewer, 'assess')).toBe(true)

    expect(canOperate(reviewer, 'remediate')).toBe(true)
    expect(isViewOnly(reviewer, 'remediate')).toBe(false)
  })

  it('reports hidden as hidden rather than as view', () => {
    expect(levelFor(reviewer, 'liveops')).toBe('hidden')
    expect(isVisible(reviewer, 'liveops')).toBe(false)
    expect(isViewOnly(reviewer, 'liveops')).toBe(false)
  })
})

// ── numbering (PRD §10) ───────────────────────────────────────────────────────

describe('the workflow renumbers over the tabs that are actually there', () => {
  it('leaves 1..5 alone when nothing is hidden', () => {
    const steps = visibleTabs(null, TABS).filter(([, , , s]) => s > 0).map(([, , , s]) => s)
    expect(steps).toEqual([1, 2, 3, 4, 5])
  })

  it('closes the gap when a workflow tab is hidden', () => {
    // Without this the stepper reads 2,3,4,5 and tells the user they have skipped step 1 —
    // which is a different message from "step 1 was never yours".
    const access = { ...reviewer, tabs: { ...reviewer.tabs, discover: 'hidden' } }
    const shown = visibleTabs(access, TABS)
    expect(shown.map(([k]) => k)).not.toContain('discover')
    expect(shown.filter(([, , , s]) => s > 0).map(([, , , s]) => s)).toEqual([1, 2, 3, 4])
    expect(shown.find(([k]) => k === 'assess')[3]).toBe(1)
  })

  it('keeps utility tabs unnumbered', () => {
    const shown = visibleTabs(null, TABS)
    expect(shown.find(([k]) => k === 'overview')[3]).toBe(0)
    expect(shown.find(([k]) => k === 'analytics')[3]).toBe(0)
  })

  it('carries each tab’s level through, so the nav can style view-only', () => {
    const shown = visibleTabs(reviewer, TABS)
    expect(shown.find(([k]) => k === 'remediate')[4]).toBe('operate')
    expect(shown.find(([k]) => k === 'assess')[4]).toBe('view')
  })
})

// ── where to send someone ─────────────────────────────────────────────────────

describe('firstPermittedTab', () => {
  it('is the first VISIBLE tab in workflow order', () => {
    const access = { ...reviewer, tabs: { ...reviewer.tabs, overview: 'hidden', integrations: 'hidden' } }
    expect(firstPermittedTab(access, TABS)).toBe('discover')
  })

  it('is null when nothing is open, rather than a default that bounces', () => {
    // An unassigned user under enforcement. Returning 'overview' here would redirect them to a
    // tab that redirects them again — a loop, from code that looks like a sensible fallback.
    const govern = TABS.filter(([k]) => !UNGOVERNED.has(k))
    expect(firstPermittedTab(nothing, govern)).toBeNull()
  })

  it('finds the ungoverned tab when that is genuinely all there is', () => {
    expect(firstPermittedTab(nothing, TABS)).toBe('acr')
  })
})

// ── calls to action (PRD §10) ─────────────────────────────────────────────────

describe('a CTA never points somewhere the user cannot go', () => {
  it('is null for a hidden destination', () => {
    expect(ctaFor(reviewer, 'liveops')).toBeNull()
  })

  it('says Start when the destination is operable', () => {
    expect(ctaFor(reviewer, 'remediate', { start: 'Start remediation', view: 'View remediation' }))
      .toEqual({ to: 'remediate', label: 'Start remediation', level: 'operate' })
  })

  it('says View when the destination is read-only', () => {
    // The failure this prevents is subtle and worse than a broken link: the button WORKS, the
    // user arrives, and nothing they were promised is available. A label that lied is harder to
    // report than a button that was not there.
    expect(ctaFor(reviewer, 'assess', { start: 'Start assessment', view: 'View assessment' }))
      .toEqual({ to: 'assess', label: 'View assessment', level: 'view' })
  })

  it('offers the destination when nothing was told', () => {
    expect(ctaFor(null, 'remediate')?.label).toBe('Start')
  })
})

// ── the restricted screen's words ─────────────────────────────────────────────

describe('restrictionReason', () => {
  it('names the role so the user knows what to ask for', () => {
    const msg = restrictionReason(reviewer, 'liveops', 'Live Operations')
    expect(msg).toContain('Live Operations')
    expect(msg).toContain('Remediation Reviewer')
  })

  it('says so plainly when there is no role at all', () => {
    expect(restrictionReason(nothing, 'remediate', 'Remediate')).toContain('no workspace role')
  })

  it('never describes what is behind the tab', () => {
    // §10: "identifies the missing permission without exposing protected data." The helpful
    // version — "3 documents await review" — tells someone without access both that the tab
    // exists and how much is in it.
    const msg = restrictionReason(reviewer, 'liveops', 'Live Operations')
    expect(msg).not.toMatch(/\d/)
    expect(msg.toLowerCase()).not.toContain('document')
    expect(msg.toLowerCase()).not.toContain('finding')
  })
})


describe('the settings modal', () => {
  // `settings` is a governed tab that renders as a modal, so `visibleTabs` never covers it and
  // App.jsx gated it on `me.allow` alone — a list the temporary 2026-09-04 navigation policy
  // unions with every tab key, making `settings: hidden` meaningless for the four built-in roles
  // that specify it. Both inputs are held here because the two sources genuinely disagree, in
  // both directions, and a predicate over two sources cannot be tested from one of them.
  const allowed = { allow: ['overview', 'settings'] }

  it('opens when the persona allows it and the role does not hide it', () => {
    expect(canOpenSettings(allowed, { tabs: { settings: 'operate' } })).toBe(true)
    expect(canOpenSettings(allowed, { tabs: { settings: 'view' } })).toBe(true)
  })

  it('is closed to a role whose settings tab is hidden', () => {
    expect(canOpenSettings(allowed, { tabs: { settings: 'hidden' } })).toBe(false)
  })

  it('is closed to a persona without it, whatever the role says', () => {
    // The other direction, and it is not symmetric: SIM personas are narrower than any role.
    expect(canOpenSettings({ allow: ['overview'] }, { tabs: { settings: 'operate' } })).toBe(false)
  })

  it('opens with no access payload at all — the deliberate fail-open', () => {
    // access.js's header: an ABSENT payload means "not told", and this is presentation rather
    // than protection. A signed-out shell, the first render before bootstrap answers, SIM mode
    // and an older server all land here; blanking the panel in those would break the UI while
    // protecting nothing, since every route behind it enforces its own capability.
    expect(canOpenSettings(allowed, null)).toBe(true)
    expect(canOpenSettings(allowed, {})).toBe(true)
  })

  it('is closed to nobody at all', () => {
    expect(canOpenSettings(null, { tabs: { settings: 'operate' } })).toBe(false)
    expect(canOpenSettings(undefined, null)).toBe(false)
  })
})
