# SharePoint / Microsoft 365 app registration for ACP

**Audience:** the customer's Microsoft Entra ID (Azure AD) / Microsoft 365 administrator.
**Purpose:** register an application so a signed-in user can let ACP (mova.io) **list and scan**
their SharePoint and OneDrive documents for accessibility. **Read-only, single-tenant.**

This supersedes any template that points a redirect URI at `api.connector.ca.lyzr.app` — that is a
different product's connector and **must not be used**. ACP signs in directly with Microsoft from
the browser (MSAL.js), so the redirect URI is ACP's own address.

---

## What you are granting (and what you are not)

ACP asks for three **delegated, read-only** Microsoft Graph permissions:

| Permission | What it allows | Admin consent? |
|---|---|---|
| `User.Read` | Sign the user in and read their basic profile | No |
| `Files.Read.All` | **Read** every file the signed-in user can already open — their OneDrive, files shared with them, and team-site libraries | **Yes** |
| `Sites.Read.All` | **List** the SharePoint sites the user can already see, so they can pick a scan target | **Yes** |

- **Delegated** means ACP acts *as the signed-in user* and can never see anything that user
  couldn't already open in SharePoint. It grants no standing/background access.
- **Read-only:** there is no `*.ReadWrite` permission. ACP does not modify, move, or delete anything
  in SharePoint. Remediated files are delivered to the user for download, not written back.
- The two `.All` reads are **organization-scoped reads** and therefore require your one-time admin
  consent (this is exactly what the "Admin Consent Required" note is about). `.All` here widens the
  read from *the user's own OneDrive* to *everywhere the user is already authorized* — team sites,
  shared files — and nothing beyond that.

---

## Steps

1. **Open the Entra admin center** — <https://entra.microsoft.com> → **Applications → App
   registrations** (or portal.azure.com → *Microsoft Entra ID* → *App registrations*).
2. **New registration.**
   - **Name:** e.g. `ACP Accessibility (mova.io)`.
   - **Supported account types:** **Accounts in this organizational directory only (single tenant).**
3. **Redirect URI** — platform **Single-page application (SPA)**, and add ACP's address:
   - `https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io`
   - *(add the mova.io custom domain here too, once it is in use)*
   - Platform **must be SPA**, not "Web" — MSAL.js uses the browser Authorization-Code + PKCE flow,
     and a "Web" registration will reject sign-in.
   - **Do not** enter `https://api.connector.ca.lyzr.app/...`.
4. Click **Register.**
5. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**, add:
   - `User.Read`
   - `Files.Read.All`
   - `Sites.Read.All`

   Remove any other permission that was added by default beyond these three. There should be **no
   `*.ReadWrite` and no Application permissions.**
6. **Grant admin consent** for the tenant (the button on the API permissions page). The two `.All`
   reads stay "Not granted" until you do this, and users will hit an *"admin approval required"*
   wall on sign-in without it.
7. **No client secret is needed.** This is a public SPA client (PKCE); do not create a secret.

---

## Send back to the mova.io team

From the app registration's **Overview** page:

- **Application (client) ID**
- **Directory (tenant) ID**

(The Object ID is not needed.) These become ACP's `VITE_AZURE_CLIENT_ID` and `VITE_AZURE_TENANT_ID`
build settings; using the real tenant ID (not the generic `common`) is what makes the sign-in
single-tenant.

---

## Troubleshooting

### 403 on a SharePoint **site** scan (OneDrive works, sites don't)

> `Microsoft Graph refused this request (403). SharePoint SITES need the Sites.Read.All delegated
> permission on the Azure app registration, granted with tenant admin consent; Files.Read.All alone
> only reaches the signed-in user's OneDrive.`

**Cause.** The signed-in token isn't carrying `Sites.Read.All`. ACP *requests* it at sign-in, but
`Sites.Read.All` is an **admin-consent-required** scope — requesting is not the same as granting.
Either the permission was never added to the app registration, or admin consent was never given.
`Files.Read.All` alone only reaches the signed-in user's OneDrive, so a **site's** drives 403 while
that user's OneDrive scans fine.

**Fix (a tenant admin, ~2 min):**

1. **Entra admin center → App registrations →** the ACP app → **API permissions**.
2. Confirm **Microsoft Graph → Delegated → `Sites.Read.All`** is listed. If it's missing, add it (step
   5 above).
3. **Grant admin consent** for the tenant (the button on the API permissions page). Both `.All` scopes
   must show the green **"Granted"** check — *"Not granted"* means the token still won't include it.
4. Have the user **sign out of ACP and sign back in.** A token cached *before* consent will not gain
   the scope on its own; a fresh sign-in issues one that carries `Sites.Read.All`. If MSAL keeps
   returning the cached token, a one-time `prompt=consent` on sign-in clears it.

**Verify.** After re-consent + a fresh sign-in, the site's drives list. If it still 403s, the token is
stale (step 4) — not the permission.

## Security summary (for your records)

- **Read-only** — `Read.All`, never `ReadWrite`. ACP cannot change anything in SharePoint.
- **Delegated, per-user** — ACP only ever sees what the *signed-in* user can already access; each
  user signs in individually, and access disappears when they do.
- **No client secret / no background daemon** — a browser SPA with short-lived tokens (PKCE),
  refreshed only while the user is active.
- **Single tenant** — the app is usable only within your directory.
