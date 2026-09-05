// The SharePoint / Microsoft Graph delegated scopes ACP requests — the single source of truth for
// both sign-in entry points (SharePoint.jsx and Integrations.jsx), so the two can never request a
// different set of permissions than the one IT consented to.
//
// Delegated read/write, so an explicit Release can create corrected copies while scans remain
// browsing plus non-destructive Release copies. ACP never overwrites the source during Release.
//   User.Read       — sign the user in and read their basic profile (no admin consent).
//   Files.ReadWrite.All — read accessible files and create corrected release copies. Plain
//                         Files.ReadWrite is limited to the user's own files.
//   Sites.ReadWrite.All — enumerate sites and create corrected copies in their libraries,
//                     which the site picker (GET /sharepoint/sites) needs and Files.* cannot give.
//
// Files.ReadWrite.All and Sites.ReadWrite.All are the organization-scoped delegated grants that require a
// tenant admin's consent — that is what docs/sharepoint-app-registration.md walks IT through. They
// act only with the signed-in user's access; they add no application/background identity.
//
export const SP_SCOPES = ['User.Read', 'Files.ReadWrite.All', 'Sites.ReadWrite.All']

// Permission is broader than product policy: Release may create a COPY, but source replacement
// stays disabled. Do not let adding the permission silently re-enable the legacy overwrite UI.
export const CAN_PUBLISH_COPY = SP_SCOPES.some((s) => /\.ReadWrite/i.test(s))
export const CAN_WRITE_BACK = false

// The Entra app (client) and directory (tenant) ids for the SharePoint/OneDrive sign-in.
// PREFER runtime /config (azure_client_id / azure_tenant_id) over the build-time VITE_AZURE_*
// values, so a deployment — or each customer's tenant — is set with an env var and no rebuild
// (the same reason GOOGLE_CLIENT_ID is served from /config). The build-time values remain the
// fallback for local dev via frontend/.env. Resolved once and cached; callers await it.
import { getConfig } from './api.js'

const VITE_CLIENT = import.meta.env.VITE_AZURE_CLIENT_ID || ''
const VITE_TENANT = import.meta.env.VITE_AZURE_TENANT_ID || 'common'

// Every SharePoint/OneDrive DATA-SOURCE tenant this deployment can connect to (multi-tenant
// SharePoint, ADR pending): [{key, label, client_id, tenant_id}, ...] from /config's
// microsoft_tenants, one entry per Entra app registration the backend knows about. A single-tenant
// deployment (today's default, and every deployment until a second is configured) gets exactly one
// entry keyed 'primary' — callers that never pass a tenantKey are unaffected by any of this.
//
// Deliberately NOT what gates sign-IN to ACP (SignIn.jsx's "Sign in with Microsoft" stays pinned to
// azure_client_id/azure_tenant_id alone) — this is which estates a signed-in user can point a scan
// at, which is a narrower, additive question than who may use the app at all.
let _tenantsCache
export async function getMicrosoftTenants() {
  if (_tenantsCache) return _tenantsCache
  let c = null
  try { c = await getConfig() } catch { /* no /config → fall back to the build-time single pair */ }
  const fromConfig = (c && Array.isArray(c.microsoft_tenants)) ? c.microsoft_tenants : []
  // A backend that hasn't rolled forward to microsoft_tenants yet (deploy-order skew, or simply
  // older) still sends the singular azure_client_id/azure_tenant_id pair — fall back to treating
  // that as a one-entry list rather than losing the connection to a rollout ordering accident.
  const legacyPair = (c && c.azure_client_id && c.azure_tenant_id)
    ? [{ key: 'primary', label: 'Primary', client_id: c.azure_client_id, tenant_id: c.azure_tenant_id }]
    : []
  _tenantsCache = fromConfig.length ? fromConfig : legacyPair.length ? legacyPair
    : (VITE_CLIENT ? [{ key: 'primary', label: 'Microsoft',
                       client_id: VITE_CLIENT, tenant_id: VITE_TENANT }] : [])
  return _tenantsCache
}

// The (clientId, tenant) pair for ONE connect attempt. `tenantKey` selects which registered
// tenant to use; omitted (every existing caller) resolves to the first configured one — identical
// to the old single-pair behaviour when only one tenant is configured, which is every deployment
// until a second is added.
export async function getSpAuth(tenantKey) {
  const tenants = await getMicrosoftTenants()
  const found = tenantKey ? tenants.find((t) => t.key === tenantKey) : tenants[0]
  return { clientId: found?.client_id || '', tenant: found?.tenant_id || 'common', key: found?.key || null }
}
