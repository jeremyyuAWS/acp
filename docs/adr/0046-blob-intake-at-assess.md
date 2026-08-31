# ADR 0046 — Blob intake at Assess: copy once, then never read the source again

Status: **Proposed** · Date: 2026-08-31 · Related: [ADR 0010](0010-remediated-output-object-store.md),
[ADR 0011](0011-incremental-scan-fingerprinting.md), [ADR 0020](0020-discover-assess-phase-separation.md),
[ADR 0044](0044-managed-content-workspace-data-model.md)

## Context

A worker assessing a Drive or SharePoint file downloads it from the connector, using a per-user
OAuth token held in Redis. That token expires in about an hour. Everything unpleasant about the
current Assess stage follows from that one fact:

- **A queued job outlives its credential.** The token is captured when the scan starts. A scan
  that sits behind a backlog, or a worker that restarts mid-fan-out, resumes with a dead token —
  and a GIS implicit-flow token cannot be refreshed (`worker.drive_session_expired` classifies it
  terminal and dead-letters immediately, precisely because retrying is guaranteed waste).
- **Retry means re-download.** Every attempt re-fetches from the source, spending the user's API
  quota again for bytes we already had.
- **Discovery and assessment see different files.** Discover records metadata at T0; Assess reads
  bytes at T1. Nothing detects that the document changed in between, so a finding can describe a
  file that no longer exists in that form.
- **Nothing is verified at a boundary.** Bytes go from the connector into the analysers with no
  point at which we could scan, checksum, or quarantine them.

### What already exists, and why it does not solve this

