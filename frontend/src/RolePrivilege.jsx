import { useState, useMemo } from 'react'
import { BUILTIN_ROLES, loadCustomRoles, saveCustomRoles, loadAllRoles } from './roleRegistry.js'

const LS_KEY = 'mova_role_privileges'

const AI_SOLUTIONS = ['App Engineering', 'Quality Engineering', 'Enterprise Ops', 'SDLC', 'CX', 'Target ITOps', 'SDLC Subscription', 'QE for Healthcare']
const TEAMS = ['Development Team', 'QA Team', 'Devops Team', 'Management Team', 'HC QC Team', 'IT Support Target', 'Salesforce Team']
const ROLES = ['Super Admin', 'Admin', 'Test Manager', 'HC Quality Engineer', 'IT Support Target', 'End User']

const MODULES = [
  { label: 'Command Center', pages: ['Chatbot', 'Task', 'Insights', 'Trends', 'Knowledge Graph', 'Workflow'] },
  { label: 'Market Place',   pages: ['Agent Management', 'Agency Management', 'Workflow Management', 'Knowledge Store Management', 'Mcp Connector Management'] },
  { label: 'Subscription',   pages: ['Subscription'] },
  { label: 'Logs',           pages: ['Logs'] },
]

const PERMS = ['view', 'edit', 'delete', 'refresh', 'execute']
const PERM_LABELS = { view: 'View', edit: 'Insert / Edit', delete: 'Delete', refresh: 'Refresh', execute: 'Execute' }

const makeKey = (sol, team, role) => sol + '||' + team + '||' + role

