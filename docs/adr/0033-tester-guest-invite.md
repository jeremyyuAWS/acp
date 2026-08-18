# ADR 0033 — In-app tester access via an Entra B2B guest invite (opt-in, least-privilege)

Status: Proposed
Date: 2026-08-18

Follow-up to the access model in `api/core.py` (`email_allowed`) and the Settings → Users allowlist.
Adds an *optional* one-step "Invite tester" action, without giving ACP the directory-write it would
take to create tenant users.

## Context

Admitting a new tester today is **two grants**:

1. **ACP authorization** — add their email to the allowlist. *Already built:* Settings → Users
   (`GET`/`PUT /admin/allowlist`), which admits the owner, the list, or any address at an
   `ACP_ALLOWED_DOMAINS` domain.
2. **Provider access** — the identity must be able to sign in: a Google *test user* (while the OAuth
   consent screen is in Testing), or an account in the single-tenant `fgxlxj` Entra tenant.

Grant 2 for Microsoft is the friction: an operator leaves ACP, opens the Entra admin center, creates
or invites the account, comes back, and adds the email to the allowlist. The ask is to collapse that
into one in-app action. The tension: doing it in ACP means ACP holds a **Microsoft Graph credential**,
and the naive version — *create a tenant user* — needs `User.ReadWrite.All` + directory privileges,
i.e. ACP could mint and modify identities in the tenant. For an accessibility-remediation app in a
hospital, that blast radius will not survive a security review.

## Decision

Offer an **opt-in "Invite tester" action** in Settings → Users that does two things in one step:

1. Sends an **Entra B2B guest invitation** via Graph `POST /invitations` (scope **`User.Invite.All`**),
   returning the redemption link.
2. **Auto-adds** the invited email to the ACP allowlist (the existing `set_allowlist` path), so the
   guest is admitted on first sign-in with no second step.

It is **dark by default**: ACP holds *no* Graph permission unless the operator explicitly configures
a Graph app credential (client id + secret in Key Vault) for this feature. With it unconfigured, the
button is hidden and the behaviour is exactly today's — the allowlist, edited by hand.

### Why guest-invite, not user-create

`User.Invite.All` is dramatically narrower than `User.ReadWrite.All`: it can **only** invite an
external identity as a guest. It cannot read the directory, cannot create or modify tenant *members*,
cannot reset passwords, cannot enumerate users. That is the whole least-privilege argument — the
feature gets the one capability it needs (bring an external tester in) and nothing else. The invited
guest authenticates with *their own* Microsoft identity; ACP never creates or holds a credential for
them.

### Guardrails

- **Owner-only.** The action is gated to the ACP owner identity (the anti-lockout `ACP_OWNER_EMAIL`),
  the same identity that can already edit the allowlist.
- **Credential in Key Vault**, accessed via Managed Identity; never in app config or logs.
- **Documented for security review** — a short app-registration doc (mirroring the SharePoint
  read-only scopes doc) naming the single `User.Invite.All` permission and why, so the customer's
  infosec can grant admin consent with the scope in front of them.
- **Audit line** — every invite writes who invited whom, when (the store already has a settings/audit
  path).

### Flow

```
owner → Settings → Users → "Invite tester" (email)
        │
        ├─▶ Graph POST /invitations  (User.Invite.All)  ─▶ guest gets redemption link (Microsoft-hosted)
        └─▶ set_allowlist(list + email)                  ─▶ email pre-authorized in ACP
                                                              │
                              guest redeems + signs in ───────┘ ─▶ email_allowed() admits them
```

## Alternatives considered

- **Status quo — manual Entra invite + manual allowlist add.** No new permission, no code. Rejected
  only as the *default we improve on*; it stays the behaviour when the feature is unconfigured.
- **In-app user *creation* (`User.ReadWrite.All`).** Rejected — grants ACP identity-write over the
  tenant; disproportionate to "let a tester in," and a security-review non-starter.
- **Google parity.** No clean equivalent: Google test-users are managed in the Cloud Console and the
  Google Workspace side has no "invite to my OAuth app" primitive. Google testers stay a manual
  Console step until the consent screen is verified/Internal. This ADR is Microsoft-only by design.

## Consequences

- A **new Entra app registration** with a single delegated/application permission `User.Invite.All`,
  admin-consented by the customer. Until that exists and is configured, the feature is inert.
- Settings → Users gains an "Invite tester" affordance (owner-only) and the invite/audit plumbing.
- The allowlist remains the single source of truth for ACP authorization; the invite is a convenience
  that *writes* to it, not a parallel grant.

## Effort estimate (LOE)

~**2–3 engineer-days**: Graph `POST /invitations` client + Key Vault credential wiring, the owner-only
Settings action, auto-add-to-allowlist, audit line, and tests. Excludes the customer-side app
registration + admin consent (theirs, and the gating dependency).

## Open questions (for the implementation PR)

- Guest vs. member invitation and the redemption/consent settings to request.
- Whether to also auto-remove from the allowlist on guest revocation, or keep those decoupled.
- Rate/abuse limits on the invite action (owner-only already bounds it).

## Status / next step

Proposed. Self-contained ~2–3 day build once the customer stands up the `User.Invite.All` app
registration; ships dark until that credential is configured.