ADR 0020 §Rollout 1 shipped a source-bytes cache: a `sources` blob container, written by
`scanner.cache_source_bytes` and read by `read_cached_source`. It is keyed by content checksum
when one is known before download (`{owner}/{checksum}` — Drive's `md5Checksum`, and since
recently SharePoint's `quickXorHash`), falling back to `{owner}/{scan_id}/{filename}`.

**It is a cache, not an intake, and the distinction is the whole of this ADR:**

1. **Nothing populates it before Assess.** ADR 0020's own §"open each file once" describes
   Discover writing each file's bytes to the cache and Assess reading them back. Rollout stages 3
   and 4 of *that same ADR* then made Discover metadata-only — it opens no file at all. The only
   surviving writer is `handlers.py`'s Assess path, **after** its own `_download`. So on a cold
   estate every file's first assessment is still a live connector fetch with the user's token.
   The cache helps a retry and a re-scan; it has never helped the case that fails.
2. **It is best-effort by construction, and correctly so.** `cache_source_bytes` swallows every
   exception — "a cache failure must never fail or slow a scan". That is right for a cache and
   wrong for a durable copy: nothing guarantees the bytes are there when the retry needs them.
3. **A miss is silent and reads *current* bytes.** `read_cached_source` returns `None` and the
   code falls through to the connector. If the document changed since discovery, the fall-through
   quietly analyses the new version. The checksum key means a *changed* file always misses.
4. **It has no document identity.** Entries are keyed by content hash or by scan, so there is no
   answer to "which versions of this document do we hold, and which one produced this finding?"

Meanwhile ADR 0044 built exactly the missing shape — immutable versions, `{kind}` sub-paths,
retention — for *uploads only*, and explicitly left open "how, or whether, a workspace document
ever becomes visible to the existing Discover/Assess pipeline". `handlers.workspace_scan_file`
already proves the target behaviour: it reads from Blob with the worker's **own managed identity**,
holds no user token, and therefore cannot be orphaned by an expiry.

The result is four containers with four key conventions — `sources` (`{owner}/{checksum}`),
`remediated` (`{owner}/{scan_id}/{filename}`, ADR 0010), `thumbnails` (same, ADR 0015), and
`workspace-content` (`workspace/{owner}/{workspace_id}/{document_id}/{kind}/{version_id}/…`) —
and no single place that answers "give me the bytes this assessment ran on".

## Decision

**Copy connector-sourced files into Blob at the start of Assess, as an authoritative intake, and
have every downstream stage read only from there.** Adopt ADR 0044's workspace layout and version
identity for those copies rather than inventing a fifth key shape.

### 1. At Assess, not at Discover

Discover stays metadata-only. That property is load-bearing — it is what makes Discovery fast
enough to be interactive, and it was paid for in ADR 0020 and again in the four-format scope. A
copy step at Discover would spend bytes on every file in the estate, including everything the user
never selects.

Copying at Assess also means the four-format scope and the user's own selection have already
narrowed the set, so we copy what will actually be analysed and nothing else.

### 2. Intake is authoritative, not best-effort

This inverts `cache_source_bytes`'s contract deliberately. A file whose copy fails is **not**
assessed from the connector as a fallback; it gets an honest `status='error'` file record naming
the intake failure, exactly as `workspace_scan_file` already does when a blob read returns `None`
("the same 'can't verify' = 'can't proceed' stance every other workspace_blob read takes").

Falling back to the connector would reintroduce the token dependency for the one case that most
needs it, and would make the guarantee unstateable: "assessment reads from Blob" is worth
something only if there is no second path.

### 3. One layout, extended — not a new one

Connector-sourced copies use ADR 0044's paths and `{kind}` vocabulary:

```
workspace/{owner_email}/{workspace_id}/{document_id}/source/{version_id}/original
workspace/{owner_email}/{workspace_id}/{document_id}/remediated/{version_id}/artifact
```

Remediation then writes a **new version of the same document** rather than a parallel object in
the ADR 0010 `remediated` container. "We will have a copy after remediation anyway" is true, and
the point is that it should be the same document's next version, not a differently-keyed artifact
that has to be correlated back by filename.

### 4. Identity: bridge, don't fork

This is the question ADR 0044 left open, and the expensive one to get wrong. ADR 0003's
`documents.doc_id` is "source + path hash, or drive_file_id" — identity derived from a connector
listing. ADR 0044's workspace documents have no connector at all.

**Decision: a connector-sourced document gets a workspace document row carrying a `source_ref`**
— `{source, external_id, drive_id?}` — and a unique index on `(owner_email, source, external_id)`.
The ADR 0003 `documents` row keeps its own identity and gains a nullable pointer to the workspace
document. Neither identity is redefined; one gains a link.

The alternative — reusing `documents` and adding version rows to it — was rejected for the reason
ADR 0044 already gave: it would mean loosening `doc_id`'s identity contract for a case it never
anticipated, and inventing a fake per-upload "scan" for the upload path.

### 5. The checksum gate is also the drift detector

Before copying, compare the source checksum from the discovery inventory against the checksums of
existing versions:

- **Match on the newest version** → skip the copy, assess the bytes already held. This is the
  cross-scan reuse ADR 0011 already does for *analysis*, applied to *bytes*.
- **No match** → copy, creating a new version.
- **Checksum differs from what Discover recorded** → still copy, and record the drift explicitly.
  This is the file-drift problem becoming visible rather than silent: the assessment names the
  version it ran on, and a report can say the document changed after it was discovered.

Both connectors now supply a pre-download checksum (`md5Checksum`, `quickXorHash`). Google-native
exports do not — an export is generated on demand and has no stable source hash — so those copy
unconditionally and are deduplicated after the fact by the hash of the exported bytes.

> **A stale comment to fix on the way past.** `api/blob.py:147` still reads "SharePoint and local
> sources carry no pre-download checksum today", which was true when the checksum key was added
> and is not now: `_sp_classify_item` populates `quickXorHash` (`api/scanner.py:204`, `:1562`).
> Anyone sizing this work from that comment would conclude SharePoint cannot be checksum-keyed and
> would build a redundant path for it. Left as a note rather than a drive-by edit only because
> this ADR is design-only; it is a one-line correction.

### 6. Retention applies from day one

Connector-sourced copies fall under the same sweep as workspace uploads
(`content_workspace_retention.run_content_workspace_retention_sweep`, already wired into the
`start_workers` sweeper thread). `blob.purge_scan`'s right-to-erasure path must be extended to the
workspace container, including the checksum-shared entries.

Stated plainly because it is the part that is easy to defer and expensive to have deferred: this
change means ACP holds copies of a hospital's documents. Without a retention sweep on day one,
what we have built is an un-expiring PHI store. It is not acceptable for the retention story to
lag the copy story by even one release.

### 7. Verify at the boundary

The copy is the first point where ACP has the bytes at rest and control over what happens next, so
it is where verification belongs: re-read the written blob and compare its hash before marking the
version usable, and leave an explicit hook for a malware scan between "written" and "assessable".
A version that fails verification is never analysed.

## Consequences

**What gets better.** Assess and Remediate stop holding user credentials — a worker restart, a
long queue, or an expired token can no longer orphan work in progress. Retries are free and local.
An assessment names the exact bytes it ran on. There is one place to look for "what did we
analyse", and one place to delete from.

**What this costs, stated honestly:**

- **We now store customer content.** The prior position — "we only read your files" — becomes "we
  copy them into a private container in your own Azure subscription". That is a customer-facing
  commitment change, not only an engineering one, and it needs to be said before it ships rather
  than discovered in a security review.
- **Storage grows with the assessed estate**, not with findings. Retention policy is what bounds
  it, which is why §6 is not optional.
- **A new hard dependency.** Blob down means Assess cannot run at all, where today it would fall
  back to the connector. That is the intended trade — a fallback is what makes the guarantee
  meaningless — but it is a real reduction in degraded-mode capability and belongs in the runbook.
- **Two source-of-bytes mechanisms during rollout.** The ADR 0020 `sources` cache and this intake
  both exist until stage 4 below removes the first. Two mechanisms that can disagree is exactly
  the drift this repo has been bitten by; the rollout is ordered to keep the window short and the
  precedence unambiguous.

## What this ADR does NOT decide

- **Whether Discover ever copies.** A future "pre-stage the selection while the user reviews it"
  optimisation is compatible with this and is not proposed here.
- **Blob-backed Discover** (ADR 0044 Phase 2's other half): whether a workspace document appears
  in the Discover estate view alongside connector files.
- **Cross-tenant deduplication.** Copies are owner-scoped, as every other boundary in this app is
  (`owner_email` is the tenant identifier — ADR 0044). Sharing identical bytes between owners
  would be a storage win and a tenancy question; it is not in scope.
- **The retention *values*.** `content_workspace_retention`'s own header notes that turning "90
  days" into a date is separate, later work. This ADR requires that connector copies be covered by
  whatever that policy becomes, not what it should say.

## Rollout

Each stage is independently revertable, and none removes a working path before its replacement is
proven — the ordering ADR 0020's own rollout used, for the same reason.

1. **Write-only intake.** Copy at Assess start; nothing reads from it. Assess still downloads as
   it does today. Proves the copy, the version rows, the identity bridge and the verification
   round-trip under real load, with no behaviour change to fall back from.
2. **Read from intake, connector as fallback.** Assess prefers the copy. A miss falls through to
   the connector exactly as the cache does now. The token dependency is still present but should
   now be exercised approximately never — and how often it *is* exercised is the measurement that
   decides whether stage 3 is safe.
3. **Make it authoritative.** Remove the fallback; an intake failure becomes an error row. This is
   the stage that delivers the guarantee, and it should not be taken until stage 2's fallback rate
   is observably ~0.
4. **Retire the `sources` cache.** Once intake is authoritative, `cache_source_bytes` /
   `read_cached_source` have no remaining callers. Remove them and the `sources` container rather
   than leaving a second mechanism nobody maintains.

Retention (§6) ships with stage 1, not stage 3. The moment the first byte is copied is the moment
the sweep needs to exist.

## Alternatives considered

**Make the existing `sources` cache eager instead.** Populate it at Discover, keep everything else.
Cheaper, and it reuses shipped code — but it copies the entire estate rather than the selected
subset, it inherits a cache's best-effort contract (so the guarantee still cannot be stated), and
it leaves document identity unanswered, which is the part that is expensive to unwind later.

**Copy at Discover into the workspace layout.** Solves drift most completely, since bytes are
captured at the moment the metadata is. Rejected because it undoes the metadata-only property that
makes Discovery fast, and spends storage and connector quota on files nobody selects.

**Per-scan temporary copies with no versioning.** Simplest possible: stage bytes for the duration
of a scan, delete at finalize. Fixes the token problem and nothing else — no drift record, no
reuse across scans, and remediation still needs a separate output store.
