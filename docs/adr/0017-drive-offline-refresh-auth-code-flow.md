# ADR 0017 — Server-side Drive refresh via the OAuth authorization-code flow

Status: Proposed
Date: 2026-07-09

Promotes **ADR 0014 Tier 2** ("server-side offline refresh") from a paragraph to a decision of
its own, because it changes what credentials ACP holds and for how long. Builds on ADR 0014
(Tier 1 keep-alive, shipped) and ADR 0013 (durable job queue).

## Context

Drive access is authenticated with a per-user Google Identity Services **access token**, obtained
in the browser by the GIS *implicit token flow* (`initTokenClient`, `frontend/src/SignIn.jsx`) and
passed to the backend as `x-drive-token`. That token lives about an hour and carries **no refresh
token**. The backend therefore cannot renew it: `google.oauth2.credentials.Credentials` built from
a bare access token has no `refresh_token`, `token_uri`, `client_id`, or `client_secret`.

Two mitigations exist today.

**ADR 0014 Tier 1 (shipped).** While a scan is running and the initiating tab is open, the
frontend silently re-mints the token every 20 minutes (`driveAuth.refreshDriveToken()`,
`prompt: ''`) and POSTs it to `/scans/{sid}/drive-token`, which updates the per-scan token store
(`core.register_scan_tokens`). Workers re-read the token per job, so long scans stay authenticated.
It cannot help a job that runs with the tab closed, and it depends on a live Google session.

**Expired-token handling (shipped, this session).** Every Drive client used to set
`creds.expiry = now + 1h` under a comment claiming it *prevented* a refresh. It caused one:
google-auth attempts a refresh exactly when `credentials.expired` is true, and `expired` is false
only while `expiry` is `None`. Once that fabricated hour lapsed, google-auth called `refresh()` and
raised *"The credentials do not contain the necessary fields need to refresh the access token"* —
which the queue then retried five times and dead-lettered in the customer's face. The expiry is
gone from all four call sites; `worker.drive_session_expired()` now classifies `RefreshError` and
Drive `401` as terminal and dead-letters once with an actionable message. **This makes the failure
honest. It does not make the scan survive.**

What remains unsolved: a **user-scoped** job that outlives its token with no browser to re-mint it.
Concretely — a remediation batch queued behind a backlog, a 100K-file estate scan, or any run where
the reviewer closes the tab. Today these fail once the hour is up, and the user must sign in and
re-run (cheap, thanks to ADR 0011 incremental fingerprinting, but not unattended).

Note what is **not** on that list. The scheduled sweep already runs unattended today, because
`core._do_scheduled_scan` calls `run_scan(source, drive_token=None)` — i.e. it authenticates with
**ADC (the service account)**, not with any user's token, and stamps the resulting scan with the
email of whoever set the schedule. Scheduled scanning therefore needs nothing from this ADR. That
is worth stating plainly, because it removes the most obvious argument for holding refresh tokens
and is direct evidence that a service-account path can already do headless Drive work here. It
sharpens the real question: do we need unattended access **as a specific user**, or merely
unattended access to the estate?

The only mechanism Google offers for unattended access to a *user's* Drive is a **refresh token**,
issued by the **authorization-code flow with offline access**. Obtaining one requires a client
secret and a server-side code exchange. Holding one is the actual decision here, and it is not a
small one: **a refresh token converts a one-hour capability into an indefinite one.** Under the
`drive.readonly` scope the app currently requests, a leaked refresh token is durable read access to
the user's entire Drive, not a one-hour window. That is why this is an ADR and not a patch.

## Decision

Adopt the authorization-code flow with offline access as an **opt-in, additive** auth path, gated
on the presence of `GOOGLE_CLIENT_SECRET`. When the secret is absent, ACP behaves exactly as it
does today (implicit token + Tier 1 keep-alive). Nothing about the current path is removed.

### D1 — Storage: a new, encrypted, durable credential

Refresh tokens are long-lived credentials and break an invariant ACP has held so far: *tokens are
never written to Postgres* (`core.py`: "tokens are NEVER written to Postgres; Redis is transient";
`store._scrub_payload_secrets` strips tokens from terminal job rows). Tier 2 requires durable
storage, so it must be storage that is safe to hold.

```
CREATE TABLE drive_credentials (
  user_email     TEXT PRIMARY KEY,       -- the Google account that consented
  refresh_token  BYTEA NOT NULL,         -- AES-GCM ciphertext, never plaintext
  nonce          BYTEA NOT NULL,
  scopes         TEXT NOT NULL,          -- exactly what the user consented to
  granted_at     TEXT NOT NULL,
  last_used_at   TEXT,
  key_version    INT  NOT NULL DEFAULT 1 -- so the key can be rotated
);
```

