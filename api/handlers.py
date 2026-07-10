"""Job handlers for the durable async queue (ADR 0004).

Registered with the worker by importing this module (see core.start_workers).
Each handler runs one job to completion; raising re-queues it with backoff,
raising FatalJobError dead-letters it.

Current handlers:
  scan            — run a full scan asynchronously (durable + retryable), persist
                    results, emit per-file/per-rule Langfuse spans, finalize.

Per-file parallelism is intentionally NOT used here: the .NET Office analyser
processes a directory in one batch, so the natural durable unit is one scan job.
Per-file fan-out (PDF/HTML) is a possible future optimization (ADR 0004 step 3).
"""
from __future__ import annotations

import core
import provenance
from worker import handler, FatalJobError
from scanner import run_scan
from remediate import remediate_html


def _drive_client(token: str):
    """Drive client for a worker (no request), from a bare GIS access token.

    NO expiry is set, and that is the point. google-auth attempts a refresh only when
    `credentials.expired` is True, and `expired` is False whenever `expiry` is None — so a
    credential with no expiry is sent as-is, forever. This used to set `expiry = now + 1h`
    under a comment claiming it PREVENTED the refresh; it caused it. Once that hour passed
    (a job queued behind a backlog, a long remediation), `expired` flipped True, google-auth
    called refresh(), and a GIS token has no refresh_token/client_id/client_secret — so the
    job died on "The credentials do not contain the necessary fields need to refresh the
    access token", five retries deep, against a failure nothing could fix.

    A GIS implicit-flow token genuinely cannot be refreshed. When it has really expired Drive
    answers 401, and worker.drive_session_expired turns that into one actionable dead-letter.
    Outliving the token needs a refresh token (the auth-code flow) — an auth change that wants
    an ADR, not a fabricated expiry."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=token, scopes=core.DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def ensure_remediated_folder(svc) -> str:
    """Find-or-create the configured Drive mirror folder (default 'Remediated',
    admin-configurable — see core.store.get_drive_mirror_folder). If legacy
    duplicates exist, picks the oldest deterministically. Call this ONCE per
    remediate batch (in the request handler) and pass the id to the jobs — calling
    it concurrently from many workers is what created duplicate folders."""
    name = core.store.get_drive_mirror_folder()
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = svc.files().list(q=q, fields="files(id)", orderBy="createdTime",
                               pageSize=1).execute().get("files", [])
    if folders:
        return folders[0]["id"]
    return svc.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]


@handler("scan")
def _scan(payload: dict, job: dict) -> None:
    """Run a scan to completion: discover → analyse → score → persist → finalize.

    payload: {source, scan_id, folder?, sp?, ai}
    The Drive/SharePoint tokens are looked up from the in-memory registry by
    scan_id (never carried in the job payload / Postgres)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    if not scan_id:
        raise FatalJobError("scan job missing scan_id")
    source = payload.get("source", "local")
    ai = bool(payload.get("ai", True))
    effective_ai = ai and core.store.get_ai_enabled()
    toks = core.get_scan_tokens(scan_id)

    report = run_scan(
        source,
        drive_token=toks.get("drive"),
        sp_token=toks.get("sp"),
        folder=payload.get("folder"),
        ai_enabled=effective_ai,
        scan_id=scan_id,
        user=payload.get("user"),
        detect_pii=payload.get("pii", True),
        exclude_remediated=bool(payload.get("exclude_remediated", False)),
    )
    core.store.save_scan(report)
    core.finalize_scan(scan_id, effective_ai, source)
    core.clear_scan_tokens(scan_id)


def _phase(job: dict, msg: str) -> None:
    """Report what this job is doing right now — the queue panel's per-row line reads it.

    Only ever called where the job genuinely changes activity, so the line stays true. Never
    raises: progress reporting must not be able to fail the work it reports on.
    """
    jid = (job or {}).get("id")
    if jid:
        core.store.set_job_phase(jid, msg)


def _verify_residual_scs(fixed_bytes: bytes, filename: str):
    """Re-scan the remediated bytes; return the set of WCAG SCs STILL failing, so a reported
    fix that did not actually clear is never credited. Delegates to the single shared
    implementation in api/proposals.py — the proposal lane and this loop must use the exact
    same residual re-scan (one whole-file path, never a divergent copy)."""
    from proposals import verify_residual_scs
    return verify_residual_scs(fixed_bytes, filename)


def _propose_text_findings(scan_id: str, filename: str, file_bytes: bytes, ai_enabled: bool) -> None:
    """Format-agnostic text proposers (WCAG 3.1.2 language-of-parts + 1.3.3 sensory rewrite).
    Both self-gate: they yield proposals ONLY when the document actually mixes languages /
    carries a sensory instruction, so this is safe to run on every remediated file. Runs on
    the extracted text (same source as the scan-time detectors), enqueues prefilled one-click
    values onto the file's HITL rows, and never fails the remediation job."""
    try:
        import tempfile
        from pathlib import Path as _P
        import pii as _pii
        import proposals as _prop
        with tempfile.TemporaryDirectory(prefix="acp-textprop-") as _d:
            p = _P(_d) / filename
            p.write_bytes(file_bytes)
            text = _pii.extract_text(p)
    except Exception:
        return
    if not text:
        return
    try:
        _enqueue_proposals(scan_id, filename, "3.1.2", "Language of Parts",
                           _prop.propose_language_parts(text))
    except Exception:
        pass
    try:
        _enqueue_proposals(scan_id, filename, "1.3.3", "Sensory Characteristics",
                           _prop.propose_sensory_rewrite(text, filename=filename, ai_enabled=ai_enabled))
    except Exception:
        pass


