# Production hardening

ACP is designed to be deployed **one instance per organization** (single-tenant).
Before a production deployment, work through this checklist. The single most
important switch is `ACP_ENV=production`.

## 1. Set production mode

```
ACP_ENV=production
```

This **hard-disables the test/demo auth bypasses** (`X-E2E-Key` and `X-Demo-Key`)
regardless of whether their keys are present (`core.IS_PROD`). Defence in depth —
a leftover `ACP_E2E_KEY`/`ACP_DEMO_DRIVE_KEY` env var can't reopen a backdoor.

Also unset them entirely:

```
# remove these in production
ACP_E2E_KEY        (smoke-test auth bypass)
ACP_DEMO_DRIVE_KEY (ADC/demo Drive scan without sign-in)
```

## 2. Lock the allow-list (deny by default)

The allow-list is **empty by default** — a fresh deploy admits **no one** in
Google-sign-in mode until you open it explicitly:

```
ACP_ALLOWED_DOMAINS=yourcompany.com          # whole Workspace domain(s), comma-sep
ACP_ALLOWED_EMAILS=alice@partner.com         # optional extra individuals
```

`email_allowed()` admits an email only if it's in `ACP_ALLOWED_EMAILS` **or** its
domain is in `ACP_ALLOWED_DOMAINS`. Leave both unset to lock everyone out.

## 3. Google "Sign in with Google" — use an INTERNAL OAuth app

For an internal/per-org deployment you can **skip Google's app verification + CASA**
(which the `drive.readonly` restricted scope otherwise requires) by making the
OAuth client **Internal** to your Workspace:

1. Google Cloud Console → **APIs & Services → OAuth consent screen**.
2. **User type: Internal** (only your Workspace's users can sign in — no
   verification, no 100-user test cap, no "unverified app" warning).
3. Add the scopes: `openid`, `email`, `profile`,
   `https://www.googleapis.com/auth/drive.readonly` (read/scan) and, if you use
   server-side remediation write-back, `https://www.googleapis.com/auth/drive.file`.
4. **Credentials → Create OAuth client → Web application**. Authorized JS origin
   and redirect = your app URL.
5. Set the client id on the app:

```
ACP_GOOGLE_CLIENT_ID=<your-web-client-id>.apps.googleusercontent.com
```

   With `ACP_GOOGLE_CLIENT_ID` set, the passcode gate is disabled and the app
   requires a valid Google token for an allow-listed user.

> **External users** (anyone with a personal Gmail, beyond your Workspace) require
> the **External** user type **+ Google verification + a CASA security assessment**
> for the restricted Drive scope. That's a multi-week, paid, annual process. Until
> it's done you're capped at 100 OAuth "test users". See the multi-tenancy notes
> below before going public.

## 4. Other production settings

```
ACP_DATABASE_URL=postgres://…              # never run on SQLite in prod
ACP_ALERT_KEY=<long-random>                # Grafana→/alerts/webhook shared secret
LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY  # via secrets, not baked in
ACP_WORKERS=<n>                            # or live-scale from Monitor
```

- Put all secrets in the platform's secret store (e.g. Container Apps secrets),
  not in env literals or committed files.
- Grafana / Langfuse expose **all** scan data — keep them admin-only; don't link
  them from a multi-user front door.

## 5. Known limits (read before scaling up)

- **Not multi-tenant.** All scans share one set of tables with no owner column —
  every signed-in user sees every other user's results. Fine for a single trusted
  team; **not** safe for unrelated users each scanning a private Drive. Needs an
  `owner_email` column + per-user filtering on every read first.
- **Horizontal scaling** is now supported: set `REDIS_URL` (per-scan tokens move to
  Redis with a 1h TTL, shared across replicas) and raise `maxReplicas`. Also enable
  **session affinity** (`az containerapp ingress sticky-sessions set --affinity
  sticky`) so the in-process scan-progress poll stays on one replica. The worker
  queue is already durable in Postgres, and each replica runs its own worker pool
  draining it. For production, run Redis with a password + `--save "" --appendonly
  no` (transient, no token persistence to disk).
- **Scan size.** A single scan is capped (`_search_drive` 500, `_search_folder`
  1000 files) and stages every file to the container's ephemeral disk. Thousands
  of files per scan needs higher caps, streaming, and a larger scan container.
