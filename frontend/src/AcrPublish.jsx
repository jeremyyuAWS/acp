import { useEffect, useState } from 'react'
import { getAcrPublication, publishAcr, getAcrRevisions, reviseAcr,
         downloadAcrRevisionPdf } from './acrApi'

/**
 * Publication and revision history (PRD §16, §17, Phase 4).
 *
 * THIS SCREEN GUARDS THE ONE IRREVERSIBLE ACT IN THE FEATURE. An ACR goes into a customer's
 * procurement file and cannot be recalled, so three things matter more here than anywhere else:
 *
 *   1. **The screen never decides whether publishing is allowed.** `may_publish` comes from the
 *      server, which recomputes the whole gate — every blocker plus the role check — on the
 *      publish request itself. A UI that decided for itself is how you get a button the server
 *      rejects, or worse, one that publishes something the gate would have stopped.
 *
 *   2. **Irreversibility is stated before the click, not after.** A confirmation step that only
 *      says "are you sure" teaches people to click through it; this one says what becomes true.
 *
 *   3. **The separation-of-duties warning is shown and never blocks.** PRD §18 words it as a
 *      recommendation conditioned on a second reviewer being available, and the server only emits
 *      it when one is. Rendering it as an error would make a one-person team unable to publish.
 */

export default function AcrPublish({ reportId, onChange }) {
  const [ready, setReady] = useState(null)
  const [revs, setRevs] = useState(null)
  const [error, setError] = useState(null)
  const [downloadError, setDownloadError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState(null)

  const load = () => Promise.all([getAcrPublication(reportId), getAcrRevisions(reportId)])
    .then(([r, v]) => { setReady(r); setRevs(v); setError(null) })
    .catch((e) => setError(e.message))

  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ },
    [reportId])

  if (error) return <p role="alert">{error}</p>
  if (!ready) return <p className="muted">Loading publication status…</p>

  const act = (fn) => {
    setBusy(true)
    return fn()
      .then((r) => { setResult(r); return load() })
      .then(() => { setError(null); onChange && onChange() })
      .catch((e) => setError(e.message))
      .finally(() => { setBusy(false); setConfirming(false) })
  }

  // The published revision as a document to send. Deliberately NOT an <a href> to the endpoint:
  // the route needs the bearer token, an anchor cannot send one, and following it would navigate
  // away from the workspace to a 401. So fetch it with the same headers as everything else and
  // hand the browser a blob — the same shape AcrWorkspace uses for the draft export.
  const downloadRevision = (revision) => {
    setBusy(true)
    setDownloadError(null)
    return downloadAcrRevisionPdf(reportId, revision)
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      })
      // The server's own sentence, not "download failed". A 409 here says the snapshot no longer
      // matches its digest and a 503 names the missing renderer; both are things a person can act
      // on, and neither survives being flattened into a generic failure.
      //
      // ITS OWN STATE, deliberately. `error` is the screen's LOAD failure and returns early from
      // the component — setting it here would replace the whole publication view with one line,
      // taking the revision table and the retry with it. A test caught exactly that: after a
      // failed download there was no button left to press.
      .catch((e) => setDownloadError(String(e.message || e)))
      .finally(() => setBusy(false))
  }

  const published = ready.status === 'published'

  return (
    <section aria-labelledby="acr-publish-heading">
      <h3 id="acr-publish-heading">Publication</h3>

      <p role="status" aria-live="polite">
        {published
          ? `Revision ${ready.revision} is published. Published reports cannot be edited.`
          : ready.may_publish
            ? `Revision ${ready.revision} is ready to publish.`
            : `Revision ${ready.revision} cannot be published yet: ${ready.blocking_count} blocker(s) outstanding.`}
      </p>

      {/* Stated before the action, not in a dialog afterwards. */}
      <p>{ready.irreversible_note}</p>

      {/* The server's own refusal sentence, rendered verbatim. */}
      {ready.role_refusal && <p role="note">{ready.role_refusal}</p>}

      {/* Advisory. PRD §18 is a recommendation, and the server only emits this when a second
          qualified reviewer actually exists. */}
      {ready.separation_warning && (
        <p role="note" className="acr-separation">
          <strong>Separation of duties:</strong> {ready.separation_warning}
        </p>
      )}

      {!published && ready.blocking_count > 0 && (
        <div>
          <h4>What is blocking publication</h4>
          <ul>
            {Object.entries(ready.by_category || {}).map(([cat, rows]) => (
              <li key={cat}>
                {ready.category_labels?.[cat] || cat}: {rows.length}
                <ul>
                  {rows.slice(0, 5).map((row, i) => (
                    <li key={`${cat}-${i}`}>{row.message}</li>
                  ))}
                  {rows.length > 5 && <li className="muted">…and {rows.length - 5} more</li>}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!published && ready.may_publish && !confirming && (
        <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
          Publish revision {ready.revision}
        </button>
      )}

      {!published && confirming && (
        <div role="group" aria-label="Confirm publication">
          <p>
            <strong>This cannot be undone.</strong> Revision {ready.revision} will be frozen as an
            immutable record. Corrections are published as a new revision that supersedes it.
          </p>
          <button type="button" disabled={busy} onClick={() => act(() => publishAcr(reportId))}>
            Publish permanently
          </button>
          <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      )}

      {published && (
        <button type="button" disabled={busy} onClick={() => act(() => reviseAcr(reportId))}>
          Start a new revision
        </button>
      )}

      {result?.reset_criteria && (
        <p role="status">
          {result.note}
          {result.reset_criteria.length > 0 && (
            <> Re-evaluate: {result.reset_criteria.join(', ')}.</>
          )}
        </p>
      )}

      <h4>Revision history</h4>
      {downloadError && <p role="alert">{downloadError}</p>}
      {!revs?.revisions?.length ? <p className="muted">No revision has been published yet.</p> : (
        <table>
          <caption className="sr-only">Published revisions of this report</caption>
          <thead>
            <tr>
              <th scope="col">Revision</th><th scope="col">Published</th>
              <th scope="col">By</th><th scope="col">Digest</th><th scope="col">Integrity</th>
              <th scope="col">Document</th>
            </tr>
          </thead>
          <tbody>
            {revs.revisions.map((r) => (
              <tr key={r.snapshot_id}>
                <th scope="row">{r.revision}</th>
                <td>{r.published_at ? new Date(r.published_at).toLocaleDateString() : '—'}</td>
                <td>{r.published_by}</td>
                <td><code>{(r.content_digest || '').slice(0, 12)}…</code></td>
                {/* Stated in words, never by colour alone — 1.4.1. */}
                <td>{r.digest_verified
                  ? 'Verified — contents match the recorded digest'
                  : `Not verified: ${r.digest_problem}`}</td>
                {/* No download offered for a revision whose contents do not match its digest.
                    The server refuses it too (409), and this is the belt to that braces: an
                    altered record must not be one click from becoming a PDF in a procurement
                    file. The reason is stated in words rather than left as a disabled control
                    with no explanation. */}
                <td>{r.digest_verified ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => downloadRevision(r.revision)}
                  >
                    Download revision {r.revision}
                  </button>
                ) : (
                  <span className="muted">Not available — this snapshot failed verification</span>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        The digest is a recomputable SHA-256 over the snapshot contents. It makes alteration
        detectable. It is not a digital signature and provides no non-repudiation.
      </p>
    </section>
  )
}
