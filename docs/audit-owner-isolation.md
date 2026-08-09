# Audit — per-user data isolation (`owner`)

**Date:** 2026-08-08 · **Scope:** can one authenticated user read another's documents, scans or
remediated files? · **Result: no.** Five links checked, all sound. Two configuration foot-guns
found that are not live in production.

The question matters because the customer is a hospital and the documents are PHI. An IDOR here
is not a data-quality bug, it is patient-record disclosure.

## The chain, link by link

### 1. `owner` cannot be influenced by a request

`api/routes/scans.py:19`

```python
def _owner(request: Request) -> str:
    return getattr(request.state, "user_email", None) or "demo"
```

`request.state.user_email` is written in exactly one place — the access-gate middleware in
`api/app.py`, after `verify_gis_token` (or `verify_entra_token`) returns an email AND
`email_allowed()` passes. **No query parameter, path segment, header or body field reaches it.**
Every route uses this helper; none accepts an owner from the caller.

### 2. Production runs the mode that sets it

The middleware branches `if ACCESS_CODE: … elif GOOGLE_CLIENT_ID: …`. Only the second branch sets
`user_email`. Read from the running container:

| variable | value |
|---|---|
| `ACP_GOOGLE_CLIENT_ID` | set |
| `ACP_ACCESS_CODE` | **empty** |
| `ACP_ALLOWED_EMAILS` / `ACP_ALLOWED_DOMAINS` | set |

`ACCESS_CODE` empty means the first branch is not taken, so the token path runs and `user_email`
is populated per user.

### 3. The whole-gate bypass is off, twice over

`app.py:41` returns early for a matching `X-E2E-Key`, skipping auth AND the allowlist. It is
fail-closed in `core.py:43-59`:

```python
IS_PROD = ACP_DEPLOY_ENV|ACP_ENV in ("production","prod")
TEST_BYPASS_ENABLED = ACP_ENABLE_TEST_BYPASS truthy AND not IS_PROD
E2E_KEY = ACP_E2E_KEY if TEST_BYPASS_ENABLED else None
```

Measured on the running container: `ACP_ENABLE_TEST_BYPASS` **absent**, `ACP_DEPLOY_ENV`
**`production`**. Either alone disables it; both hold. `E2E_KEY` resolves to `None`, so the header
is inert.

### 4. The store enforces ownership, not just the routes

- `list_scans` — filters in SQL: `WHERE … AND owner_email=%s`
- `get_scan` — `if owner is not None and run["owner_email"] != owner: return None`
- `get_scan_diff` — rejects unless BOTH scans belong to the caller

### 5. The one unscoped query is gated by its callers

`get_scan_traces(scan_id, file)` takes no `owner`. Both call sites resolve ownership first and
404 before reaching it — `scan_traces` (`:488`) and `scan_digest` (`:565`) each call
`get_scan(sid, owner=_owner(request))` and raise if it returns `None`.

## Two foot-guns, neither live

**A. Basic-auth mode has no per-user isolation.** With `ACP_ACCESS_CODE` set, the middleware
verifies the shared password and never sets `user_email` — so `_owner()` returns `"demo"` for
everybody and all users share one estate. That is correct for a single-tenant demo and wrong for
a hospital. Production does not use it (`ACP_ACCESS_CODE` is empty), but nothing in the code
prevents someone enabling it later.

**B. The compose stack defaults to demo mode.** `deploy/compose/docker-compose.yml` sets
`ACP_GOOGLE_CLIENT_ID: ${ACP_GOOGLE_CLIENT_ID:-}` — empty unless supplied, with the comment "No
GIS/ADC locally → runs in demo mode". **A customer-VPC deployment from that compose file would
have no per-user isolation at all**, and nothing would say so. Given ADR 0001 contemplates
customer-VPC installs, this is the one worth acting on.

## Recommendations

1. **Make isolation-off loud.** At startup, when neither `ACP_GOOGLE_CLIENT_ID` nor an Entra
   issuer is configured, log that every user shares the `demo` estate. It is the right behaviour
   for a demo and a serious misconfiguration for a tenant; the app should say which it is.
   *Cheap, and it is the difference between a documented mode and a silent one.*
2. **Consider refusing Basic-auth mode when `IS_PROD`**, the same fail-closed shape the E2E
   bypass already uses. A production deployment that collapses every user to one owner is almost
   certainly a mistake.
3. **Minor hardening:** `get_scan` fetches the row and then compares `owner_email`, rather than
   filtering in SQL. Authorisation is correct — it returns `None` — but another owner's row is
   briefly read into memory. Moving the predicate into the query costs nothing.

## What this audit does NOT cover

- **Langfuse trace contents** — whether PHI leaves the boundary via tracing. Separate item (P0.2).
- **Blob path traversal** — `{owner}/{scan_id}/{filename}`; `filename` comes from a path parameter
  and this audit did not check normalisation.
- **The worker tier** — background jobs resolve owner from the job payload, not a request, and
  were not traced here.
