// The SharePoint / Microsoft Graph delegated scopes ACP requests — the single source of truth for
// both sign-in entry points (SharePoint.jsx and Integrations.jsx), so the two can never request a
// different set of permissions than the one IT consented to.
//
// READ-ONLY, and enough to reach SharePoint rather than just OneDrive:
//   User.Read       — sign the user in and read their basic profile (no admin consent).
//   Files.Read.All  — read every file the signed-in user can already see: their OneDrive, files
//                     shared with them, and team-site document libraries. Plain Files.Read is the
//                     user's personal OneDrive alone, which cannot reach SharePoint libraries.
//   Sites.Read.All  — enumerate the SharePoint sites the user can see (Graph /sites?search=*),
//                     which the site picker (GET /sharepoint/sites) needs and Files.* cannot give.
//
// Files.Read.All and Sites.Read.All are the ".All" (organization-scoped) reads that require a
// tenant admin's consent — that is what docs/sharepoint-app-registration.md walks IT through. They
// grant NO access the user does not already have; they widen the read from OneDrive to everywhere
// the user is authorized, and nothing more.
//
// Deliberately no *.ReadWrite scope: this deployment is read-only, so ACP never writes a remediated
// file back to SharePoint. CAN_WRITE_BACK is derived from this list rather than set by hand, so the
// write-back UI can never appear without the permission to honour it — add a *.ReadWrite scope here
// and the button returns on its own; leave it out and the read-only build hides it.
export const SP_SCOPES = ['User.Read', 'Files.Read.All', 'Sites.Read.All']

export const CAN_WRITE_BACK = SP_SCOPES.some((s) => /\.ReadWrite/i.test(s))
