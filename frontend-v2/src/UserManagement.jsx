import { useState } from 'react'
import { loadAllRoles, loadCustomRoles, saveCustomRoles, BUILTIN_ROLES } from './roleRegistry.js'

const AI_SOLUTIONS = ['App Engineering', 'Quality Engineering', 'Enterprise Ops', 'SDLC', 'CX', 'Target ITOps', 'SDLC Subscription', 'QE for Healthcare']
const TEAMS        = ['Development Team', 'QA Team', 'Devops Team', 'Management Team', 'HC QC Team', 'IT Support Target', 'Salesforce Team']
// ROLES loaded dynamically from roleRegistry so new custom roles appear here too

// Seeded demo users — matches the style from the Movate platform screenshot
let NEXT_ID = 7
const SEED_USERS = [
  { id: 1, first: 'Mohamed',    last: 'Luthufullah', email: 'Mohamed.Luthufullah@movate.com',
    solutions: ['Quality Engineering', 'SDLC', 'App Engineering'],
    teams: ['QA Team', 'Development Team', 'Development Team'],
    roles: ['Test Manager', 'Admin', 'Super Admin'], active: true },
  { id: 2, first: 'NaveenKumar', last: 'Keasavan',   email: 'naveenkumar.kesavan@movate.com',
    solutions: ['App Engineering', 'Quality Engineering', 'Enterprise Ops', 'SDLC Subscription'],
    teams: ['Development Team', 'QA Team', 'Devops Team', 'Management Team'],
    roles: ['Super Admin', 'Test Manager', 'Admin', 'Admin'], active: true },
  { id: 3, first: 'Gobu',       last: 'Durai',       email: 'gobu.durairasu@movate.com',
    solutions: ['App Engineering', 'Enterprise Ops', 'CX'],
    teams: ['Development Team', 'QA Team', 'Devops Team', 'Salesforce Team'],
    roles: ['Super Admin', 'Test Manager', 'Admin', 'Admin'], active: true },
  { id: 4, first: 'Meena',      last: 'RahulMalu',   email: 'meena.rahulmalu@movate.com',
    solutions: ['App Engineering', 'Quality Engineering', 'Enterprise Ops', 'QE for Healthcare'],
    teams: ['Development Team', 'QA Team', 'Devops Team', 'HC QC Team', 'IT Support Target'],
    roles: ['Super Admin', 'Admin', 'Test Manager', 'HC Quality Engineer', 'IT Support Target'], active: true },
  { id: 5, first: 'Devanathan', last: 'Desikan',     email: 'devanathan.desikan@movate.com',
    solutions: ['App Engineering', 'Enterprise Ops', 'Quality Engineering', 'Target ITOps'],
    teams: ['Development Team', 'Devops Team', 'QA Team', 'IT Support Target'],
    roles: ['Super Admin', 'Admin', 'Test Manager', 'IT Support Target'], active: true },
  { id: 6, first: 'Priya',      last: 'Sundaram',    email: 'priya.sundaram@movate.com',
    solutions: ['Quality Engineering'],
    teams: ['QA Team'],
    roles: ['Test Manager'], active: false },
]

const LS_KEY = 'mova_users'
const loadUsers = () => { try { const s = localStorage.getItem(LS_KEY); return s ? JSON.parse(s) : [...SEED_USERS] } catch { return [...SEED_USERS] } }
const saveUsers = (u) => { try { localStorage.setItem(LS_KEY, JSON.stringify(u)) } catch {} }

const MultiChips = ({ values }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
    {values.map((v, i) => (
      <span key={i} style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{v}</span>
    ))}
  </div>
)

// Compute union of permissions across all a user's roles using the stored privilege map.
// If no map exists yet for a role, that role contributes no permissions.
const computeEffective = (userRoles, allPrivileges, solution, team) => {
  const result = {}
  userRoles.forEach(role => {
    const key = solution + '||' + team + '||' + role
    const rolePerms = allPrivileges[key]
    if (!rolePerms) return
    Object.entries(rolePerms).forEach(([mod, pages]) => {
      result[mod] = result[mod] || {}
      Object.entries(pages).forEach(([page, perms]) => {
        result[mod][page] = result[mod][page] || {}
        Object.entries(perms).forEach(([perm, val]) => {
          if (val) result[mod][page][perm] = true
        })
      })
    })
  })
  return result
}

const LS_PRIVS = 'mova_role_privileges'
const loadPrivileges = () => { try { return JSON.parse(localStorage.getItem(LS_PRIVS) || '{}') } catch { return {} } }