const loadPrivileges = () => { try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') } catch { return {} } }
export const loadRolePrivileges = loadPrivileges

const DEFAULT_FOR = (role) => {
  const full  = Object.fromEntries(PERMS.map(p => [p, true]))
  const view  = Object.fromEntries(PERMS.map(p => [p, p === 'view']))
  const none  = Object.fromEntries(PERMS.map(p => [p, false]))
  const build = (pages, permsObj) => Object.fromEntries(pages.map(pg => [pg, { ...permsObj }]))
  if (role === 'Super Admin') {
    return Object.fromEntries(MODULES.map(m => [m.label, build(m.pages, full)]))
  }
  if (role === 'Admin') {
    return {
      'Command Center': build(MODULES[0].pages, full),
      'Market Place':   build(MODULES[1].pages, full),
      'Subscription':   build(MODULES[2].pages, view),
      'Logs':           build(MODULES[3].pages, none),
    }
  }
  if (role === 'Test Manager') {
    return {
      'Command Center': build(MODULES[0].pages, { view: true, edit: false, delete: false, refresh: false, execute: true }),
      'Market Place':   build(MODULES[1].pages, view),
      'Subscription':   build(MODULES[2].pages, { ...view, execute: true }),
      'Logs':           build(MODULES[3].pages, none),
    }
  }
  if (role === 'HC Quality Engineer') {
    return {
      'Command Center': build(MODULES[0].pages, view),
      'Market Place':   build(['Agent Management', 'Workflow Management'], view),
      'Subscription':   build(MODULES[2].pages, view),
      'Logs':           build(MODULES[3].pages, none),
    }
  }
  return Object.fromEntries(MODULES.map(m => [m.label, build(m.pages, view)]))
}

export default function RolePrivilege({ onChanged }) {
  const [privileges, setPrivileges] = useState(loadPrivileges)
  const [solution, setSolution] = useState(AI_SOLUTIONS[0])
  const [team, setTeam] = useState(TEAMS[0])
  const [customRoles, setCustomRoles] = useState(loadCustomRoles)
  const [newRoleName, setNewRoleName] = useState('')
  const [showNewRole, setShowNewRole] = useState(false)
  const allRoles = [...BUILTIN_ROLES, ...customRoles]
  const [role, setRole] = useState(BUILTIN_ROLES[2])
  const [saved, setSaved] = useState(false)

  const createRole = () => {
    const name = newRoleName.trim()
    if (!name || allRoles.includes(name)) return
    const next = [...customRoles, name]
    setCustomRoles(next); saveCustomRoles(next)
    setRole(name); setNewRoleName(''); setShowNewRole(false)
  }
  const deleteCustomRole = (name) => {
    const next = customRoles.filter(r => r !== name)
    setCustomRoles(next); saveCustomRoles(next)
    if (role === name) setRole(BUILTIN_ROLES[0])
  }

  const key = makeKey(solution, team, role)
  const current = useMemo(() => privileges[key] || DEFAULT_FOR(role), [privileges, key, role])

  const getVal = (mod, page, perm) => !!(current[mod] && current[mod][page] && current[mod][page][perm])

  const update = (nextCurrent) => setPrivileges(p => ({ ...p, [key]: nextCurrent }))

  const setVal = (mod, page, perm, val) => {
    update({
      ...current,
      [mod]: { ...current[mod], [page]: { ...(current[mod] || {})[page], [perm]: val } },
    })
  }

  const toggleModuleAll = (mod, checked) => {
    const pages = MODULES.find(m => m.label === mod)?.pages || []
    const modMap = {}
    pages.forEach(pg => { modMap[pg] = Object.fromEntries(PERMS.map(p => [p, checked])) })
    update({ ...current, [mod]: modMap })
  }

  const isModuleAllChecked = (mod) =>
    (MODULES.find(m => m.label === mod)?.pages || []).every(pg =>
      PERMS.every(p => getVal(mod, pg, p)))

  const applyAll = () => {
    const next = {}
    MODULES.forEach(m => {
      next[m.label] = Object.fromEntries(m.pages.map(pg => [pg, Object.fromEntries(PERMS.map(p => [p, true]))]))
    })
    update(next)
  }

  const applyViewOnly = () => {
    const next = {}
    MODULES.forEach(m => {
      next[m.label] = Object.fromEntries(m.pages.map(pg => [pg, Object.fromEntries(PERMS.map(p => [p, p === 'view']))]))
    })
    update(next)
  }

  const applyReset = () => {
    update(DEFAULT_FOR(role))
  }

  const save = () => {
    const next = { ...privileges, [key]: current }
    localStorage.setItem(LS_KEY, JSON.stringify(next))
    setPrivileges(next)
    onChanged?.(next)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  let firstInModule = {}
  const rows = []
  MODULES.forEach(mod => {
    mod.pages.forEach((page, pi) => {
      rows.push({ mod: mod.label, page, isFirst: pi === 0, pageCount: mod.pages.length })
    })
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span className="muted" style={{ whiteSpace: 'nowrap' }}>AI Solution</span>
          <select style={{ fontSize: 12 }} value={solution} onChange={e => setSolution(e.target.value)}>
            {AI_SOLUTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span className="muted">Team</span>
          <select style={{ fontSize: 12 }} value={team} onChange={e => setTeam(e.target.value)}>
            {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span className="muted">Role</span>
          <select style={{ fontSize: 12 }} value={role} onChange={e => setRole(e.target.value)}>
            <optgroup label="Built-in">
              {BUILTIN_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </optgroup>
            {customRoles.length > 0 && (
              <optgroup label="Custom">
                {customRoles.map(r => <option key={r} value={r}>{r}</option>)}
              </optgroup>
            )}
          </select>
          {customRoles.includes(role) && (
            <button className="ghost small" style={{ fontSize: 11, color: '#d9534f' }} title="Delete this custom role" onClick={() => deleteCustomRole(role)}>✕ delete role</button>
          )}
          <button className="ghost small" style={{ fontSize: 11 }} onClick={() => setShowNewRole(v => !v)}>＋ New role</button>
        </label>
        {showNewRole && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: '#f8f8f8', border: '1px solid var(--line)', borderRadius: 6, marginTop: 2 }}>
            <input
              type="text" value={newRoleName} onChange={e => setNewRoleName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && createRole()}
              placeholder="Role name (e.g. Accessibility Reviewer)"
              style={{ fontSize: 12, padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 4, width: 260 }}
              aria-label="New role name" autoFocus
            />
            <button className="ghost small" onClick={createRole} disabled={!newRoleName.trim() || allRoles.includes(newRoleName.trim())}>Create</button>
            <span className="muted" style={{ fontSize: 11 }}>Starts with no permissions (least privilege)</span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 14, fontSize: 13 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
          <input type="radio" name="rp-quick" onChange={applyViewOnly} style={{ cursor: 'pointer' }} />
          View Only
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
          <input type="radio" name="rp-quick" onChange={applyAll} style={{ cursor: 'pointer' }} />
          All
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
          <input type="radio" name="rp-quick" onChange={applyReset} style={{ cursor: 'pointer' }} />
          Reset to defaults
        </label>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="ruletable" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', minWidth: 120 }}>Module</th>
              <th style={{ textAlign: 'left', minWidth: 160 }}>Page</th>
              {PERMS.map(p => (
                <th key={p} style={{ textAlign: 'center', minWidth: 80, whiteSpace: 'nowrap', fontSize: 12 }}>{PERM_LABELS[p]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ mod, page, isFirst, pageCount }, ri) => (
              <tr key={mod + '|' + page} style={{ borderTop: isFirst && ri > 0 ? '2px solid var(--line)' : undefined }}>
                {isFirst ? (
                  <td rowSpan={pageCount} style={{ verticalAlign: 'middle', fontWeight: 500, paddingRight: 12 }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={isModuleAllChecked(mod)}
                        onChange={e => toggleModuleAll(mod, e.target.checked)}
                        style={{ cursor: 'pointer' }}
                      />
                      {mod}
                    </label>
                  </td>
                ) : null}
                <td style={{ fontSize: 13, paddingLeft: 8 }}>{page}</td>
                {PERMS.map(perm => (
                  <td key={perm} style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={getVal(mod, page, perm)}
                      onChange={e => setVal(mod, page, perm, e.target.checked)}
                      style={{ cursor: 'pointer' }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
        <button className="dlbtn" onClick={save} style={{ minWidth: 140 }}>
          {saved ? '✓ Saved' : 'Save Permissions'}
        </button>
      </div>
    </div>
  )
}
