# SharePoint / Microsoft 365 app registration for ACP

**Audience:** the customer's Microsoft Entra ID (Azure AD) / Microsoft 365 administrator.
**Purpose:** register an application so a signed-in user can let ACP (mova.io) **list and scan**
their SharePoint and OneDrive documents for accessibility and publish approved corrected copies
into separate structured release folders. **Delegated, single-tenant; originals are unchanged.**

This supersedes any template that points a redirect URI at `api.connector.ca.lyzr.app` — that is a
different product's connector and **must not be used**. ACP signs in directly with Microsoft from
the browser (MSAL.js), so the redirect URI is ACP's own address.

---

## What you are granting (and what you are not)

ACP asks for three **delegated** Microsoft Graph permissions:

| Permission | What it allows | Admin consent? |
|---|---|---|
| `User.Read` | Sign the user in and read their basic profile | No |
| `Files.ReadWrite.All` | Read files the user can open and create corrected release copies | **Yes** |
| `Sites.ReadWrite.All` | List accessible SharePoint sites and create release folders in their libraries | **Yes** |

- **Delegated** means ACP acts *as the signed-in user* and can never see anything that user
  couldn't already open in SharePoint. It grants no standing/background access.
- **Non-destructive Release:** ACP writes only to a separate `Remediated/<timestamp>` tree. It does
  not overwrite, move, or delete the source document.
- The two `.All` delegated permissions require your one-time admin consent. They let ACP operate
  anywhere the signed-in user is already authorized — team sites and shared files — but do not
  create a standing background application identity.

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
   - `Files.ReadWrite.All`
   - `Sites.ReadWrite.All`

   Remove other permissions added by default. There should be no **Application permissions**.
6. **Grant admin consent** for the tenant (the button on the API permissions page). The two `.All`
   permissions stay "Not granted" until you do this, and users will hit an *"admin approval required"*
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

> `Microsoft Graph refused this request (403). SharePoint sites need the Sites.ReadWrite.All delegated
> permission on the Azure app registration, granted with tenant admin consent; a file scope alone
> only reaches the signed-in user's OneDrive.`

**Cause.** The signed-in token isn't carrying `Sites.ReadWrite.All`. ACP *requests* it at sign-in,
but it is an **admin-consent-required** scope — requesting is not the same as granting. Either the
permission was never added to the app registration, or admin consent was never given. A file scope
alone can reach OneDrive while
that user's OneDrive scans fine.

**Fix (a tenant admin, ~2 min):**

1. **Entra admin center → App registrations →** the ACP app → **API permissions**.
2. Confirm **Microsoft Graph → Delegated → `Sites.ReadWrite.All`** is listed. If it's missing, add it (step
   5 above).
3. **Grant admin consent** for the tenant (the button on the API permissions page). Both `.All` scopes
   must show the green **"Granted"** check — *"Not granted"* means the token still won't include it.
4. Have the user **sign out of ACP and sign back in.** A token cached *before* consent will not gain
   the scope on its own; a fresh sign-in issues one that carries `Sites.ReadWrite.All`. If MSAL keeps
   returning the cached token, a one-time `prompt=consent` on sign-in clears it.

**Verify.** After re-consent + a fresh sign-in, the site's drives list. If it still 403s, the token is
stale (step 4) — not the permission.

## Security summary (for your records)

- **Delegated write** — only while a signed-in user is active; Release creates corrected copies in
  a separate tree and leaves originals unchanged.
- **Delegated, per-user** — ACP only ever sees what the *signed-in* user can already access; each
  user signs in individually, and access disappears when they do.
- **No client secret / no background daemon** — a browser SPA with short-lived tokens (PKCE),
  refreshed only while the user is active.
- **Single tenant** — the app is usable only within your directory.