function EffectivePermsPopover({ user, onClose }) {
  const privs = loadPrivileges()
  const solution = (user.solutions && user.solutions[0]) || 'App Engineering'
  const team     = (user.teams     && user.teams[0])     || 'Development Team'
  const effective = computeEffective(user.roles || [], privs, solution, team)
  const hasAny = Object.keys(effective).length > 0
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 10, padding: 24, maxWidth: 480, width: '90vw', maxHeight: '70vh', overflow: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.18)' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <b style={{ fontSize: 14 }}>Effective permissions · {user.first} {user.last}</b>
          <button className="ghost small" onClick={onClose}>✕</button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Union of {user.roles.length} role{user.roles.length !== 1 ? 's' : ''}: {user.roles.join(', ')} · via {solution} / {team}
        </div>
        {!hasAny ? (
          <p className="muted" style={{ fontSize: 13 }}>No permissions configured yet for these roles. Open Settings → Permissions to assign them.</p>
        ) : (
          Object.entries(effective).map(([mod, pages]) => (
            <div key={mod} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 12, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{mod}</div>
              {Object.entries(pages).map(([page, perms]) => {
                const granted = Object.entries(perms).filter(([,v]) => v).map(([k]) => k)
                if (!granted.length) return null
                return (
                  <div key={page} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4, fontSize: 12 }}>
                    <span style={{ minWidth: 160 }}>{page}</span>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {granted.map(p => (
                        <span key={p} style={{ background: '#E7F0DC', color: '#3B6D11', borderRadius: 3, padding: '1px 5px', fontSize: 10, fontWeight: 600 }}>{p}</span>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          ))
        )}
        <p className="muted" style={{ fontSize: 11, marginTop: 12, borderTop: '1px solid var(--line)', paddingTop: 10 }}>
          Effective = union of all role permissions. Each role only adds; never subtracts. Least-privilege: assign narrow roles, combine as needed.
        </p>
      </div>
    </div>
  )
}

const MultiSelect = ({ label, options, value, onChange }) => {
  const toggle = (opt) => {
    const next = value.includes(opt) ? value.filter(v => v !== opt) : [...value, opt]
    onChange(next)
  }
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 6 }}>{label}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {options.map(opt => (
          <button key={opt}
            type="button"
            onClick={() => toggle(opt)}
            className={value.includes(opt) ? 'fchip on' : 'fchip'}
            style={{ fontSize: 11 }}>
            {opt}
          </button>
        ))}
      </div>
      {value.length === 0 && <p className="muted" style={{ fontSize: 11, marginTop: 4 }}>Select at least one</p>}
    </div>
  )
}