- Encrypted with AES-GCM; the key comes from an ACA secret (`ACP_TOKEN_ENC_KEY`), sourced from Key
  Vault, never from the image. A database backup on its own must not yield Drive access.
- `key_version` exists so rotation is a migration, not an outage.
- The plaintext refresh token never enters a log line, a job payload, a trace, or an exception
  message. `_scrub_payload_secrets` already covers job rows; add the same posture to `lf` spans.
- Deleting the row is deleting the grant (see D4).

### D2 — Consent and code exchange

- Frontend switches from `initTokenClient` to `initCodeClient` (auth-code, PKCE, popup ux_mode)
  **only when `/config` reports the server can exchange a code**. One flag, one code path.
- New endpoint `POST /auth/google/exchange` takes the authorization code, exchanges it server-side
  with `client_id` + `client_secret` + PKCE verifier, and persists the resulting refresh token via
  D1. It returns the access token to the SPA for immediate use; the refresh token never reaches the
  browser.
- The exchange endpoint is the only place the client secret is read.

**Verify before building:** Google returns a refresh token on the *first* consent for a given
client/user/scope set, and not on subsequent consents unless re-prompted (`prompt=consent`). The
exchange must therefore treat "no refresh_token in the response, and no row on file" as a hard
error with a re-consent path — not as success. I have not exercised this against a live client;
it is the first thing an implementation spike should confirm.

### D3 — Credentials that can actually refresh

Where a worker today builds a bare-token credential, it instead loads the user's refresh token and
builds a full one:

```python
Credentials(token=access_token, refresh_token=rt, token_uri=TOKEN_URI,
            client_id=CLIENT_ID, client_secret=CLIENT_SECRET, scopes=SCOPES)
```

google-auth then refreshes on expiry, automatically, inside the job. Note that this is the *only*
configuration in which setting `expiry` is meaningful — with a refresh token present, `expired`
becoming true is a signal to renew rather than a fatal error. The `.expiry` ban in
`tests/test_drive_token_expiry.py` must be narrowed at that point, not deleted: the invariant is
"never fabricate an expiry on a credential that cannot refresh," and it should be re-expressed as
such rather than dropped.

`worker.drive_session_expired()` stays. A refresh token can still be revoked, expire, or be
rejected; when it is, the job must still dead-letter once with the "reconnect Drive" message
rather than retry five times. The classifier becomes the fallback rather than the common path.

### D4 — Revocation is a first-class operation

Holding a durable credential obliges ACP to give it back.

- Sign-out calls `POST https://oauth2.googleapis.com/revoke` and deletes the row. Best-effort on
  the network call; unconditional on the delete.
- Settings → Integrations gains an explicit **Disconnect Drive** control that does the same.
- A row unused for `ACP_CREDENTIAL_MAX_IDLE` (default 90 days) is revoked and deleted by the
  existing scheduled tick. An unused durable credential is pure liability.
- `log_decision` records grant, use-by-a-job, and revocation — the audit trail a compliance
  customer will ask for, and one we would want ourselves after an incident.

### D5 — Scope reduction, as a precondition

`SignIn.jsx` currently requests `drive.readonly` **and** `drive.file`. `drive.readonly` over a
refresh token is durable read access to everything the user can see in Drive. Before D1 ships,
scanning should move to the narrowest scope that supports the product:

- `drive.file` alone covers files the app created or the user explicitly picked. If discovery over
  a whole Drive is required, `drive.readonly` is unavoidable and the consent screen must say so in
  those words.
- If the answer is "we need the whole estate," that is an argument for the service-account
  alternative below, not for a per-user durable `drive.readonly` grant.

This ordering is deliberate: it is easier to ask for a narrow scope before you hold refresh tokens
than to shrink one afterwards.

## Alternatives considered

**Do nothing beyond Tier 1 + honest failure (the status quo).** A scan whose tab closes fails once,
legibly, and re-running skips already-scanned files (ADR 0011). Zero new attack surface, zero
secrets, zero durable credentials. This is genuinely defensible, and it is the right answer if
unattended scanning is not a product requirement. **It is the baseline this ADR must beat.** The
case against it is `ACP_DRIVE_FOLDER` scheduled sweeps, which cannot work at all without D1–D3, and
overnight remediation of a large estate.

**Service account with domain-wide delegation.** A Workspace admin grants ACP's service account
delegated authority over the domain; scans impersonate users, or run as the org. **ACP already does
a weaker version of this**: the scheduled sweep authenticates with ADC and runs with no user present
(`core._do_scheduled_scan`), so the headless path is not hypothetical — it is in production. No per-user refresh
tokens are stored at all — the credential is a service-account key held in Key Vault, one secret
instead of N. For a compliance platform scanning an *organisation's* estate this is arguably the
correct enterprise shape, and it makes unattended sweeps trivial. Costs: it needs a Workspace admin
to enable, it is all-or-nothing over a domain, it is unavailable for consumer Gmail accounts, and it
concentrates blast radius into a single key. **Recommend evaluating this against D1–D5 with Deva
before implementing either.** If Deva is a Workspace tenant and the buyer is the org rather than the
individual reviewer, this may dominate.

