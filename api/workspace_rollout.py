"""PRD §15's staged rollout, as four states instead of one boolean.

Slices 1–5 shipped behind `ACP_WORKSPACE_RBAC_ENABLED`, which is on or off. §15 does not ask for
on or off; it asks for a LADDER, and the rungs exist because they fail differently:

    off          nothing changes. Roles can be designed and assigned; nothing reads them.
    observe      roles are resolved and the decision is RECORDED, but everyone keeps today's
                 access. This is the rung that produces evidence.
    navigation   the SPA hides tabs a role does not grant; the server still allows the call.
    enforce      the server refuses. What slices 4–5 shipped.

WHY THE MIDDLE TWO ARE NOT CEREMONY. Skipping from `off` to `enforce` is a single deployment in
which every wrong permission becomes a 403 for a real user doing real work, and the first you hear
of it is a support ticket. The two intermediate rungs each remove one class of that risk before it
can bite:

  * `observe` answers "who WOULD we have refused?" from production traffic, at zero user impact.
    A capability map that is subtly wrong — a route mapped to a capability the role that needs it
    does not hold — is invisible in tests, because tests assert the mapping we intended. Only real
    traffic exercises the mapping we actually wrote.
  * `navigation` removes the worst UX failure independently: a user clicking a tab and getting a
    wall of 403s. Hiding the tab first means that by the time the server refuses, nothing in the
    product invites the click.

THE LADDER IS ORDERED, AND CODE ASKS ABOUT RUNGS RATHER THAN NAMES. `at_least(NAVIGATION)` rather
than `mode() in ("navigation", "enforce")` — the second is a list every new rung has to be added
to by hand, and the one place somebody forgets is a permission check that silently stops applying.
This is the same shape as workspace_rbac.access_at_least for the same reason.

FAIL-CLOSED DOES NOT MEAN "TREAT CONFUSION AS ENFORCE". An unreadable mode is not an operator
asking for enforcement; it is an operator whose intent we do not know. Enforcing on a typo would
lock a workspace out on a deploy nobody thought was risky, and §15's own rule is that migration
must not unexpectedly remove access. So an unrecognised value falls back — but LOUDLY, and never
by silently discarding a legacy variable that IS readable (see mode()).
"""
from __future__ import annotations

import os

# The variable this slice introduces. The legacy one still works; see mode().
MODE_VAR = "ACP_WORKSPACE_RBAC_MODE"
LEGACY_VAR = "ACP_WORKSPACE_RBAC_ENABLED"

OFF = "off"
OBSERVE = "observe"
NAVIGATION = "navigation"
ENFORCE = "enforce"

# Ordered lowest to highest. Membership and comparison both read from this one tuple, so a new
# rung cannot be added to one and forgotten in the other.
LADDER = (OFF, OBSERVE, NAVIGATION, ENFORCE)

_TRUTHY = ("1", "true", "yes", "on")

# What each rung means to an operator, in the terms they will judge it by: what the user
# experiences, and what it costs. Kept next to the definitions rather than in a document, because
# the document is the thing that goes stale — the preflight report serves these strings, so what
# an operator reads is what the code does.
DESCRIPTIONS = {
    OFF: "Roles are designed and assigned but nothing reads them. No user is affected.",
    OBSERVE: ("Roles are resolved and refusals are recorded, but every user keeps today's access. "
              "Use this to find wrong permissions before they can refuse anybody."),
    NAVIGATION: ("Tabs a role does not grant are hidden. The server still allows the calls, so a "
                 "direct URL or a stale browser tab still works."),
    ENFORCE: ("The server refuses calls a role does not permit. Hiding a tab is no longer the "
              "control; this is."),
}


def _normalise(raw: str | None) -> str | None:
    """A recognised rung, or None. None means "this string told us nothing", which is a different
    fact from OFF and is why the return is not just `OFF`."""
    value = (raw or "").strip().lower()
    return value if value in LADDER else None


