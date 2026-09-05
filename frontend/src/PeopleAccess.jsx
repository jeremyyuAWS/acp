import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { addPerson, getPeople, removePerson, updatePerson, getWorkspaceRoles, assignWorkspaceRole, roleImpact } from './api.js'

// LABELS ONLY. The colours moved to `.people-badge.is-<status>` in styles.css so they can be the
// app's semantic tokens (--success-*/--warn-*/--info-*/--error-*) rather than hex literals. Those
// tokens exist for exactly these states, and `failed` was already reaching for one while the rest
// were hardcoded — which is what a table looks like after it has drifted rather than been chosen.
const statusCopy = {
  active: 'Active',
  access_ready: 'Access ready',
  invited: 'Invitation sent',
  setup_required: 'Setup needed',
  failed: 'Invite failed',
  suspended: 'Suspended',
}

function Badge({ status }) {
  // The wrapper is load-bearing: a DIRECT grid child is blockified, so the badge's
  // `display: inline-block` computed to `block` and the tint stretched across the whole column
  // as a band instead of hugging the label. See the note on `.people-badge` in styles.css.
  const known = Object.prototype.hasOwnProperty.call(statusCopy, status)
  return <div className="people-badge-cell">
    <span className={`people-badge is-${known ? status : 'unknown'}`}>
      {known ? statusCopy[status] : (status || 'Access ready')}
    </span>
  </div>
}

/**
 * Render an overlay at document.body instead of where it sits in the tree.
 *
 * WHY THIS IS NOT COSMETIC. Both dialogs below are `position: fixed; inset: 0`, and both are
 * rendered inside Settings, whose `.setoverlay` sets `backdrop-filter: blur(2px)`. An element
 * with a backdrop-filter becomes the CONTAINING BLOCK for its fixed-position descendants, so
 * "fixed" stopped meaning "relative to the viewport" and started meaning "relative to the
 * settings overlay" — which scrolls.
 *
 * The consequence, measured in Chromium on the People screen: with the panel scrolled, the
 * confirmation dialog rendered at y=-21 with its scrim at y=-105, i.e. above the top of the
 * window. Selecting a role therefore did nothing an administrator could see — the dialog was
 * there, focusable, and off-screen. That is the whole reported bug: "the dropdown does not
 * work". It saves only after the confirmation, and the confirmation was never visible.
 *
 * A portal moves the DOM node out of that ancestor, so `fixed` resolves against the viewport
 * again. React events still propagate along the REACT tree, so `.setpanel`'s stopPropagation
 * still keeps a click inside the dialog from closing Settings — the behaviour is unchanged, only
 * the position is fixed.
 *
 * Guarded on `document` so a non-DOM render (SSR, a bare unit test) falls back to rendering in
 * place rather than throwing.
 */
