# Production hardening

ACP is designed to be deployed **one instance per organization** (single-tenant).
Before a production deployment, work through this checklist. The single most
important switch is `ACP_DEPLOY_ENV=production`.

## 1. Set production mode

```
ACP_DEPLOY_ENV=production
```

This **hard-disables the test/demo auth bypasses** (`X-E2E-Key` and `X-Demo-Key`)
regardless of whether their keys are present (`core.IS_PROD`). Defence in depth —
a leftover `ACP_E2E_KEY`/`ACP_DEMO_DRIVE_KEY` env var can't reopen a backdoor.

`deploy/public/deploy.sh` already stamps this on the container; set it yourself only
for deployments that do not go through that script.

> **This page used to say `ACP_ENV=production`, and that was wrong.** The deploy
> scripts read `ACP_ENV` as the *Container Apps environment name*, not as the
> deployment environment. Following the old instruction never reached the container:
> `IS_PROD` stayed false, the `X-E2E-Key` bypass stayed live on the public demo, and
> `standup.sh` would have created an empty ACA environment literally named
> `production`. The scripts now use `ACP_ACA_ENV` for the environment name and
> **refuse to run** if `ACP_ENV` is set. `core.IS_PROD` still reads `ACP_ENV` as a
> legacy alias, so an existing container that sets it keeps production mode.

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

### A domain grants sign-in, not privileges

`ACP_ALLOWED_DOMAINS` decides who may **authenticate**. What they may then **do** is a
workspace role, and it is assigned — not inherited from the domain.

The first time somebody signs in who is not already on the roster, ACP creates a person
record for them and gives them one configurable role:

```
ACP_DEFAULT_SIGNIN_ROLE=viewer               # default; any role id, or empty to hold them
```

They appear on **Settings → Users** immediately, so an administrator can change that role
the same way they would for anyone else. Set the variable **empty** (or `none`) and new
arrivals are instead held at an **Access pending** screen until somebody assigns them a
role by hand.

Three properties worth knowing before you change it:

- **Nothing is enumerated.** A record is created only for people who actually sign in or
  are explicitly invited. ACP never reads your directory, so the roster grows to the size
  of the team using the product, not the size of the company.
- **The allow-list is not touched.** A record is a record; `ACP_ALLOWED_EMAILS` and the
  runtime allow-list are *grants*. Removing a domain therefore still revokes everyone who
  came in through it — their records remain, but the records admit nobody by themselves.
- **Existing users are backfilled lazily**, on their next sign-in, one at a time. There is
  no migration to run.

**Before this existed, a domain-admitted user was not blocked — they were silently given
the default Platform User role**, which carries every workflow tab. If you are upgrading and
want the old behaviour, set `ACP_DEFAULT_SIGNIN_ROLE=platform-user` deliberately, rather
than getting it from an authentication setting.

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

## 4. Set the public base URL

```
ACP_PUBLIC_URL=https://acp.yourcompany.com
```

This controls two things in generated PDF reports:

- **QR codes.** Each report embeds a QR code that links to the live scan for re-scan
  and verify flows. Without `ACP_PUBLIC_URL` the PDF encodes an `acp://` URI that no
  browser handles — the QR code renders but cannot be opened.
- **Reproducibility / digest verification.** The "Reproduce and verify" section of the
  PDF tells the reader how to re-run the scan via `POST /scans` and verify the rubric
  hash at `GET /rubric`. Those URLs are built from `ACP_PUBLIC_URL`; without it the
  links are relative and unusable from outside the host.

> **Rubric sensitivity.** The digest embedded in the PDF is tied to the rubric's
> `conformance_target`. If you replace or update the active ruleset (changing its
> `conformance_target`), existing PDF digests will **not** match what `/rubric` returns —
> the verify step will flag a mismatch even for correct re-runs. Changing the ruleset
> invalidates all prior report digests; note this in any change-management process.

## 5. Other production settings

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

## 6. Known limits (read before scaling up)

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
- **Database connection budget.** Each replica sizes its own Postgres pool from
  `db_max_conn()` (`api/store.py`) and nothing sums those pools against the server's
  `max_connections`. Raising `maxReplicas` or `ACP_WORKERS` therefore raises the fleet's
  connection ceiling silently. Work the capacity gate in
  [`docs/prd-reliability-hardening.md`](prd-reliability-hardening.md) (H-02) before you
  scale either one — on 30 August 2026 the configured maxima already permitted more pool
  connections than the production server allows.

## 7. Blue/green deployment

Azure Container Apps supports traffic-splitting via ingress weights, making blue/green a natural
fit for ACP.

**What fits well:**

- **Traffic splitting** — route 0% to the green revision until healthy, then flip to 100% with
  `az containerapp ingress traffic set`. The switch is near-instant and requires no DNS change.
- **Shared Postgres** — state is already separated from the app tier, so a rollback is just a
  traffic shift; no data is lost or replayed.
- **Worker queue in Postgres** — in-flight scans are not lost during the switch. Workers on
  either revision drain the same queue; outstanding items complete on whichever side picked them
  up.

**Watch out for:**

- **Schema migrations** — if a deploy includes a migration, both revisions must handle the new
  schema simultaneously. This constrains you to additive-only changes (new columns with defaults,
  new tables, new indexes) until the blue revision is fully drained. Never rename or drop a column
  while blue is still receiving traffic.
- **Redis session tokens** — both revisions must share the same Redis instance so sessions
  started on blue remain valid on green. If `REDIS_URL` is not configured, tokens are in-process
  and blue sessions will break the instant blue is drained. Set `REDIS_URL` before enabling
  blue/green.
- **WebSocket/SSE scan-progress** — the sticky-session ingress rule pins a user to the revision
  that started their scan. Drain blue gracefully (set its weight to 0 and wait for in-progress
  SSE streams to close) rather than killing it immediately; otherwise users watching a scan lose
  their live-update stream mid-scan.

**Recommended setup:**

```
# Deploy new revision as green, send it 0% traffic
az containerapp revision copy --name acp --resource-group <rg> --revision-suffix green

# Smoke-test green (healthz, a test scan) while blue handles 100%
az containerapp ingress traffic set --name acp --resource-group <rg> \
  --revision-weight acp--green=0 acp--blue=100

# Cut over
az containerapp ingress traffic set --name acp --resource-group <rg> \
  --revision-weight acp--green=100 acp--blue=0

# Keep blue warm for instant rollback (1 replica, no traffic)
az containerapp revision activate --name acp --resource-group <rg> --revision acp--blue
```

Set `minReplicas: 1` on the blue revision while it is on standby — this keeps it warm for a
sub-second rollback without consuming the full auto-scaled capacity. Deactivate it (or set
`minReplicas: 0`) once green has been stable for your confidence window.

**Backlog:** add a `deploy/blue-green.sh` script that codifies the above steps, runs the
healthcheck against green before cutting over, and falls back automatically on a non-200 response.