def mode() -> str:
    """The rung this process is running at.

    PRECEDENCE, AND THE ORDER IS THE INTERESTING PART:

      1. A VALID `ACP_WORKSPACE_RBAC_MODE` wins. It is the specific instruction.
      2. Otherwise `ACP_WORKSPACE_RBAC_ENABLED=1` means `enforce`. This is not a courtesy — it is
         the deployed contract. Slices 1–5 shipped that variable, an operator may already have it
         set, and a release that quietly stopped honouring it would turn enforcement OFF in a
         workspace that believed it was enforcing. Removing a security control by renaming its
         switch is the failure mode; the alias is how it is avoided.
      3. Otherwise off.

    An UNREADABLE mode falls through to (2) rather than jumping to (1)'s failure. If somebody
    typos `enfoce` while `ACP_WORKSPACE_RBAC_ENABLED=1` is still set, the readable variable is
    still an instruction and is still obeyed. Only when nothing readable remains do we land on
    off — and `invalid_mode()` stays true either way, so the typo is reported rather than absorbed.
    """
    explicit = _normalise(os.environ.get(MODE_VAR))
    if explicit:
        return explicit
    if os.environ.get(LEGACY_VAR, "").strip().lower() in _TRUTHY:
        return ENFORCE
    return OFF


def invalid_mode() -> str | None:
    """The unrecognised value of `ACP_WORKSPACE_RBAC_MODE`, if one is set, else None.

    THIS EXISTS SO A TYPO CANNOT BE SILENT. The dangerous direction is an operator advancing to
    enforcement who misspells it: the workspace runs unenforced while its owner believes otherwise,
    and nothing in the product looks wrong — an unenforced deployment behaves exactly like one
    nobody has got to yet. So the bad value is kept rather than discarded, and every surface that
    reports the mode (the preflight report, /me/access, the Roles screen) reports this too.
    """
    raw = (os.environ.get(MODE_VAR) or "").strip()
    return raw if raw and _normalise(raw) is None else None


def at_least(minimum: str) -> bool:
    """Is the current rung at or above `minimum`?"""
    try:
        return LADDER.index(mode()) >= LADDER.index(minimum)
    except ValueError:
        # An unknown `minimum` is a programming error in the CALLER, not a configuration problem,
        # and answering True would grant on a typo. Answer False and let the feature look off.
        return False


def roles_resolved() -> bool:
    """Should a role be looked up at all? False at `off`, where the store is never touched."""
    return at_least(OBSERVE)


def navigation_active() -> bool:
    """Do a role's tabs govern what the SPA shows? True from `navigation` up."""
    return at_least(NAVIGATION)


def enforcement_active() -> bool:
    """Does the server refuse? True only at `enforce`.

    The narrowest of the three on purpose. Every other predicate can be wrong and cost clarity;
    this one being wrong costs either an outage or a hole.
    """
    return mode() == ENFORCE


def next_stage(current: str | None = None) -> str | None:
    """The rung above `current`, or None at the top. Used by the preflight report so "what would
    I be advancing to?" is answered by the ladder rather than by the operator's memory."""
    at = current or mode()
    if at not in LADDER or at == LADDER[-1]:
        return None
    return LADDER[LADDER.index(at) + 1]


def describe() -> dict:
    """The rollout state as an API payload.

    Carries `legacy_flag` because the two variables can disagree — MODE=observe with ENABLED=1 is
    a rollback in progress, and an operator reading only the effective mode cannot see the stale
    variable they still need to remove.
    """
    current = mode()
    return {
        "mode": current,
        "means": DESCRIPTIONS.get(current, ""),
        "enforcing": enforcement_active(),
        "navigation": navigation_active(),
        "next": next_stage(current),
        "ladder": list(LADDER),
        "invalid_mode": invalid_mode(),
        "legacy_flag": os.environ.get(LEGACY_VAR, "").strip().lower() in _TRUTHY,
    }