def _record_applied_fixes(scan_id: str, filename: str, fixes: list) -> None:
    """Persist the concrete values the AI actually wrote — the alt text and the picture it
    was written for — so "Recent AI fixes" and the certification evidence show what really
    happened, per format, identically.

    Every remediator emits the same row shape: {rule_id, value, source, thumb}. `seq` orders
    them within a (scan, file, rule) so several figures on one criterion each keep a row —
    the table's primary key is (scan_id, file, rule_id, seq).

    Best-effort per row: a telemetry failure must never fail the remediation job, and one bad
    row must not discard the rest."""
    for i, fx in enumerate(fixes or []):
        try:
            core.store.record_applied_fix(
                scan_id, filename, fx["rule_id"], fx["value"],
                source=fx.get("source"), thumb=fx.get("thumb"), seq=i)
        except Exception:
            pass


def _enqueue_proposals(scan_id: str, filename: str, sc: str, rule_name: str,
                       proposals: list, *, validated: bool = False) -> None:
    """Best-effort: attach AI-proposed (not auto-applied) fix values to the file's HITL row
    for this SC, so the reviewer approves a prefilled value in one click. Never fails the
    remediation job — a telemetry/queue error just means the finding routes as a plain
    deferral. `validated` stays False for model/heuristic proposals (a machine guess a human
    confirms), so confidence.js surfaces them as Medium/Low, never a trusted 'fixed'."""
    if not proposals:
        return
    try:
        core.store.enqueue_proposals(scan_id, filename, sc, proposals,
                                     validated=validated, rule_name=rule_name)
    except Exception:
        pass


