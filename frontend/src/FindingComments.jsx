import { useEffect, useRef, useState } from 'react'
import { getFindingComments, addFindingComment, findingKeyOf, getMe } from './api.js'

// R18 · Comments on a finding — where two people disagree about a judgement call, the
// disagreement should live NEXT TO the finding, not in a chat thread nobody reading the finding
// later can see. This renders the persisted thread for ONE finding (scan × file × criterion ×
// instance) and lets the signed-in user append to it.
//
// It is append-only by design: a comment is a record of what someone said at a point in time, so
// there is no edit or delete here. The author is stamped server-side from the signed-in user, so a
// comment can never be attributed to someone who did not write it (the client cannot set it).
//
// Two honesty rules this component keeps:
//   - Nothing renders until the fetch answers. An empty thread and a failed fetch are different
//     claims; showing "no comments" before the request returns would assert the stronger, wrong one.
//   - The empty state says the thread is empty, not that the finding is uncontested.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

// Compact, local, and stable — the exact format matters less than that every comment carries one.
function when(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric',
                                       hour: '2-digit', minute: '2-digit' })
}

function CommentRow({ c, isMe }) {
  return (
    <li className="finding-comment" data-me={isMe ? '1' : '0'}
        style={{ padding: '9px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <b style={{ fontSize: 12.5, fontWeight: 600 }}>{c.author || 'unknown'}</b>
        {isMe && <span style={{ ...muted, fontSize: 11 }}>(you)</span>}
        <span style={{ ...muted, fontSize: 11.5, fontVariantNumeric: 'tabular-nums',
                       marginLeft: 'auto' }}>{when(c.ts)}</span>
      </div>
      <div style={{ fontSize: 13, marginTop: 3, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {c.body}
      </div>
    </li>
  )
}

/**
 * @param scanId   the scan the finding belongs to. Without it nothing is fetched or rendered.
 * @param finding  the selected finding (the inbox row) — carries file, rule_id/ruleId, location.
 */
export default function FindingComments({ scanId, finding }) {
  const key = finding ? findingKeyOf(finding) : ''
  const [comments, setComments] = useState(null)   // null = not loaded yet
  const [err, setErr] = useState('')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [me, setMe] = useState('')
  const live = useRef(true)

  useEffect(() => {
    getMe().then((m) => { if (live.current) setMe(m?.email || '') }).catch(() => {})
  }, [])

  useEffect(() => {
    live.current = true
    setComments(null); setErr('')
    if (!scanId || !key) return undefined
    getFindingComments(scanId, key)
      .then((d) => { if (live.current) setComments(Array.isArray(d) ? d : []) })
      .catch((e) => { if (live.current) setErr(e?.message || 'unavailable') })
    return () => { live.current = false }
  }, [scanId, key])

  if (!scanId || !finding) return null

  const post = () => {
    const body = draft.trim()
    if (!body || sending) return
    setSending(true); setErr('')
    addFindingComment(scanId, { findingKey: key, body,
                                file: finding.file || '',
                                ruleId: finding.rule_id || finding.ruleId || '' })
      .then((row) => {
        if (!live.current) return
        setComments((cur) => [...(cur || []), row])
        setDraft('')
      })
      .catch((e) => { if (live.current) setErr(e?.message || 'could not post comment') })
      .finally(() => { if (live.current) setSending(false) })
  }

  // Cmd/Ctrl+Enter posts — the textarea keeps Enter for newlines, since comments can be multi-line.
  const onKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); post() }
  }

  return (
    <section className="panel finding-comments" role="region" aria-label="Comments on this finding"
             style={{ marginBottom: 14 }}>
      <div style={kicker}>Comments</div>

      {comments === null
        ? (err
            ? <p role="alert" style={{ ...muted, marginTop: 6 }}>Comments could not be loaded: {err}.</p>
            : <p role="status" aria-live="polite" style={{ ...muted, marginTop: 6 }}>Loading comments…</p>)
        : (
          <>
            {comments.length === 0
              ? <p style={{ ...muted, marginTop: 6 }}>
                  No comments yet — this thread is empty, which is not the same as the finding being
                  uncontested. Add the first note.
                </p>
              : <ul style={{ listStyle: 'none', margin: '6px 0 0', padding: 0 }}>
                  {comments.map((c) => (
                    <CommentRow key={c.id} c={c} isMe={!!me && c.author === me} />
                  ))}
                </ul>}
          </>
        )}

      <div style={{ marginTop: 12 }}>
        <label htmlFor="finding-comment-draft" style={{ ...muted, display: 'block', marginBottom: 4 }}>
          Add a comment
        </label>
        <textarea id="finding-comment-draft" value={draft} rows={3}
                  onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown}
                  placeholder="Note a judgement call, or reply to one…"
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 13, padding: '8px 10px',
                           border: '1px solid var(--line)', borderRadius: 8, resize: 'vertical',
                           fontFamily: 'inherit' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
          <button type="button" onClick={post} disabled={!draft.trim() || sending}
                  style={{ fontSize: 13, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
                           border: '1px solid var(--line)',
                           cursor: (!draft.trim() || sending) ? 'default' : 'pointer',
                           opacity: (!draft.trim() || sending) ? 0.55 : 1 }}>
            {sending ? 'Posting…' : 'Post comment'}
          </button>
          <span style={{ ...muted, fontSize: 11 }}>⌘/Ctrl + Enter</span>
          {err && comments !== null && <span role="alert" style={{ ...muted, color: 'var(--red, #b23b3b)' }}>{err}</span>}
        </div>
      </div>
    </section>
  )
}
