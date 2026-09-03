import { useEffect, useRef, useState } from 'react'
import { addPerson, getPeople, removePerson, updatePerson } from './api.js'

const statusCopy = {
  active: ['Active', '#287D3C', '#EDF8F0'],
  access_ready: ['Access ready', '#287D3C', '#EDF8F0'],
  invited: ['Invitation sent', '#315F9E', '#EDF4FF'],
  setup_required: ['Setup needed', '#8A5B00', '#FFF6DF'],
  failed: ['Invite failed', 'var(--error-fg-strong)', '#FFF0F0'],
  suspended: ['Suspended', '#66616A', '#F2F0F3'],
}

function Badge({ status }) {
  const [label, color, background] = statusCopy[status] || [status || 'Access ready', '#555', '#eee']
  return <span style={{ display: 'inline-block', padding: '3px 8px', borderRadius: 99, fontSize: 12, fontWeight: 700, color, background }}>{label}</span>
}

export default function PeopleAccess() {
  const [data, setData] = useState({ people: [], domains: [], invite_enabled: false, can_manage: false })
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [provider, setProvider] = useState('google')
  const [role, setRole] = useState('user')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const emailRef = useRef(null)
  const dialogRef = useRef(null)
  const addButtonRef = useRef(null)

  const load = () => getPeople().then(setData).catch((e) => setError(e.message || 'Could not load people.'))
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!open) return undefined
    emailRef.current?.focus()
    const keydown = (e) => {
      if (e.key === 'Escape') { close(); return }
      if (e.key !== 'Tab') return
      const focusable = [...(dialogRef.current?.querySelectorAll('button, [href], input, select, textarea') || [])].filter((el) => !el.disabled)
      if (!focusable.length) return
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [open])
  const close = () => { setOpen(false); setError(''); setTimeout(() => addButtonRef.current?.focus(), 0) }
  const submit = (e) => {
    e.preventDefault(); setError('')
    if (!email.trim().includes('@')) { setError('Enter a valid email address.'); return }
    setBusy(true)
    addPerson({ email: email.trim().toLowerCase(), provider, role })
      .then((d) => {
        const person = d.person
        setData((old) => ({ ...old, ...d, people: d.people || [...old.people.filter((p) => p.email !== person.email), person] }))
        setMessage(person.status === 'setup_required'
          ? `${person.email} has ACP access. Complete the Microsoft guest setup shown in their row.`
          : person.status === 'failed'
          ? `${person.email} was added, but the Microsoft invitation failed. See their row for details.`
          : `${person.email} is ready to join ACP.`)
        setEmail(''); setRole('user'); close()
      })
      .catch((x) => setError(x.message || 'Could not add this person.'))
      .finally(() => setBusy(false))
  }
  const change = (person, patch) => {
    setError('')
    updatePerson(person.email, patch).then((d) => {
      setData((old) => ({ ...old, ...d, people: d.people || old.people.map((p) => p.email === person.email ? d.person : p) }))
      setMessage(`${person.email} was updated.`)
    }).catch((e) => setError(e.message || 'Could not update this person.'))
  }
  const remove = (person) => {
    if (!window.confirm(`Remove ${person.email} from ACP? They will lose access on their next request.`)) return
    removePerson(person.email).then((d) => { setData((old) => ({ ...old, ...d })); setMessage(`${person.email} was removed.`) })
      .catch((e) => setError(e.message || 'Could not remove this person.'))
  }
  const active = data.people.filter((p) => p.status !== 'suspended').length
  const pending = data.people.filter((p) => ['invited', 'setup_required', 'failed'].includes(p.status)).length

  return <section aria-labelledby="people-title" style={{ maxWidth: 860 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
      <div><h3 id="people-title" style={{ margin: 0 }}>People</h3><div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{active} with access{pending ? ` · ${pending} need attention` : ''}</div></div>
      {data.can_manage && <button ref={addButtonRef} onClick={() => setOpen(true)}>+ Add people</button>}
    </div>
    {data.domains?.length > 0 && <div role="note" style={{ marginTop: 14, padding: 12, border: '1px solid #E5C875', borderRadius: 9, background: '#FFF8E7', fontSize: 13 }}>
      <b>Domain-wide access is on.</b> Anyone at {data.domains.map((d) => `@${d}`).join(', ')} can sign in even if they are not listed here.
    </div>}
    <div role="status" aria-live="polite" style={{ minHeight: 22, marginTop: 10, color: error ? 'var(--error-fg-strong)' : '#287D3C', fontSize: 13 }}>{error || message}</div>
    <div style={{ border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden' }}>
      {data.people.length === 0 ? <p className="muted" style={{ padding: 18, margin: 0 }}>No people have been added yet.</p> : data.people.map((person, i) => <div key={person.email} style={{ display: 'grid', gridTemplateColumns: 'minmax(210px, 1.5fr) 110px 140px minmax(180px, 1fr)', gap: 12, alignItems: 'center', padding: '13px 14px', borderTop: i ? '1px solid var(--line)' : 0 }}>
        <div><b style={{ fontSize: 13 }}>{person.email}</b><div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{person.provider === 'microsoft' ? 'Microsoft · SharePoint / OneDrive' : person.provider === 'google' ? 'Google · Drive' : person.role === 'owner' ? 'Workspace owner' : 'Provider not recorded'}</div></div>
        <Badge status={person.status} />
        {person.protected ? <b style={{ fontSize: 12 }}>Owner</b> : data.can_manage ? <select aria-label={`Access level for ${person.email}`} value={person.role || 'user'} onChange={(e) => change(person, { role: e.target.value })}><option value="user">User</option><option value="admin">Platform Admin</option></select> : <span style={{ fontSize: 12 }}>{person.role === 'admin' ? 'Platform Admin' : 'User'}</span>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {person.status === 'setup_required' && <a href="https://entra.microsoft.com/#view/Microsoft_AAD_UsersAndTenants/UserManagementMenuBlade/~/GuestUsers" target="_blank" rel="noreferrer">Invite in Entra ↗</a>}
          {person.failure && <span title={person.failure} style={{ fontSize: 12, color: 'var(--error-fg-strong)' }}>Invitation needs attention</span>}
          {data.can_manage && !person.protected && <><button className="ghost small" onClick={() => change(person, { status: person.status === 'suspended' ? 'access_ready' : 'suspended' })}>{person.status === 'suspended' ? 'Restore' : 'Suspend'}</button><button className="ghost small" onClick={() => remove(person)}>Remove</button></>}
        </div>
      </div>)}
    </div>
    <p className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>People sign in with their existing Google or Microsoft identity. Their Drive, OneDrive, and SharePoint access remains governed by that provider; adding them here does not grant access to source documents.</p>

    {open && <div role="presentation" onMouseDown={(e) => e.target === e.currentTarget && close()} style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(24,18,25,.42)', display: 'grid', placeItems: 'center', padding: 20 }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="add-person-title" style={{ width: 'min(500px, 100%)', padding: 22, borderRadius: 12, background: 'var(--surface)', boxShadow: '0 20px 60px rgba(0,0,0,.25)' }}>
      <form onSubmit={submit}>
        <h3 id="add-person-title" style={{ marginTop: 0 }}>Add a person</h3>
        <label style={{ display: 'grid', gap: 6, fontSize: 13, fontWeight: 700 }}>Work email<input ref={emailRef} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" required style={{ padding: 9 }} /></label>
        <fieldset style={{ border: 0, padding: 0, margin: '18px 0 0' }}><legend style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>They sign in with</legend><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <label style={{ padding: 12, border: `2px solid ${provider === 'google' ? '#315F9E' : 'var(--line)'}`, borderRadius: 9 }}><input type="radio" name="provider" value="google" checked={provider === 'google'} onChange={() => setProvider('google')} /> <b>Google</b><div className="muted" style={{ margin: '5px 0 0 22px', fontSize: 12 }}>Google Drive</div></label>
          <label style={{ padding: 12, border: `2px solid ${provider === 'microsoft' ? '#315F9E' : 'var(--line)'}`, borderRadius: 9 }}><input type="radio" name="provider" value="microsoft" checked={provider === 'microsoft'} onChange={() => setProvider('microsoft')} /> <b>Microsoft</b><div className="muted" style={{ margin: '5px 0 0 22px', fontSize: 12 }}>SharePoint / OneDrive</div></label>
        </div></fieldset>
        <label style={{ display: 'grid', gap: 6, marginTop: 16, fontSize: 13, fontWeight: 700 }}>Access level<select value={role} onChange={(e) => setRole(e.target.value)}><option value="user">User — scan and work with documents</option><option value="admin">Platform Admin — manage ACP settings</option></select></label>
        <div role="note" className="muted" style={{ marginTop: 14, padding: 11, borderRadius: 8, background: '#F4F2F5', fontSize: 12, lineHeight: 1.5 }}>{provider === 'microsoft' ? (data.invite_enabled ? 'ACP will send a Microsoft guest invitation and grant access when you add them.' : 'ACP will grant access now. Microsoft guest invitations are not connected, so you will see one short setup step afterward.') : 'ACP will grant access now. If the Google OAuth app is still in testing, also add this email as a Google test user.'}</div>
        {error && <p role="alert" style={{ color: 'var(--error-fg-strong)', fontSize: 13 }}>{error}</p>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}><button type="button" className="ghost" onClick={close}>Cancel</button><button type="submit" disabled={busy}>{busy ? 'Adding…' : 'Add person'}</button></div>
      </form>
      </div>
    </div>}
  </section>
}
