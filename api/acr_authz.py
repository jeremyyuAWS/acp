"""ACR roles and the publish gate (PRD §18, §21.11).

WHY THIS IS NOT core.is_admin()
--------------------------------
Under ACP's default OPEN_ACCESS model (api/core.py — `ACP_OPEN_ACCESS` defaults on),
`core.is_admin()` returns True for ANY authenticated, admitted user. That is a deliberate product
decision for the rest of the platform: there is no separate admin view, everyone who can sign in
gets the same screens.

It is the wrong gate for this feature, and quietly so. PRD §21.11 requires that only an approver
may publish an ACR; if "approver" resolves to "anyone who can log in", the requirement is
satisfied on paper and absent in fact — and it would PASS a naive test written on a dev box where
no owner is configured at all (`is_admin` returns True for everyone there too). A published ACR is
an external compliance artifact; that is not a claim to let a default make.

So authority over an ACR is granted in the `acr_role` table and nowhere else. `OPEN_ACCESS` does
not confer it. `core.is_admin()` does not confer it. The ONE carve-out is the protected owner
(`core.is_owner`), who is the platform's anti-lockout root of trust and must be able to grant the
first role — otherwise a fresh deploy has an ACR feature nobody can ever administer.

tests/test_acr_authorization.py runs with ACP_OPEN_ACCESS=1 explicitly set, because that is the
configuration this gate exists to survive.

ROLES (PRD §18)
---------------
    viewer     — read a report
    evaluator  — record evidence and manual test results
    editor     — edit metadata, remarks, and select final statuses
    approver   — approve criteria and publish
    admin      — grant and revoke ACR roles

Roles are additive: an approver may also evaluate. The ladder below is a convenience for "does X
imply Y", not a claim that a role is a strict superset in every dimension.
"""
from __future__ import annotations

ROLE_VIEWER = "viewer"
ROLE_EVALUATOR = "evaluator"
ROLE_EDITOR = "editor"
ROLE_APPROVER = "approver"
ROLE_ADMIN = "admin"

ROLES: frozenset[str] = frozenset({ROLE_VIEWER, ROLE_EVALUATOR, ROLE_EDITOR, ROLE_APPROVER,
                                   ROLE_ADMIN})

# What each role implies. Kept explicit rather than computed from an ordering: "an approver can
# also edit" is a product decision, and writing it as a rank comparison hides it behind arithmetic.
_IMPLIES: dict[str, frozenset[str]] = {
    ROLE_VIEWER: frozenset({ROLE_VIEWER}),
    ROLE_EVALUATOR: frozenset({ROLE_VIEWER, ROLE_EVALUATOR}),
    ROLE_EDITOR: frozenset({ROLE_VIEWER, ROLE_EVALUATOR, ROLE_EDITOR}),
    ROLE_APPROVER: frozenset({ROLE_VIEWER, ROLE_EVALUATOR, ROLE_EDITOR, ROLE_APPROVER}),
    ROLE_ADMIN: frozenset(ROLES),
}


class AcrForbidden(PermissionError):
    """The caller lacks the ACR role this action needs."""


def effective_roles(granted: list[str], *, is_platform_owner: bool = False) -> frozenset[str]:
    """Everything `granted` implies, plus the owner carve-out.

    `is_platform_owner` is core.is_owner(email) — the single protected ACP_OWNER_EMAIL. It is NOT
    core.is_admin(), which under OPEN_ACCESS is everybody. See this module's docstring.
    """
    out: set[str] = set()
    for role in granted:
        out |= _IMPLIES.get(role, frozenset())
    if is_platform_owner:
        out |= set(ROLES)
    return frozenset(out)


def has_role(required: str, granted: list[str], *, is_platform_owner: bool = False) -> bool:
    return required in effective_roles(granted, is_platform_owner=is_platform_owner)


def require(required: str, granted: list[str], *, email: str | None = None,
            is_platform_owner: bool = False) -> None:
    """Raise AcrForbidden unless the caller holds `required`."""
    if not has_role(required, granted, is_platform_owner=is_platform_owner):
        who = email or "this account"
        raise AcrForbidden(
            f"{who} lacks the '{required}' role on this Accessibility Conformance Report. ACR "
            f"authority is granted per report and is not implied by platform admin access.")


def may_publish(email: str, granted: list[str], *, report: dict,
                is_platform_owner: bool = False) -> tuple[bool, str]:
    """PRD §21.11 plus §18's separation-of-duties advisory.

    Returns (allowed, reason). The second element is populated even when allowed, to carry the
    separation-of-duties WARNING — PRD §18 words it as "should not be the only approver when a
    second qualified reviewer is available", which is guidance, not a prohibition. Encoding it as a
    hard block would stop a one-person team from ever publishing; encoding it as nothing would let
    the sole-decider case pass unremarked. It is surfaced, and recorded in the audit log.
    """
    if not has_role(ROLE_APPROVER, granted, is_platform_owner=is_platform_owner):
        return False, (f"{email} is not an approver on this report — only an approver may publish "
                       f"an ACR (PRD §21.11)")
    if report.get("status") == "published":
        return False, "this report is already published; changes create a new draft revision"
    return True, ""


def separation_warning(email: str, decision_makers: dict[str, int], *,
                       other_approvers: int) -> str | None:
    """PRD §18: flag when the person approving also made most of the conformance decisions.

    Advisory only, and silent when no second qualified reviewer exists — the PRD conditions the
    expectation on one being available.
    """
    total = sum(decision_makers.values()) or 0
    if not total or other_approvers < 1:
        return None
    mine = decision_makers.get(email, 0)
    if mine * 2 > total:
        return (f"{email} made {mine} of {total} conformance decisions on this report and is also "
                f"the approver. A second qualified reviewer is available; PRD §18 recommends they "
                f"approve instead.")
    return None
