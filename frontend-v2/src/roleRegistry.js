// Shared role registry — built-in roles + admin-created custom roles.
// Both RolePrivilege and UserManagement import from here so dropdowns stay in sync.

const LS_ROLES = 'mova_custom_roles'

export const BUILTIN_ROLES = ['Super Admin', 'Admin', 'Test Manager', 'HC Quality Engineer', 'IT Support Target', 'End User']

export const loadCustomRoles = () => { try { return JSON.parse(localStorage.getItem(LS_ROLES) || '[]') } catch { return [] } }
export const saveCustomRoles = (r) => { try { localStorage.setItem(LS_ROLES, JSON.stringify(r)) } catch {} }
export const loadAllRoles    = () => [...BUILTIN_ROLES, ...loadCustomRoles()]