function UserDetailsTab({ users, onDelete, onToggleActive }) {
  const [search, setSearch] = useState('')
  const [viewPerms, setViewPerms] = useState(null)
  const filtered = users.filter(u =>
    (u.first + ' ' + u.last + ' ' + u.email).toLowerCase().includes(search.toLowerCase())
  )
  return (
    <div>
      <input
        type="search" placeholder="Search"
        value={search} onChange={e => setSearch(e.target.value)}
        style={{ fontSize: 13, padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 4, width: 220, marginBottom: 14 }}
        aria-label="Search users"
      />
      <div style={{ overflowX: 'auto' }}>
        <table className="ruletable" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', width: 32, paddingRight: 8 }}>#</th>
              <th style={{ textAlign: 'left' }}>First Name</th>
              <th style={{ textAlign: 'left' }}>Last Name</th>
              <th style={{ textAlign: 'left' }}>Email ID</th>
              <th style={{ textAlign: 'left' }}>AI Solution</th>
              <th style={{ textAlign: 'left' }}>Team</th>
              <th style={{ textAlign: 'left' }}>Role</th>
              <th style={{ textAlign: 'center' }}>IsActive</th>
              <th style={{ textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(u => (
              <tr key={u.id} style={{ opacity: u.active ? 1 : 0.55 }}>
                <td className="muted" style={{ paddingRight: 8, fontVariantNumeric: 'tabular-nums' }}>{u.id}</td>
                <td style={{ fontWeight: 500 }}>{u.first}</td>
                <td>{u.last}</td>
                <td className="muted" style={{ fontSize: 12 }}>{u.email}</td>
                <td><MultiChips values={u.solutions} /></td>
                <td><MultiChips values={u.teams} /></td>
                <td><MultiChips values={u.roles} /></td>
                <td style={{ textAlign: 'center' }}>
                  <span style={{
                    fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 3,
                    background: u.active ? '#E7F0DC' : '#f3f0f7',
                    color: u.active ? '#3B6D11' : '#5b4a72'
                  }}>{u.active ? 'true' : 'false'}</span>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                    <button className="ghost small" title="Send email" style={{ fontSize: 13 }} onClick={() => {}}>✉</button>
                    <button className="ghost small" title="Effective permissions" style={{ fontSize: 13 }} onClick={() => setViewPerms(u)}>⊙</button>
                    <button className="ghost small" title={u.active ? 'Deactivate' : 'Activate'} style={{ fontSize: 13 }} onClick={() => onToggleActive(u.id)}>
                      {u.active ? '⊘' : '⊕'}
                    </button>
                    <button className="ghost small" title="Delete user" style={{ fontSize: 13, color: '#d9534f' }} onClick={() => { if (window.confirm('Remove ' + u.first + ' ' + u.last + '?')) onDelete(u.id) }}>✕</button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={9} className="muted" style={{ textAlign: 'center', padding: 20 }}>No users match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {viewPerms && <EffectivePermsPopover user={viewPerms} onClose={() => setViewPerms(null)} />}
    </div>
  )
}

function OnboardUserTab({ onAdded }) {
  const blank = { first: '', last: '', email: '', solutions: [], teams: [], roles: [] }
  const [form, setForm] = useState(blank)
  const [sent, setSent] = useState(false)

  const valid = form.first && form.last && form.email.includes('@') && form.solutions.length && form.teams.length && form.roles.length

  const submit = (e) => {
    e.preventDefault()
    if (!valid) return
    const newUser = { ...form, id: NEXT_ID++, active: true }
    onAdded(newUser)
    setSent(true)
    setTimeout(() => { setSent(false); setForm(blank) }, 2500)
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 560 }}>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        Fill in the details below. The user will receive an invite email and can set their password on first sign-in.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <label style={{ fontSize: 12, fontWeight: 500 }}>
          First Name
          <input type="text" value={form.first} onChange={e => setForm(f => ({ ...f, first: e.target.value }))}
            required style={{ display: 'block', marginTop: 4, width: '100%', fontSize: 13, padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 4 }} />
        </label>
        <label style={{ fontSize: 12, fontWeight: 500 }}>
          Last Name
          <input type="text" value={form.last} onChange={e => setForm(f => ({ ...f, last: e.target.value }))}
            required style={{ display: 'block', marginTop: 4, width: '100%', fontSize: 13, padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 4 }} />
        </label>
      </div>
      <label style={{ fontSize: 12, fontWeight: 500, display: 'block', marginBottom: 14 }}>
        Email ID
        <input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
          required style={{ display: 'block', marginTop: 4, width: '100%', fontSize: 13, padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 4 }} />
      </label>
      <MultiSelect label="AI Solution" options={AI_SOLUTIONS} value={form.solutions} onChange={v => setForm(f => ({ ...f, solutions: v }))} />
      <MultiSelect label="Team" options={TEAMS} value={form.teams} onChange={v => setForm(f => ({ ...f, teams: v }))} />
      <MultiSelect label="Role (multiple = least-privilege union)" options={loadAllRoles()} value={form.roles} onChange={v => setForm(f => ({ ...f, roles: v }))} />
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
        <button type="submit" className="dlbtn" disabled={!valid || sent} style={{ minWidth: 160 }}>
          {sent ? '✓ Invite sent' : 'Send Invite'}
        </button>
        {!valid && <span className="muted" style={{ fontSize: 12 }}>Fill all required fields</span>}
      </div>
    </form>
  )
}

export default function UserManagement() {
  const [users, setUsers] = useState(loadUsers)
  const [tab, setTab] = useState('details')

  const update = (next) => { setUsers(next); saveUsers(next) }
  const onDelete = (id) => update(users.filter(u => u.id !== id))
  const onToggleActive = (id) => update(users.map(u => u.id === id ? { ...u, active: !u.active } : u))
  const onAdded = (u) => { const next = [...users, u]; update(next); setTab('details') }

  return (
    <div>
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid var(--line)' }}>
        <button
          role="tab" aria-selected={tab === 'details'}
          onClick={() => setTab('details')}
          style={{ fontSize: 13, fontWeight: tab === 'details' ? 600 : 400, padding: '6px 18px', background: 'none', border: 'none', borderBottom: tab === 'details' ? '2px solid var(--ink)' : '2px solid transparent', cursor: 'pointer', marginBottom: -1 }}>
          User Details
        </button>
        <button
          role="tab" aria-selected={tab === 'onboard'}
          onClick={() => setTab('onboard')}
          style={{ fontSize: 13, fontWeight: tab === 'onboard' ? 600 : 400, padding: '6px 18px', background: 'none', border: 'none', borderBottom: tab === 'onboard' ? '2px solid var(--ink)' : '2px solid transparent', cursor: 'pointer', marginBottom: -1 }}>
          Onboard User
        </button>
      </div>
      {tab === 'details' && <UserDetailsTab users={users} onDelete={onDelete} onToggleActive={onToggleActive} />}
      {tab === 'onboard' && <OnboardUserTab onAdded={onAdded} />}
    </div>
  )
}