@handler("remediate_file")
def _remediate_file(payload: dict, job: dict) -> None:
    """Apply server-side remediation to one file and write the fixed copy to Drive.

    payload: {scan_id, file, drive_file_id}
    HTML files are remediated deterministically (ADR 0005); other types are routed
    to human review (no in-repo Office/PDF remediator yet)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    filename = payload.get("file")
    drive_file_id = payload.get("drive_file_id")
    if not (scan_id and filename and drive_file_id):
        raise FatalJobError("remediate_file job missing scan_id/file/drive_file_id")

    _OFFICE_MIME = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("html", "htm", "pdf", *_OFFICE_MIME):
        # No server-side remediator for this type → human review.
        core.store.log_decision("system", "remediate.deferred", scan_id=scan_id,
                                file=filename, detail=f"no server-side remediator for .{ext}")
        return

    # Prefer the token carried in the durable job payload: the in-memory scan-token
    # store is per-replica and is wiped by a restart/redeploy, so a durable remediate
    # job that later runs on another replica (or after a restart) would otherwise fail
    # with "no Drive token". The payload token survives both; fall back to in-memory.
    token = payload.get("drive_token") or core.get_scan_tokens(scan_id).get("drive")
    if not token:
        raise FatalJobError("no Drive token for this scan (expired/restarted) — re-trigger")

    _phase(job, f"downloading {filename}")
    svc = _drive_client(token)
    data = svc.files().get_media(fileId=drive_file_id).execute()

    # Format-agnostic text proposers (3.1.2 language-of-parts + 1.3.3 sensory rewrite) run on
    # the original bytes — the prose these check is unchanged by remediation, and running
    # here (not after the format branch) means they still surface even when a file has no
    # deterministic fixes and would hit the no-fixes early return below. Both self-gate.
    _propose_text_findings(scan_id, filename, data, core.store.get_ai_enabled())

    # Per-fix before→after evidence for the certification report's "Before → After"
    # section. Each remediator appends {rule_id (SC), before, after, note}; we persist
    # only the ones that verifiably cleared on the post-fix re-scan (below).
    rem_diffs: list[dict] = []

    # AI-proposed one-click values applied/drafted inline during remediation (e.g. 2.4.4
    # link text). Collected here so they can be enqueued AFTER the residual re-scan below,
    # with an honest `validated` flag (True only when the applied fix actually cleared).
    inline_proposals: list[dict] = []

    _phase(job, f"applying fixes to {filename}")
    if ext in ("html", "htm"):
        fixed_html, applied, _deferred = remediate_html(
            data.decode("utf-8", errors="replace"),
            ai_enabled=core.store.get_ai_enabled(), diffs=rem_diffs,
            proposals=inline_proposals)
        fixed_bytes = fixed_html.encode("utf-8")
        mimetype = "text/html"
    else:  # pdf / office — file-based deterministic remediators (ADR 0005 step 4)
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory(prefix="acp-rem-") as _d:
            src = _Path(_d) / filename
            src.write_bytes(data)
            if ext == "pdf":
                from remediate_pdf import remediate_pdf
                _pdf_proposals: list = []
                _applied_fixes: list = []
                out_path, applied, _skipped = remediate_pdf(
                    src, ai_enabled=core.store.get_ai_enabled(), scan_id=scan_id,
                    diffs=rem_diffs, proposals=_pdf_proposals, applied_fixes=_applied_fixes)
                mimetype = "application/pdf"
                # A PDF's AI-written alt text is evidence exactly like an Office document's.
                # It used to be dropped: remediate_pdf returned only prose, so no row reached
                # applied_fixes and the certification record showed the fix had never happened.
                _record_applied_fixes(scan_id, filename, _applied_fixes)
                # 1.3.2 reading-order vision proposal (untagged/scanned PDF) — surfaced for
                # one-click confirm, never auto-applied. Before the no-fixes early return.
                _enqueue_proposals(scan_id, filename, "1.3.2", "Meaningful Sequence", _pdf_proposals)
            else:  # docx / pptx / xlsx
                from remediate_office import remediate_office
                _applied_fixes: list = []
                _proposals: list = []
                _evidence: list = []
                out_path, applied, _skipped = remediate_office(
                    src, ai_enabled=core.store.get_ai_enabled(), scan_id=scan_id,
                    applied_fixes=_applied_fixes, proposals=_proposals,
                    evidence=_evidence, diffs=rem_diffs)
                mimetype = _OFFICE_MIME[ext]
                _record_applied_fixes(scan_id, filename, _applied_fixes)
                # AI-proposed (but not auto-applied) alt: an ungrounded vision guess is
                # surfaced for one-click approval rather than silently written (WCAG 1.1.1
                # intent stays human). Attach the prefilled drafts to the file's 1.1.1 HITL
                # row — before the no-fixes early return, or they die inside the job result.
                _enqueue_proposals(scan_id, filename, "1.1.1", "Non-text Content", _proposals)
                # Deferred alt text (no faithful source — see remediate_office) must
                # reach a human: those findings are fix_mode 'auto', so the ai-assisted
                # HITL pull never sees them. Queue here — before the no-fixes early
                # return below — or the deferral dies inside the job result.
                for _msg in _skipped:
                    if "faithful alt source" in _msg:
                        try:
                            _n = int(_msg.split(" ", 1)[0])
                        except ValueError:
                            _n = 1
                        try:
                            core.store.queue_hitl_deferral(scan_id, filename, _msg, _n)
                        except Exception:
                            pass
                # Attach the deferred images to whichever 1.1.1 row now exists — the
                # deferral queued just above, or the proposals row. Last, because there is
                # nothing to attach to until one of them has been created.
                try:
                    core.store.attach_hitl_evidence(scan_id, filename, "1.1.1", _evidence)
                except Exception:
                    pass   # evidence is a nicety; never fail a remediation job for a thumbnail
            if not out_path or not _Path(out_path).exists():
                core.store.log_decision("system", "remediate.deferred", scan_id=scan_id,
                                        file=filename, detail=f".{ext}: no deterministic fixes applied")
                return
            fixed_bytes = _Path(out_path).read_bytes()

    # ADR 0010: Blob is now the PRIMARY, must-succeed write -- no per-user token needed
    # (managed identity), so this no longer hard-fails for orgs that only granted
    # read-only Drive access. Drive becomes a best-effort MIRROR below: failure there no
    # longer fails the whole remediation, since Blob already has the durable copy.
    import blob as _blob
    _phase(job, "storing the corrected copy")
    owner = (core.store.get_scan(scan_id) or {}).get("run", {}).get("owner_email")
    blob_url = _blob.upload_remediated(owner, scan_id, filename, fixed_bytes, mimetype)

    web_url = None
    if core.store.get_drive_mirror_enabled():
        _phase(job, "writing the corrected copy to Drive")
        import io
        from googleapiclient.http import MediaIoBaseUpload
        from googleapiclient.errors import HttpError
        try:
            # Folder id is created once per batch in the endpoint and passed in, so
            # concurrent workers don't each create their own mirror folder.
            # Fall back to find-or-create for a standalone job.
            folder_id = payload.get("remediated_folder_id") or ensure_remediated_folder(svc)
            media = MediaIoBaseUpload(io.BytesIO(fixed_bytes), mimetype=mimetype, resumable=False)
            # Upsert: update an existing fixed copy rather than piling up duplicates on re-run.
            safe = filename.replace("\\", "\\\\").replace("'", "\\'")
            existing = svc.files().list(
                q=f"name='{safe}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)", pageSize=1).execute().get("files", [])
            # Stamp ACP's own output so a later scan skips it by provenance rather than by
            # which folder it happens to live in (api/provenance.py).
            props = provenance.stamp(filename)
            # Ask Drive to echo `properties` back. A stamp that does not round-trip is invisible
            # to the next scan's provenance filter, which then re-ingests ACP's own output as if
            # it were a source document. That has been the observed state — every discovery logs
            # "0 skipped as ACP-generated output" — and nothing told us whether the write set the
            # property, or the read never saw it. Now the write says so, once, at the moment of
            # truth. Diagnostic only: a missing stamp never fails the mirror (the in-document
            # content stamp still catches the copy).
            if existing:
                _mode = "updated"
                result = svc.files().update(fileId=existing[0]["id"], media_body=media,
                                            body={"properties": props},
                                            fields="id,webViewLink,properties").execute()
            else:
                _mode = "created"
                result = svc.files().create(body={"name": filename, "parents": [folder_id],
                                                  "properties": props},
                                            media_body=media,
                                            fields="id,webViewLink,properties").execute()
            web_url = result.get("webViewLink", "")
            # ALWAYS one greppable line, stamped or not. Silence used to be ambiguous: this
            # branch only spoke up on failure, so "no stamp line in the logs" meant either the
            # stamp round-tripped, or the mirror never ran at all — and on the day it mattered
            # it was the second. A log that only reports failure cannot tell you a thing about
            # a system that is quiet.
            _stamped = provenance.is_acp_generated(result)
            print(f"[remediate] drive mirror: {filename} {_mode} id={result.get('id')} "
                  f"stamp={'persisted' if _stamped else 'MISSING'} "
                  f"properties={result.get('properties')!r}", flush=True)
            if not _stamped:
                # The audit trail records only the anomaly — one row per unstamped copy, not a
                # row per successful write. Diagnostic: a missing stamp never fails the mirror
                # (Blob holds the durable copy; the in-document content stamp still catches it).
                _detail = (f"Drive did not echo the ACP provenance stamp on {filename} "
                           f"(got properties={result.get('properties')!r}); the next scan will "
                           f"not skip this copy by provenance")
                core.store.log_decision("system", "remediate.stamp_not_persisted",
                                        scan_id=scan_id, file=filename, detail=_detail[:200])
        except HttpError as e:
            # A 403 here means the user's Drive grant lacks write access (drive.file) --
            # no longer fatal now that Blob has the durable copy; log and move on.
            reason = ("Drive write denied (403) — the signed-in user hasn't granted write "
                     "access (drive.file)." if getattr(e, "resp", None) is not None and e.resp.status == 403
                     else f"Drive mirror failed: {type(e).__name__}: {e}")
            # To stdout as well as the decisions table: a mirror failure recorded only in the
            # database is invisible to anyone reading logs, which is where you look first.
            print(f"[remediate] drive mirror: {filename} FAILED — {reason}", flush=True)
            core.store.log_decision("system", "remediate.drive_mirror_failed", scan_id=scan_id,
                                    file=filename, detail=reason[:200])
        except Exception as e:
            print(f"[remediate] drive mirror: {filename} FAILED — "
                  f"{type(e).__name__}: {e}", flush=True)
            core.store.log_decision("system", "remediate.drive_mirror_failed", scan_id=scan_id,
                                    file=filename, detail=f"{type(e).__name__}: {e}"[:200])
    else:
        # The third silence: with the mirror switched off nothing was written and nothing was
        # said, so "no mirror line" could also mean "the operator turned it off". Say it.
        print(f"[remediate] drive mirror: {filename} skipped — disabled "
              f"(settings.drive_mirror_enabled=false)", flush=True)

    core.store.record_remediation(scan_id, filename, drive_write_url=web_url, blob_url=blob_url)
    core.emit_remediation_span(scan_id, filename, drive_write_url=web_url)
    core.store.log_decision("system", "remediate.applied", scan_id=scan_id, file=filename,
                            detail="; ".join(applied) or "no auto fixes needed")
    # ADR 0003 Phase 2: mark this file's deterministically-auto-fixable violations
    # complete -- but VERIFY first. Some criteria (docx/pdf language & title) report
    # 'applied' yet do not clear on re-scan (metadata is written, but the engine reads
    # a field it does not touch). Re-scan the fixed bytes and only credit criteria that
    # ACTUALLY cleared; the rest stay failing for review, so the app never shows a fix
    # that did not take.
    _phase(job, "re-verifying the corrected copy")
    residual = _verify_residual_scs(fixed_bytes, filename)
    # Enqueue the inline AI proposals (2.4.4 link text …) now that the re-scan has run, so a
    # deterministic fix that verifiably cleared carries validated=True (confidence.js reads
    # it as a High, one-click confirm) while a fix still failing / a model draft stays
    # unvalidated (Medium). Group per SC — one HITL row per (file, sc).
    if inline_proposals:
        _by_sc: dict[str, list] = {}
        for _p in inline_proposals:
            _by_sc.setdefault(_p.get("sc", ""), []).append(_p)
        _PROPOSAL_RULE_NAMES = {"2.4.4": "Link Purpose (In Context)",
                                "2.4.6": "Headings and Labels", "1.3.1": "Info and Relationships"}
        for _sc, _ps in _by_sc.items():
            if not _sc:
                continue
            _applied_any = any(p.get("applied") for p in _ps)
            _cleared = residual is not None and _sc not in residual
            _enqueue_proposals(scan_id, filename, _sc, _PROPOSAL_RULE_NAMES.get(_sc, _sc),
                               [{k: v for k, v in p.items() if k not in ("sc", "applied")} for p in _ps],
                               validated=bool(_applied_any and _cleared))
    # Truthfulness gate: keep a before→after record only when its criterion is NOT still
    # failing on the re-scan (or when the re-scan could not run — same "credit it" posture
    # as remediation_state below). A fix that did not actually clear never reaches the PDF.
    try:
        verified_diffs = [d for d in rem_diffs
                          if residual is None or d.get("rule_id") not in residual]
        core.store.record_remediation_diffs(scan_id, filename, verified_diffs)
    except Exception:
        pass
    try:
        from documents import resolve_doc_id
        doc_id = resolve_doc_id("drive", drive_file_id, filename, None)
        auto_rules = core.store.list_auto_fail_rules(scan_id, filename)
        cleared: set[str] = set()   # rule_ids this run verifiably auto-cleared
        kept = []
        for rule_id in auto_rules:
            if residual is not None and rule_id in residual:
                kept.append(rule_id)                       # reported fix did not clear -> leave failing
                continue
            core.store.upsert_remediation_state(doc_id, rule_id, "complete", scan_id)
            cleared.add(rule_id)
        if residual is not None and kept:
            core.store.log_decision("system", "remediate.unverified", scan_id=scan_id, file=filename,
                                    detail=f"{len(cleared)} verified cleared; {len(kept)} reported-fixed but still failing on re-scan (kept for review): {', '.join(sorted(kept))}")
        # Tie the HITL review queue to the remediate action. Every FAILing finding this run
        # did NOT verifiably auto-clear — contrast sign-off, link purpose, structure, or an
        # auto fix that didn't take — must reach a human here, or it silently vanishes: the
        # mount-time queue_hitl_items pull only sees fix_mode='ai-assisted', so a stuck
        # fix_mode='auto' finding never routes to anyone, the reviewer has nothing to
        # approve, and the file can never re-validate to compliant (Publish stays empty).
        # A fully-cleared file still gets ONE verification item (user decision 2026-07-02)
        # so no unreviewed fix reaches Publish on trust alone.
        review_rules = [
            {"rule_id": r["rule_id"], "rule_name": r.get("rule_name"),
             "finding_count": r.get("finding_count")}
            for r in core.store.get_scan_traces(scan_id, file=filename)
            if r.get("outcome") == "FAIL" and r["rule_id"] not in cleared
        ]
        if review_rules:
            queued = core.store.queue_hitl_review_for_file(scan_id, filename, review_rules)
            if queued:
                core.fire_webhook(queued)
                core.store.log_decision("system", "hitl.review_routed", scan_id=scan_id, file=filename,
                                        detail=f"{len(queued)} finding(s) routed to human review after remediation")
        else:
            core.store.queue_hitl_deferral(scan_id, filename,
                                           "Automatic fix applied — verify the result", 1,
                                           rule_id="auto/verify")
    except Exception:
        pass


# ── Fan-out scan pipeline (ADR 0007): discover → scan_file → finalize ─────────
import datetime as _dt
import shutil as _shutil
import tempfile as _tempfile
from pathlib import Path as _Path


@handler("scan_discover")
def _scan_discover(payload: dict, job: dict) -> None:
    """List the source (paginated, no cap), create the scan_runs row, and enqueue one
    scan_file job per file. Each file's Langfuse trace is opened later, per file, by
    _analyse_and_persist_one — not here."""
    from rubric import Rubric
    from scanner import (_list, _drive_service, ACP, FANOUT_MAX_FILES, SCAN_BATCH_SIZE,
                         SCAN_BATCH_THRESHOLD)
    scan_id = payload.get("scan_id") or job.get("scan_id")
    source = payload.get("source", "drive")
    ai = bool(payload.get("ai", True)) and core.store.get_ai_enabled()
    pii = bool(payload.get("pii", True))
    user = payload.get("user")
    folder = payload.get("folder")
    toks = core.get_scan_tokens(scan_id)
    rb = Rubric.load_active(ACP / "config")
    svc = None if source in ("local", "sharepoint") else _drive_service(toks.get("drive"))
    effective_folder = folder if folder else ("root" if toks.get("drive") else None)
    items = _list(source, svc, folder=effective_folder, sp_token=toks.get("sp"),
                  max_files=FANOUT_MAX_FILES,
                  exclude_remediated=bool(payload.get("exclude_remediated", False)))
    # Which discovered files share a logical name with another? Only those can be ACP's own
    # output SHADOWING a source document. A stamped file standing alone under its own name is
    # a certified document published back into the estate — it must still be scanned.
    # The content stamp needs the bytes, so the final call happens per-file in scan_file; this
    # just tells that job whether the question is even worth asking.
    from store import logical_name as _logical_name
    _name_counts: dict[str, int] = {}
    for _it in items:
        _name_counts[_logical_name(_it["name"])] = _name_counts.get(_logical_name(_it["name"]), 0) + 1
    _exclude_rem = bool(payload.get("exclude_remediated", False))

    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    core.store.init_scan_run(scan_id, source, len(items), started, rb.name, rb.hash, owner=user)
    if not items:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source, "ai": ai, "pii": pii}, scan_id=scan_id)
        return
    # ADR 0008: very large estates fan out as batches (N files / job) instead of one job
    # per file — far less queue churn + claim contention. Per-file stays the proven default
    # below the threshold; an explicit batch=true forces the batch path. The persisted
    # results and Langfuse traces are identical either way — only job granularity changes.
    # No more per-document span cap here: file-centric tracing (lf.file_trace) gives every
    # file its OWN trace, so there's no single big trace whose span count could break the
    # Langfuse OSS detail view — the old SCAN_TRACE_SPAN_CAP problem this guarded against.
    use_batch = bool(payload.get("batch")) or len(items) >= SCAN_BATCH_THRESHOLD
    if use_batch:
        for i in range(0, len(items), SCAN_BATCH_SIZE):
            chunk = items[i:i + SCAN_BATCH_SIZE]
            core.store.enqueue_job("scan_batch", {
                "scan_id": scan_id, "source": source, "ai": ai, "pii": pii, "user": user,
                "incremental": bool(payload.get("incremental", True)),
                "items": [{"file": it["name"], "drive_file_id": it.get("id"),
                           "mime": it.get("mime"), "path": it.get("path"),
                           "checksum": it.get("checksum"),
                           "shadow_candidate": _name_counts[_logical_name(it["name"])] > 1,
                           "exclude_remediated": _exclude_rem} for it in chunk],
            }, scan_id=scan_id)
    else:
        for it in items:
            core.store.enqueue_job("scan_file", {
                "scan_id": scan_id, "source": source, "file": it["name"],
                "drive_file_id": it.get("id"), "mime": it.get("mime"), "path": it.get("path"),
                "checksum": it.get("checksum"),
                "shadow_candidate": _name_counts[_logical_name(it["name"])] > 1,
                "exclude_remediated": _exclude_rem,
                "ai": ai, "pii": pii, "user": user,
                "incremental": bool(payload.get("incremental", True))}, scan_id=scan_id)


def _analyse_and_persist_one(scan_id, item, source, pii, svc, toks, now, _lf, user=None,
                             rubric_hash=None, incremental=True) -> None:
    """Download + analyse + assess + persist ONE file and emit its Discover span on that
    file's own Langfuse trace. Shared by scan_file (per-file fan-out) and scan_batch
    (ADR 0008). A
    fetch/analyse failure is recorded as an 'error' file so the scan still finalizes."""
    from scanner import _download, analyse_and_assess
    name = item["file"]
    checksum = item.get("checksum")
    drive_file_id = item.get("drive_file_id")
    dedup_of = None
    reused_from_scan = None
    # Checksum dedup: a byte-identical copy of a file already analysed earlier in THIS
    # scan (e.g. the same PDF uploaded to two folders under different names) — skip the
    # download + engine analysis + PII extraction entirely and copy the prior result
    # forward under this file's own name/id. Scoped to one scan_id only.
    dedup = core.store.find_by_checksum(scan_id, checksum) if checksum else None
    # ADR 0011: reuse ACROSS scans when within-scan dedup didn't match. Gated on the
    # same owner + drive_file_id + checksum + rubric_hash (see find_prior_analysis).
    if not dedup and incremental:
        dedup = core.store.find_prior_analysis(user, drive_file_id, checksum, rubric_hash)
    tmp = _Path(_tempfile.mkdtemp(prefix="acp-scanone-"))
    fdict = pinfo = None
    try:
        if dedup:
            dedup_of = dedup.pop("dedup_of", None)
            reused_from_scan = dedup.pop("reused_from_scan", None)
            pinfo = dedup.pop("pii")
            fdict = {"file": name, **dedup}
            if reused_from_scan and pinfo and pinfo.get("total"):
                # PII carries more sensitivity than a WCAG score -- copying it forward
                # gets its own audit entry rather than a silent inherit (ADR 0011).
                core.store.log_decision("system", "pii.copied_forward", scan_id=scan_id, file=name,
                                        detail=f"from scan {reused_from_scan}: {pinfo['total']} item(s)")
        else:
            try:
                it = {"name": name, "id": item.get("drive_file_id")}
                if item.get("mime"):
                    it["mime"] = item["mime"]
                if item.get("path"):                       # local source — read from disk
                    it["path"] = item["path"]
                _download(it, tmp, svc, sp_token=toks.get("sp"))
                # Stop BEFORE the expensive analysis. This file shares its logical name with
                # another discovered file and carries ACP's in-document stamp, so it is our own
                # remediated copy shadowing its source. Scanning it ran the Office/PDF engine,
                # the PII pass and the AI pass, then produced a phantom document, a phantom
                # duplicate, and a HITL item asking a reviewer to approve alt text for ACP's own
                # output. detect_acp_stamp only reads the document's properties — cheap.
                #
                # A row is still persisted: count_files_done() counts file_records rows against
                # scan_runs.files, so a missing row would leave the scan permanently unfinalized.
                # It carries acp_stamped, so get_scan's shadow filter hides it from every reader,
                # and it has no issues -> no scan_rule_traces -> it never reaches the HITL queue.
                if item.get("shadow_candidate") and item.get("exclude_remediated"):
                    from scanner import detect_acp_stamp
                    stamp = detect_acp_stamp(tmp / name, _Path(name).suffix.lower())
                    if stamp:
                        print(f"[scan] skipping {name}: ACP-generated output shadowing its "
                              f"source (not analysed, not queued for review)", flush=True)
                        fdict = {"file": name, "engine": "n/a", "status": "skipped",
                                 "score": None, "compliant": 0, "skipped_rules": 0,
                                 "issues": [], "acp_stamped": stamp}
                        pinfo = None
                if fdict is None:
                    fdict, pinfo = analyse_and_assess(tmp, name, detect_pii=pii)
            except Exception as e:
                # Classify Drive auth expiry distinctly: GIS access tokens live ~1h and
                # cannot be refreshed server-side, so on a long scan every remaining file
                # fails with 401. A clear reason (instead of a generic error) tells the
                # user exactly what happened and that a re-scan after signing in fixes it.
                _msg = f"{type(e).__name__}: {e}"
                if "401" in _msg or "Invalid Credentials" in _msg or "authError" in _msg:
                    _msg = ("Drive authorization expired mid-scan — sign in again and "
                            "re-run the scan to cover this file")
                core.store.log_decision("system", "scan.file_error", scan_id=scan_id, file=name,
                                        detail=_msg[:200])
        # Both branches converge here. The pre-analysis skip above only runs on a FRESH
        # analysis; with incremental=true, find_prior_analysis() reuses the previous scan's
        # record and short-circuits the whole download+analyse block — so the phantom sailed
        # straight through with all its issues, wrote scan_rule_traces, and landed back in the
        # human review queue. Observed live: get_scan hid it 2s after discovery, and no
        # "skipping" line was ever printed.
        #
        # The reused record carries acp_stamped (that is how get_scan recognises it), so one
        # check here covers reuse, fresh analysis, and any future path that produces an fdict.
        if (item.get("shadow_candidate") and item.get("exclude_remediated")
                and fdict and fdict.get("acp_stamped") and fdict.get("status") != "skipped"):
            print(f"[scan] skipping {name}: ACP-generated output shadowing its source "
                  f"(reused analysis discarded, not queued for review)", flush=True)
            fdict = {"file": name, "engine": "n/a", "status": "skipped", "score": None,
                     "compliant": 0, "skipped_rules": 0, "issues": [],
                     "acp_stamped": fdict.get("acp_stamped")}
            pinfo = None

        if fdict is None:                              # fetch/analyse failed → error record
            fdict = {"file": name, "engine": "n/a", "status": "error", "score": None,
                     "compliant": 0, "skipped_rules": 0, "issues": []}
        fdict["drive_file_id"] = item.get("drive_file_id")
        fdict["checksum"] = checksum
        if pinfo:
            fdict["pii"] = pinfo
        core.store.save_file_result(scan_id, fdict, now)
        # Document-centric layer (ADR 0003, Phase 1): every scan upserts the long-lived
        # document row (api/documents.py), independent of file_records' per-scan snapshot.
        # Defensively wrapped -- must never break the scan pipeline itself, only lose this
        # layer for that one file (same posture as the file-centric tracing right below).
        try:
            from documents import resolve_doc_id, compute_triage_score
            doc_id = resolve_doc_id(source, item.get("drive_file_id"), name, checksum)
            prior = core.store.get_document(doc_id)
            created_at = (prior or {}).get("created_at") or now
            age_days = ((_dt.datetime.fromisoformat(now) - _dt.datetime.fromisoformat(created_at)).days
                       if prior and prior.get("created_at") else None)
            tscore, rationale = compute_triage_score(
                compliance_score=fdict.get("score"), pii_severity=(pinfo or {}).get("severity"),
                pii_total=(pinfo or {}).get("total", 0), age_days=age_days,
                skipped_rules=fdict.get("skipped_rules", 0))
            core.store.upsert_document(doc_id, source=source, path=name, content_hash=checksum,
                                       owner=user, created_at=created_at, last_seen=now,
                                       triage_score=tscore, triage_rationale=rationale)
        except Exception:
            pass
        # File-centric tracing (see lf.file_trace): each file gets its own trace, so unlike
        # the old shared-trace model there's no "too many spans on one trace" risk to cap —
        # always emit, regardless of deep-scan setting (the PII sub-span stays conditional).
        ftrace = _lf.file_trace(scan_id, name, user=user)
        dspan = _lf.discover_span(ftrace, fdict["engine"])
        if pii and pinfo and pinfo.get("total"):
            _lf.pii_span(dspan, pinfo, filename=name)
        dspan.end(output={"engine": fdict["engine"], "sensitive_data": (pinfo or {}).get("total", 0),
                          **({"duplicate_of": dedup_of} if dedup_of else {}),
                          **({"reused_from_scan": reused_from_scan} if reused_from_scan else {})})
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def _make_svc(source, toks):
    """Build the Drive client once per job, resiliently — a build failure degrades to
    None (downloads then fail per-file into 'error' records) rather than killing the job."""
    from scanner import _drive_service
    if source in ("local", "sharepoint"):
        return None
    try:
        return _drive_service(toks.get("drive"))
    except Exception:
        return None


@handler("scan_batch")
def _scan_batch(payload: dict, job: dict) -> None:
    """Analyse + persist a CHUNK of files in one durable job (ADR 0008), then bump the
    done counter ONCE by the chunk size. Cuts queue churn ~SCAN_BATCH_SIZE× on large
    estates; the job that completes the count enqueues finalize (same trigger as scan_file).
    Idempotent on retry — save_file_result replaces per file, so re-running a chunk is safe."""
    import lf as _lf
    scan_id = payload["scan_id"]
    source = payload.get("source", "drive")
    pii = bool(payload.get("pii", True))
    user = payload.get("user")
    items = payload.get("items", [])
    toks = core.get_scan_tokens(scan_id)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    svc = _make_svc(source, toks)
    rubric_hash = core.active_rubric().hash
    incremental = bool(payload.get("incremental", True))
    for it in items:
        _analyse_and_persist_one(scan_id, it, source, pii, svc, toks, now, _lf, user=user,
                                 rubric_hash=rubric_hash, incremental=incremental)
    _lf.flush()  # send any file spans before the batch job exits
    done, total = core.store.count_files_done(scan_id)   # ADR 0013: count, not a running counter
    if done >= total > 0:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source,
                                "ai": bool(payload.get("ai", True)), "pii": pii}, scan_id=scan_id)


@handler("scan_file")
def _scan_file(payload: dict, job: dict) -> None:
    """Download + analyse + assess + persist ONE file, emit its Langfuse spans, then
    bump the done counter — the job that completes the count enqueues finalize.
    Resilient: a fetch/analyse failure is recorded as an 'error' file so the counter
    always advances and the scan can finalize."""
    import lf as _lf
    scan_id = payload["scan_id"]
    source = payload.get("source", "drive")
    pii = bool(payload.get("pii", True))
    user = payload.get("user")
    toks = core.get_scan_tokens(scan_id)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    svc = _make_svc(source, toks)
    _analyse_and_persist_one(scan_id, payload, source, pii, svc, toks, now, _lf, user=user,
                             rubric_hash=core.active_rubric().hash,
                             incremental=bool(payload.get("incremental", True)))
    _lf.flush()  # send file span before this per-file job exits
    done, total = core.store.count_files_done(scan_id)   # ADR 0013: count, not a running counter
    if done >= total > 0:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source,
                                "ai": bool(payload.get("ai", True)), "pii": pii}, scan_id=scan_id)


@handler("scan_finalize")
def _scan_finalize(payload: dict, job: dict) -> None:
    """Aggregate the per-file results into the scan summary and run the shared post-scan
    step (HITL routing + audit). No scan-wide Langfuse trace to finish anymore — file-
    centric tracing (lf.file_trace) already wrote each file's Discover span as it was
    analysed; this just flushes anything still pending."""
    import lf as _lf
    scan_id = payload["scan_id"]
    source = payload.get("source", "drive")
    ai = bool(payload.get("ai", True)) and core.store.get_ai_enabled()
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    core.store.finalize_scan_run(scan_id, now)
    _lf.flush()
    core.finalize_scan(scan_id, ai, source)
    core.clear_scan_tokens(scan_id)


def ensure_assess_trace(scan_id: str, level: str = "AA") -> None:
    """Write the WCAG assessment to each file's OWN Langfuse trace (file-centric tracing —
    see lf.file_trace): an 'Assess' span per file, with that file's per-rule ✓/✗ outcomes
    as children when scan_rule_traces has them (recorded at scan time), plus the file's own
    compliance score. Idempotent — safe to call repeatedly, Langfuse upserts a trace by id.
    Always emits something for every file (falls back to its stored issues when there's no
    per-rule data, e.g. an older scan) so a 'View trace' chip never 404s. Shared by the
    worker job AND the /scans/{sid}/trace/file/{file} endpoint."""
    import lf as _lf
    from store import RULE_CATALOG
    rows = core.store.get_scan_traces(scan_id)                 # per file + rule
    # A finding blocks conformance when its WCAG level is at or below the target
    # (A ⊆ AA ⊆ AAA), so the score is level-aware — matching the Assess tab.
    RANK = {"A": 1, "AA": 2, "AAA": 3}
    target = RANK.get(str(level).upper(), 2)
    by_file: dict[str, dict] = {}              # file → {rule_id: count} for ALL failures (spans)
    blocking_files: set[str] = set()           # files with a failure at/below the target level
    for r in rows:
        f = r["file"]
        by_file.setdefault(f, {})
        if r["outcome"] == "FAIL":
            by_file[f][r["rule_id"]] = r.get("finding_count") or 1
            if RANK.get((r.get("level") or "A").upper(), 1) <= target:
                blocking_files.add(f)
    res = core.store.get_scan(scan_id)
    owner = (res or {}).get("run", {}).get("owner_email")
    source = (res or {}).get("run", {}).get("source")
    # ADR 0003 Phase 2: seed a 'not_started' remediation_state row for every violation
    # newly seen at Assess time. Only inserts (never overwrites), so a rule still failing
    # on a later scan doesn't reset any progress already made on it.
    from documents import resolve_doc_id
    identities = {r["file"]: r for r in core.store.list_file_identities(scan_id)}
    for f in (res or {}).get("files", []):
        fname = f["file"]
        ftrace = _lf.file_trace(scan_id, fname, user=owner)
        aspan = _lf.assess_span(ftrace, level)
        sc_counts = by_file.get(fname)
        if sc_counts:
            _lf.rule_spans(aspan, sc_counts, RULE_CATALOG, filename=fname, scan_id=scan_id, user=owner)
            conformant = fname not in blocking_files
            ident = identities.get(fname) or {}
            try:
                doc_id = resolve_doc_id(source, ident.get("drive_file_id"), fname, ident.get("checksum"))
                for rule_id in sc_counts:
                    core.store.seed_remediation_state(doc_id, rule_id, scan_id)
            except Exception:
                pass
        else:
            conformant = not bool(f.get("issues"))
        aspan.end(output={"conformant": conformant, "failing_criteria": len(sc_counts or {})})
        _lf.file_score(scan_id, fname, f.get("score"))
    _lf.flush()


@handler("assess_trace")
def _assess_trace(payload: dict, job: dict) -> None:
    """Worker path for the on-demand assessment trace — delegates to the shared
    ensure_assess_trace so the job and the trace-redirect endpoint stay in agreement."""
    ensure_assess_trace(payload["scan_id"], payload.get("level", "AA"))


@handler("rescore_file")
def _rescore_file(payload: dict, job: dict) -> None:
    """Re-download and re-analyse ONE file from an existing scan, then refresh the scan
    aggregate. Called when a user self-remediates a file externally and clicks Re-scan
    to confirm. Tokens are embedded in the payload (scan tokens were cleared at finalize)."""
    import lf as _lf
    scan_id = payload["scan_id"]
    file = payload["file"]
    source = payload.get("source", "drive")
    pii = bool(payload.get("pii", True))
    user = payload.get("user")
    drive_token = payload.get("drive_token")
    from scanner import _drive_service
    svc = None
    if source not in ("local", "sharepoint") and drive_token:
        try:
            svc = _drive_service(drive_token)
        except Exception:
            pass
    toks = {"drive": drive_token} if drive_token else {}
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    file_rec = core.store.get_file_record(scan_id, file) or {}
    item = {
        "file": file,
        "drive_file_id": file_rec.get("drive_file_id"),
        "source": source,
    }
    if source == "local":
        # Reconstruct the corpus path the same way the original scan did.
        import os as _os
        corpus = _os.environ.get("ACP_CORPUS_DIR", "/corpus")
        item["path"] = _os.path.join(corpus, file)
    _analyse_and_persist_one(scan_id, item, source, pii, svc, toks, now, _lf, user=user)
    core.store.refresh_scan_aggregate(scan_id)
    _lf.flush()
