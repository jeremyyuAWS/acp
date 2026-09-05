import { useEffect, useRef, useState } from 'react'
import {
  getWorkspaceRoles, getRoleCapabilities, createWorkspaceRole,
  updateWorkspaceRole, deleteWorkspaceRole,
} from './api.js'

// The Roles screen (PRD §8) — a list of roles and a drawer for editing one.
//
// THE DRAWER RENDERS ITSELF FROM THE SERVER'S CATALOG, not from a copy of the tab list kept here.
// GET /admin/capabilities returns the governed tabs, the three levels, and the seven
// administrative permissions. Hardcoding them would give this file a second opinion about what a
// role can hold, and the failure mode of that is a checkbox that is visibly ticked and silently
// ignored — worse than the permission not existing, because somebody will rely on it.
//
// WHAT THE UI REFUSES, IT REFUSES AS A COURTESY. Every rule below (Owner is not editable, a role
// with users cannot be deleted, you cannot grant beyond your own ceiling) is enforced server-side
// in api/routes/workspace_roles_admin.py and tested there. Disabling the control is so an
// administrator does not design a role around a permission and get refused on save — it is not
// what makes the rule true.

const LEVEL_LABEL = { hidden: 'Hidden', view: 'View', operate: 'Operate' }

export default function WorkspaceRoles() {
  const [roles, setRoles] = useState([])
  const [catalog, setCatalog] = useState(null)
  const [enforced, setEnforced] = useState(false)
  const [rollout, setRollout] = useState(null)
  const [editing, setEditing] = useState(null)     // the role in the drawer, or null
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loaded, setLoaded] = useState(false)
  const createRef = useRef(null)

  const load = () => Promise.all([getWorkspaceRoles(), getRoleCapabilities()])
    .then(([r, c]) => { setRoles(r.roles || []); setEnforced(!!r.enforced)
                    setRollout(r.rollout || null); setCatalog(c) })
    .catch((e) => setError(e.message || 'Could not load roles.'))
    .finally(() => setLoaded(true))
  useEffect(() => { load() }, [])

  const afterWrite = (note) => { setMessage(note); setError(''); setEditing(null); load() }
  const fail = (e) => setError(e.message || 'That change could not be saved.')

  const remove = (role) => {
    if (!window.confirm(`Delete the ${role.name} role? This cannot be undone.`)) return
    deleteWorkspaceRole(role.id).then(() => afterWrite(`${role.name} was deleted.`)).catch(fail)
  }

  return <section aria-labelledby="roles-title" style={{ maxWidth: 860 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
      <div>
        <h3 id="roles-title" style={{ margin: 0 }}>Roles</h3>
        <div className="muted" style={{ fontSize: 13, marginTop: 3 }}>
          {roles.length} role{roles.length === 1 ? '' : 's'} · a role decides which tabs someone
          sees and what they can do there
        </div>
      </div>
      <button ref={createRef} onClick={() => setEditing({ isNew: true, name: '', description: '',
                                                          tabs: {}, grants: [], version: 0 })}>
        + Create role
      </button>
    </div>

    {/* THE MOST IMPORTANT LINE ON THIS SCREEN when the server is not refusing. Without it an
        administrator designs roles, assigns them, and reasonably believes access is now
        restricted — while every route still admits everyone. Saying so here is the difference
        between a staged rollout and a false sense of security.

        IT NAMES THE RUNG, not just "off", because the three unenforced rungs mean genuinely
        different things to the person reading this: at `navigation` their roles ARE hiding tabs
        and a direct URL still works, which is a materially different claim from "nothing changes
        for anyone". Collapsing them to one sentence would make this banner wrong two thirds of
        the time it appears.

        The wording comes from the SERVER (rollout.means), so it cannot drift from what the code
        does — the rung's description lives next to its definition in api/workspace_rollout.py. */}
    {loaded && !enforced && (
      <div role="note" className="roles-not-enforced">
        <b>Roles are not being enforced yet.</b>{' '}
        {rollout?.means || 'You can design and assign them now; nothing changes for anyone.'}
        {rollout?.next && <> Next stage: <code>{rollout.next}</code>.</>}
      </div>
    )}

    {/* An unreadable mode is the one configuration that looks identical to a workspace nobody has
        got to yet: the operator set the variable, believes it took effect, and it did not. */}
    {loaded && rollout?.invalid_mode && (
      <div role="alert" className="roles-not-enforced">
        <b>The rollout stage is misconfigured.</b> <code>ACP_WORKSPACE_RBAC_MODE</code> is set to
        {' '}<code>{rollout.invalid_mode}</code>, which is not a stage. ACP is running as
        {' '}<code>{rollout.mode}</code>.
      </div>
    )}

    <div role="status" aria-live="polite" style={{ minHeight: 22, marginTop: 10, fontSize: 13,
                                                   color: error ? 'var(--error-fg-strong)' : '#287D3C' }}>
      {error || message}
    </div>

    <div className="roles-table">
      {!loaded ? <p className="muted" style={{ padding: 18, margin: 0 }}>Loading roles…</p>
        : roles.length === 0 ? <p className="muted" style={{ padding: 18, margin: 0 }}>No roles yet.</p>
        : roles.map((role, i) => (
          <div key={role.id} className="roles-row" style={{ borderTop: i ? '1px solid var(--line)' : 0 }}>
            <div>
              <b style={{ fontSize: 13 }}>{role.name}</b>
              {role.is_protected && <span className="roles-chip" title="Owner cannot be edited, deleted, or assigned by anyone but the current Owner">Protected</span>}
              {role.is_system && !role.is_protected && <span className="roles-chip">Built-in</span>}
              <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{role.description}</div>
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {role.users} user{role.users === 1 ? '' : 's'}
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {summariseTabs(role.tabs)}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="ghost small" onClick={() => setEditing({ ...role })}>
                {role.is_protected ? 'View' : 'Edit'}
              </button>
              <button className="ghost small"
                      onClick={() => setEditing({ isNew: true, duplicate_of: role.id,
                                                  name: `${role.name} copy`, description: role.description,
                                                  tabs: role.tabs, grants: role.grants, version: 0 })}>
                Duplicate
              </button>
              {/* Disabled rather than hidden when the role is in use: a missing button reads as
                  "you cannot do this", a disabled one with a reason reads as "not yet, and here
                  is why" — which is the actionable version. */}
              <button className="ghost small" disabled={role.is_protected || role.users > 0}
                      title={role.is_protected ? 'The Owner role cannot be deleted'
                             : role.users > 0 ? `Reassign the ${role.users} user(s) holding this role first`
                             : undefined}
                      onClick={() => remove(role)}>Delete</button>
            </div>
          </div>
        ))}
    </div>

    {editing && catalog && (
      <RoleDrawer role={editing} catalog={catalog} onClose={() => setEditing(null)}
                  onSaved={afterWrite} onError={fail} />
    )}
  </section>
}

/** "8 tabs · 2 read-only" — enough to compare roles at a glance without opening each. */
function summariseTabs(tabs) {
  const values = Object.values(tabs || {})
  const visible = values.filter((v) => v !== 'hidden').length
  const viewOnly = values.filter((v) => v === 'view').length
  if (visible === 0) return 'No tabs'
  return `${visible} tab${visible === 1 ? '' : 's'}${viewOnly ? ` · ${viewOnly} read-only` : ''}`
}


function RoleDrawer({ role, catalog, onClose, onSaved, onError }) {
  const [name, setName] = useState(role.name || '')
  const [description, setDescription] = useState(role.description || '')
  const [tabs, setTabs] = useState(() => ({ ...(role.tabs || {}) }))
  const [grants, setGrants] = useState(() => [...(role.grants || [])])
  const [busy, setBusy] = useState(false)
  const dialogRef = useRef(null)
  const nameRef = useRef(null)
  const readOnly = !!role.is_protected

  useEffect(() => { nameRef.current?.focus() }, [])
  useEffect(() => {
    const keydown = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [onClose])

  // What the CALLER may grant. The server refuses anything beyond it (PRD §14) — this only stops
  // an administrator designing a role around a permission they were never going to be allowed to
  // hand out, and then meeting the refusal at save time.
  const mine = new Set(catalog.mine || [])
  const canGrant = (key) => mine.has(key)

  const save = () => {
    setBusy(true)
    const body = { name: name.trim(), description, tabs, grants }
    const call = role.isNew
      ? createWorkspaceRole(role.duplicate_of ? { ...body, duplicate_of: role.duplicate_of } : body)
      : updateWorkspaceRole(role.id, { ...body, version: role.version })
    call.then(() => onSaved(role.isNew ? `${body.name} was created.` : `${body.name} was saved.`))
      .catch(onError)
      .finally(() => setBusy(false))
  }

  return (
    <div role="presentation" className="roles-drawer-scrim"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="role-drawer-title"
           className="roles-drawer">
        <h3 id="role-drawer-title" style={{ marginTop: 0 }}>
          {role.isNew ? 'Create role' : readOnly ? role.name : `Edit ${role.name}`}
        </h3>

        {readOnly && (
          <p role="note" className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            The Owner role cannot be changed. It exists so that administrative lockout is
            impossible — an Owner that can be edited is not that role. Duplicate it if you need a
            role like it that you can adjust.
          </p>
        )}

        <label className="roles-field">Role name
          <input ref={nameRef} value={name} maxLength={60} disabled={readOnly}
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="roles-field">Description
          <input value={description} disabled={readOnly}
                 onChange={(e) => setDescription(e.target.value)} />
        </label>

        <fieldset className="roles-fieldset">
          <legend>Tab access</legend>
          <table className="roles-grid">
            <thead>
              <tr>
                <th scope="col">Tab</th>
                {catalog.levels.map((lvl) => <th key={lvl} scope="col">{LEVEL_LABEL[lvl] || lvl}</th>)}
              </tr>
            </thead>
            <tbody>
              {catalog.tabs.map((tab) => (
                <tr key={tab.key}>
                  <th scope="row">{tab.label}</th>
                  {catalog.levels.map((lvl) => (
                    <td key={lvl}>
                      <input type="radio" name={`tab-${tab.key}`} value={lvl} disabled={readOnly}
                             checked={(tabs[tab.key] || 'hidden') === lvl}
                             aria-label={`${tab.label}: ${LEVEL_LABEL[lvl] || lvl}`}
                             onChange={() => setTabs((t) => ({ ...t, [tab.key]: lvl }))} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </fieldset>

        <fieldset className="roles-fieldset">
          <legend>Additional permissions</legend>
          {catalog.grants.map((grant) => {
            const checked = grants.includes(grant.key)
            const blocked = !canGrant(grant.key) && !checked
            return (
              <label key={grant.key} className="roles-grant">
                <input type="checkbox" checked={checked} disabled={readOnly || blocked}
                       onChange={(e) => setGrants((g) => (e.target.checked
                         ? [...g, grant.key] : g.filter((x) => x !== grant.key)))} />
                <span>{grant.label}</span>
                {blocked && <span className="muted" style={{ fontSize: 11.5 }}>
                  — you do not hold this permission yourself
                </span>}
              </label>
            )
          })}
          {/* PRD §5 makes these independent of tab access, which has a consequence the drawer
              should name rather than silently allow: a role can publish without being able to see
              what it publishes. Warned, not prevented — the two controls are separate on purpose,
              and repairing it here would make a ticked checkbox do nothing. */}
          {grants.includes('release.publish') && (tabs.publish || 'hidden') === 'hidden' && (
            <p role="note" className="roles-warn">
              This role can publish corrected files but cannot see the Release tab. That is
              allowed, but the people holding it will have no way to review what they publish.
            </p>
          )}
        </fieldset>

        {!role.isNew && !readOnly && (
          <p className="muted" style={{ fontSize: 12 }}>
            {role.users} user{role.users === 1 ? '' : 's'} currently {role.users === 1 ? 'has' : 'have'} this role.
          </p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
          <button type="button" className="ghost" onClick={onClose}>
            {readOnly ? 'Close' : 'Cancel'}
          </button>
          {!readOnly && (
            <button type="button" onClick={save} disabled={busy || !name.trim()}>
              {busy ? 'Saving…' : role.isNew ? 'Create role' : 'Save role'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