const Overlay = ({ children }) =>
  (typeof document === 'undefined' ? children : createPortal(children, document.body))

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

  const [roles, setRoles] = useState([])
  // The rollout rung, which GET /admin/roles has always returned and this screen has
  // always thrown away. See the note it feeds, below the heading.
  const [enforced, setEnforced] = useState(true)
  const [rollout, setRollout] = useState(null)
  // The role change that JUST HAPPENED, reported as a toast in the top-right corner.
  //
  // This replaced a modal confirmation (PRD §9 originally specified one, and it shipped). The
  // change was asked for directly: the confirmation made every assignment a two-step act, and
  // assigning roles to a roster is a repetitive job. What the dialog carried that a plain
  // "saved" message does not is the SERVER-COMPUTED IMPACT — which capabilities the person
  // gains and, the half nobody can derive from two role names, which they lose. That moves into
  // the toast, and an Undo replaces the Cancel button: the safety is now after the fact rather
  // than before it, which is the trade this change makes deliberately.
  const [roleToast, setRoleToast] = useState(null)

  // The toast carries an Undo, so it has to outlast READING it — three short lines plus a
  // decision. LiveOperationsNotifier's 8s is for a toast you can only dismiss; this one is the
  // entire safety net for a change that now happens without asking, so it is given longer.
  useEffect(() => {
    if (!roleToast) return undefined
    const timer = setTimeout(() => setRoleToast(null), 12000)
    return () => clearTimeout(timer)
  }, [roleToast])

  const load = () => getPeople().then(setData).catch((e) => setError(e.message || 'Could not load people.'))
  useEffect(() => { load() }, [])
  // Best-effort: a caller without roles.manage gets a 403 here, and that is not an error worth
  // showing them — it means the role column is simply not theirs to use, and the People screen
  // still does everything else it did before.
  useEffect(() => {
    getWorkspaceRoles()
      .then((r) => { setRoles(r.roles || []); setEnforced(r.enforced !== false); setRollout(r.rollout || null) })
      // `enforced` stays TRUE on failure, deliberately. This note exists to warn that an
      // assignment may do nothing; showing it because a request failed would cry wolf on a screen
      // where the roles are also missing, and an operator who learns to ignore it once ignores it
      // when it is true.
      .catch(() => setRoles([]))
  }, [])

  // Paint the new role on the row immediately. The select is CONTROLLED by
  // `person.workspace_role_id`, so without this it snaps back to the old value for the length of
  // the round trip — which, on the screen whose whole reported bug was "the dropdown does not
  // do anything", is the one thing it must not do.
  const showRole = (email, roleId) => setData((old) => ({
    ...old,
    people: old.people.map((p) => (p.email === email ? { ...p, workspace_role_id: roleId || null } : p)),
  }))

  const changeRole = (person, roleId) => {
    const previousRoleId = person.workspace_role_id || ''
    if (roleId === previousRoleId) return
    setError('')
    showRole(person.email, roleId)
    // THE IMPACT IS ASKED FOR BEFORE THE ASSIGNMENT LANDS, and the order is load-bearing: it is
    // the difference between the role they hold NOW and the one they are moving to. Asked
    // afterwards, the server would be comparing the new role with itself and would answer
    // "nothing changes" every single time — a preview that is always empty is worse than none,
    // because it reads as a fact about the roles rather than about when it was requested.
    //
    // A failed preview still must not block the write: the assignment is the operation, the
    // impact is commentary. `.catch(() => null)` degrades it to "could not be previewed".
    roleImpact(person.email, roleId).catch(() => null)
      .then((impact) => assignWorkspaceRole(person.email, roleId).then(() => impact))
      .then((impact) => { setRoleToast({ at: Date.now(), person, roleId, previousRoleId, impact }); load() })
      // load() on failure too — the optimistic paint above has to be undone by the truth rather
      // than by guessing what the server kept.
      .catch((e) => { setRoleToast(null); setError(e.message || 'Could not change this role.'); load() })
  }

  const undoRoleChange = () => {
    if (!roleToast) return
    const { person, previousRoleId } = roleToast
    setRoleToast(null)
    setError('')
    showRole(person.email, previousRoleId)
    assignWorkspaceRole(person.email, previousRoleId)
      .then(() => load())
      .catch((e) => { setError(e.message || 'Could not undo this change.'); load() })
  }
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
    {data.domains?.length > 0 && <div role="note" className="people-domain-note">
      <b>Domain-wide access is on.</b> Anyone at {data.domains.map((d) => `@${d}`).join(', ')} can sign in even if they are not listed here.
    </div>}
    {/* THE SAME WARNING THE ROLES SCREEN CARRIES, ON THE SCREEN WHERE ROLES ARE ACTUALLY GIVEN.
        WorkspaceRoles.jsx says "Roles are not being enforced yet" because an administrator who
        designs a role and believes access is now restricted is in a worse position than one who
        knows it is not. Assigning is the same act with the same consequence, and this screen said
        nothing: the dropdown changed, "Alice's role was updated" appeared in green, and every
        route still admitted her exactly as before.

        The server has always sent the rung on this very request — `enforced` and `rollout` come
        back from GET /admin/roles alongside the roles the dropdown is built from — so
        the information was already in the response this component throws away. Wording from
        `rollout.means`, so it cannot drift from what the code does.

        Only when roles EXIST: on a deployment with none there is no dropdown to qualify, and a
        warning about the effect of an action nobody can take is noise. */}
    {roles.length > 0 && !enforced && (
      <div role="note" className="roles-not-enforced" style={{ marginTop: 10 }}>
        <b>Roles are not being enforced yet.</b>{' '}
        {rollout?.means || 'You can assign them now; nothing changes for anyone.'}
        {rollout?.next && <> Next stage: <code>{rollout.next}</code>.</>}
      </div>
    )}
    <div role="status" aria-live="polite" style={{ minHeight: 22, marginTop: 10, color: error ? 'var(--error-fg-strong)' : '#287D3C', fontSize: 13 }}>{error || message}</div>
    <div style={{ border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden' }}>
      {data.people.length === 0 ? <p className="muted" style={{ padding: 18, margin: 0 }}>No people have been added yet.</p> : data.people.map((person) => <div key={person.email} className={roles.length > 0 ? 'people-row has-role-column' : 'people-row'}>
        <div><b className="people-email">{person.email}</b><div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{person.provider === 'microsoft' ? 'Microsoft · SharePoint / OneDrive' : person.provider === 'google' ? 'Google · Drive' : person.role === 'owner' ? 'Workspace owner' : 'Provider not recorded'}</div></div>
        <Badge status={person.status} />
        {person.protected ? <b style={{ fontSize: 12 }}>Owner</b> : data.can_manage ? <select className="people-select" aria-label={`Access level for ${person.email}`} value={person.role || 'user'} onChange={(e) => change(person, { role: e.target.value })}><option value="user">User</option><option value="admin">Platform Admin</option></select> : <span style={{ fontSize: 12 }}>{person.role === 'admin' ? 'Platform Admin' : 'User'}</span>}
        {/* The WORKSPACE role (PRD §9), a different thing from the platform access level beside
            it: that one decides whether they can touch platform settings, this one decides which
            tabs they see. Shown only when roles exist — on a deployment that has not been
            migrated there is nothing to choose from, and an empty select reads as a broken
            control rather than an absent feature. */}
        {roles.length > 0 && (
          <div className="people-role-cell">
            {person.protected ? (
              <span style={{ fontSize: 12 }}>Owner — full access</span>
            ) : (
              <select className={`people-select${person.workspace_role_id ? '' : ' is-unassigned'}`}
                      aria-label={`Workspace role for ${person.email}`}
                      value={person.workspace_role_id || ''}
                      onChange={(e) => changeRole(person, e.target.value)}>
                <option value="">No role</option>
                {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            )}
          </div>
        )}
        <div className="people-row-actions">
          {person.status === 'setup_required' && <a href="https://entra.microsoft.com/#view/Microsoft_AAD_UsersAndTenants/UserManagementMenuBlade/~/GuestUsers" target="_blank" rel="noreferrer">Invite in Entra ↗</a>}
          {person.failure && <span title={person.failure} style={{ fontSize: 12, color: 'var(--error-fg-strong)' }}>Invitation needs attention</span>}
          {data.can_manage && !person.protected && <><button className="ghost small" onClick={() => change(person, { status: person.status === 'suspended' ? 'access_ready' : 'suspended' })}>{person.status === 'suspended' ? 'Restore' : 'Suspend'}</button><button className="ghost small" onClick={() => remove(person)}>Remove</button></>}
        </div>
      </div>)}
    </div>
    <p className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>People sign in with their existing Google or Microsoft identity. Their Drive, OneDrive, and SharePoint access remains governed by that provider; adding them here does not grant access to source documents.</p>

    {/* WHAT JUST HAPPENED, not a question about what is about to.
        Portalled for the SAME reason the dialogs are (see Overlay above): this is
        `position: fixed`, Settings' `.setoverlay` carries a `backdrop-filter`, and a
        fixed-position descendant of one of those is positioned against IT rather than the
        viewport. A toast pinned to the top-right corner of a scrolling panel is the identical
        bug in a new place — it would drift off-screen exactly as the confirmation did.

        Geometry and tokens match LiveOperationsToast deliberately: the application already has
        one top-right toast, and a second at different coordinates on a different surface reads
        as a different product. The one property that does NOT match is `color` — that file asks
        for `var(--text)`, which is defined nowhere in this codebase (it is used twice and set
        never), so it silently resolves to nothing and inherits. `--ink` is the real token. */}
    {roleToast && <Overlay>
      <div role="status" aria-live="polite" aria-atomic="true" className="people-toast">
        <div className="people-toast-head">
          <b>Role updated</b>
          <button type="button" className="ghost small" aria-label="Dismiss notification"
                  onClick={() => setRoleToast(null)}>×</button>
        </div>
        <p className="people-toast-line">
          {roleToast.person.email} is now <b>{roles.find((r) => r.id === roleToast.roleId)?.name || 'unassigned'}</b>.
        </p>
        {/* PAST TENSE, and that is not a nicety. The dialog said "they will lose"; by the time
            this is on screen they already have. Copy that still reads as a forecast invites an
            administrator to think there is something left to approve. */}
        {roleToast.impact === null ? (
          <p className="muted people-toast-line">
            The exact effect could not be previewed. The change itself went through.
          </p>
        ) : (
          <>
            {roleToast.impact.loses?.length > 0 && (
              <p className="people-toast-line"><b>Lost:</b> {roleToast.impact.loses.join(', ')}</p>
            )}
            {roleToast.impact.gains?.length > 0 && (
              <p className="people-toast-line"><b>Gained:</b> {roleToast.impact.gains.join(', ')}</p>
            )}
            {!roleToast.impact.loses?.length && !roleToast.impact.gains?.length && (
              <p className="muted people-toast-line">Nothing they can do today changes.</p>
            )}
            {/* WHAT "NOT ENFORCED" MEANS DEPENDS ON THE RUNG, and saying the wrong one is worse
                than saying nothing. At `navigation` this assignment DOES take effect — their
                tabs disappear on the next load — while the server still answers a direct
                request. Telling an administrator it "changes nothing" at that rung would have
                them alter somebody's access believing they had not. */}
            {roleToast.impact.enforced === false && (
              <p className="muted people-toast-line">
                {roleToast.impact.mode === 'navigation'
                  ? 'This hides tabs for them on their next page load, but the server still '
                    + 'allows direct requests until the rollout reaches the enforce stage.'
                  : 'Roles are not being enforced yet, so this changes nothing for them until the '
                    + 'rollout advances.'}
              </p>
            )}
          </>
        )}
        {/* The Undo is what the Cancel button became. Without it this screen would assign on a
            single stray change event with no way back except knowing what the previous role
            was — which, for a role the administrator did not set, they do not. */}
        <div className="people-toast-actions">
          <button type="button" className="ghost small" onClick={undoRoleChange}>Undo</button>
        </div>
      </div>
    </Overlay>}

    {open && <Overlay><div role="presentation" onMouseDown={(e) => e.target === e.currentTarget && close()} style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(24,18,25,.42)', display: 'grid', placeItems: 'center', padding: 20 }}>
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
    </div></Overlay>}
  </section>
}