**Push the token lifetime problem onto the queue.** Refuse to enqueue a job unless the token has
>N minutes of life; chunk long scans so no job exceeds the token. This narrows the window without
closing it, adds a scheduling constraint that the fan-out design (ADR 0013) would have to honour,
and still fails the tab-closed case. Rejected as a partial fix that complicates the queue.

**Store the access token and re-mint from a headless browser session.** Rejected without further
analysis: it is a credential-replay design, it will break, and it is worse than the thing it avoids.

## Consequences

- **Unattended Drive work becomes possible**: scheduled sweeps, overnight remediation, multi-hour
  estates, tab closed. This is the entire point, and nothing short of D1–D3 delivers it.
- **ACP becomes a holder of long-lived user credentials.** The security posture changes from "we
  hold a one-hour token in RAM" to "we hold indefinite Drive access at rest." Every consequence
  below follows from that sentence, and the human owning this decision should weigh it against the
  service-account alternative before accepting.
- **A client secret enters the deployment.** `GOOGLE_CLIENT_SECRET` and `ACP_TOKEN_ENC_KEY` become
  ACA secrets sourced from Key Vault. `deploy.sh` must pass them; neither may be baked into an image
  or printed by a deploy log.
- **Storage-schema change** (`drive_credentials`) and a new invariant to defend: tokens may live in
  Postgres *only* encrypted, and never in `jobs.payload`. The existing scrub test should be extended
  to assert the new column never appears in a job payload or a Langfuse span.
- **Backward compatible.** Without `GOOGLE_CLIENT_SECRET` the app runs exactly as today. The
  `/api/v1` shape gains one additive endpoint. No existing endpoint changes. Tier 1 keep-alive stays
  as belt-and-braces and as the only path for users who decline offline consent.
- **Consent friction.** Offline access shows a materially scarier Google consent screen. Some users
  will decline; the app must degrade to today's behaviour rather than break. That is a product
  decision, not only an engineering one.
- **Google publishing status is a live constraint.** While the OAuth consent screen is in *Testing*,
  refresh tokens are invalidated after 7 days — an unattended sweep would silently stop working a
  week after consent. Production publishing (and, for `drive.readonly`, Google's app verification,
  which is a review with a security questionnaire and can take weeks) is a **prerequisite**, not a
  follow-up. Refresh tokens are also invalidated by password change, explicit revocation, and ~6
  months of disuse; D4's idle sweep and the terminal-classifier must both handle that.
- **`_TOKEN_TTL = 3600` and its comment** ("GIS tokens live ~1h and don't refresh") become wrong for
  the Tier 2 path and must be revisited alongside D3.

## Verification

- **Unit:** encrypt/decrypt round-trip with a rotated `key_version`; exchange endpoint rejects a
  response with no refresh token and no existing row; `Credentials` built by D3 carries all five
  fields and reports `expired`→refresh rather than raising; `drive_session_expired` still classifies
  a revoked-token `RefreshError` as terminal.
- **Integration:** a job whose access token is expired at claim time completes, having refreshed
  in-flight, with no browser involved. This is the acceptance test — everything else is scaffolding.
- **Security:** `drive_credentials.refresh_token` is unreadable from a database dump without the
  ACA secret; the plaintext appears in no log, no `jobs.payload`, no Langfuse span, no exception.
- **Revocation:** disconnect → Google reports the grant gone → a queued job dead-letters once with
  "reconnect Drive," not five times.
- **The 7-day check:** consent under *Testing*, wait 8 days, confirm the failure mode is the
  actionable dead-letter and not a silent stall. If we cannot wait, verify with a manually revoked
  token — but say which one we did.

## Open questions (answer before implementing)

1. **Does any requirement actually need unattended access *as a specific user*?** The scheduled
   sweep does not — it runs on ADC today. If every unattended requirement can be met by the service
   account, D1–D5 buy nothing and should not be built. Answer this before anything else.
2. **Is Deva a Google Workspace tenant, and is the buyer the org or the individual reviewer?** If
   the org, domain-wide delegation likely beats per-user refresh tokens and this ADR should be
   superseded rather than implemented.
3. Can discovery live within `drive.file`, or is `drive.readonly` a hard product requirement? The
   security posture of D1 depends entirely on the answer.
4. Are we prepared to complete Google's verification review for a sensitive scope before the demo
   date? If not, Tier 1 + honest failure is the only shippable option and this ADR waits.
