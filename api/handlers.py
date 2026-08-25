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

import json as _json
import os as _os

import core
import provenance
from worker import handler, FatalJobError
from scanner import run_scan


def _defer_analysis_to_assess() -> bool:
    """ADR 0020 — metadata-only discovery is now the DEFAULT. Discover only LISTS the estate
    (metadata, no file opened, nothing downloaded); the download + WCAG analysis run at Assess
    time instead. Read per-call so the behaviour can be overridden by env without a code change:
    set ACP_DEFER_ANALYSIS_TO_ASSESS=0 (or false/no/off) to force the legacy immediate-analysis
    scan that downloads and analyses at Discover time."""
    return _os.environ.get("ACP_DEFER_ANALYSIS_TO_ASSESS", "1").strip().lower() in ("1", "true", "yes", "on")


def _enqueue_analysis(scan_id: str, source: str, items: list[dict], *, ai: bool, pii: bool,
                      user: str | None, incremental: bool, exclude_remediated: bool,
                      force_batch: bool = False) -> None:
    """Fan out the download+analyse work over `items` — one scan_file per file, or scan_batch
    chunks for large estates (ADR 0008). Shared by the immediate scan path and the deferred
    Assess path so both enqueue identical work; the last completing job finalizes (ADR 0013)."""
    from store import logical_name as _logical_name
    from scanner import SCAN_BATCH_SIZE, SCAN_BATCH_THRESHOLD
    # A previous run of THIS scan may have halted on an unusable credential. Both the immediate
    # path and the deferred Assess path come through here, so this is the one place that has to
    # forget it — otherwise fixing the credential and pressing Assess again would short-circuit
    # every file against a stale marker and look like the fix had not worked.
    clear_drive_stop(scan_id)
    if not items:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source, "ai": ai, "pii": pii}, scan_id=scan_id)
        return
    name_counts: dict[str, int] = {}
    for it in items:
        name_counts[_logical_name(it["file"])] = name_counts.get(_logical_name(it["file"]), 0) + 1
    use_batch = force_batch or len(items) >= SCAN_BATCH_THRESHOLD
    if use_batch:
        for i in range(0, len(items), SCAN_BATCH_SIZE):
            chunk = items[i:i + SCAN_BATCH_SIZE]
            core.store.enqueue_job("scan_batch", {
                "scan_id": scan_id, "source": source, "ai": ai, "pii": pii, "user": user,
                "incremental": incremental,
                "items": [{"file": it["file"], "drive_file_id": it.get("drive_file_id"),
                           "mime": it.get("mime"), "path": it.get("path"),
                           "checksum": it.get("checksum"), "drive_id": it.get("drive_id"),
                           "source_modified": it.get("source_modified"),
                           "shadow_candidate": name_counts[_logical_name(it["file"])] > 1,
                           "exclude_remediated": exclude_remediated} for it in chunk],
            }, scan_id=scan_id)
    else:
        for it in items:
            core.store.enqueue_job("scan_file", {
                "scan_id": scan_id, "source": source, "file": it["file"],
                "drive_file_id": it.get("drive_file_id"), "mime": it.get("mime"), "path": it.get("path"),
                "checksum": it.get("checksum"), "drive_id": it.get("drive_id"),
                "source_modified": it.get("source_modified"),
                "shadow_candidate": name_counts[_logical_name(it["file"])] > 1,
                "exclude_remediated": exclude_remediated,
                "ai": ai, "pii": pii, "user": user, "incremental": incremental}, scan_id=scan_id)
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
    """Run a scan: discover → (analyse → score → persist → finalize).

    Metadata-only discovery is the DEFAULT (ADR 0020): this monolithic 'scan' job LISTS the estate
    and STOPS at a 'discovered' run, deferring the download + WCAG analysis to Assess — delegating
    to _scan_discover so it produces the exact same discovered state (inventory + assess_params +
    lifecycle + tracing) as the fan-out path, and the tokens are LEFT registered for that later
    Assess. Only when ACP_DEFER_ANALYSIS_TO_ASSESS=0 (the legacy override) does this download and
    analyse now, in which case it finalizes and clears the tokens here.

    payload: {source, scan_id, folder?, sp?, ai}
    The Drive/SharePoint tokens are looked up from the in-memory registry by
    scan_id (never carried in the job payload / Postgres)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    if not scan_id:
        raise FatalJobError("scan job missing scan_id")
    # Fail closed on a missing source rather than defaulting to 'local'. 'local' scans the bundled
    # test corpus, not the production estate — a source-less job silently defaulting to it produces a
    # small scan that lands as 'latest' and collapses every dashboard/report/selector (the exact
    # fingerprint the production probe caught). The route always sets a source, so this only fires on
    # a malformed/legacy job, where a loud failure beats scanning test files.
    source = payload.get("source")
    if not source:
        raise FatalJobError("scan job missing source")
    ai = bool(payload.get("ai", True))
    effective_ai = ai and core.store.get_ai_enabled()

    if _defer_analysis_to_assess():
        # Metadata-only discovery: list + classify from metadata + persist inventory, then STOP.
        # Tokens stay registered so a later Assess can download; do NOT clear them here.
        _scan_discover(payload, job)
        return

    toks = core.get_scan_tokens(scan_id)

    inv: list = []
    report = run_scan(
        source,
        drive_token=toks.get("drive"),
        sp_token=toks.get("sp"),
        folder=payload.get("folder"),
        **({"folders": payload["folders"]} if payload.get("folders") else {}),
        **({"exclude_folders": payload["exclude_folders"]} if payload.get("exclude_folders") else {}),
        ai_enabled=effective_ai,
        scan_id=scan_id,
        user=payload.get("user"),
        detect_pii=payload.get("pii", False),
        exclude_remediated=bool(payload.get("exclude_remediated", False)),
        inventory_out=inv,
    )
    core.store.save_scan(report)
    # Persist per-file inventory + evaluate archival/deletion rules, as the fanout path does.
    persist_discovery_inventory(scan_id, inv, source, payload.get("user"))
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


def _remediation_scope(filename: str, scan_id: str):
    """The scope in force for THIS SCAN and file, as a `(sc) -> bool` predicate.

    The remediation-side twin of scanner._scoped_for_scoring (#107). That change made the
    `scan_scope` setting gate what gets ASSESSED and SCORED; nothing gated what gets FIXED, so
    a scoped scan still wrote changes into a customer's document for criteria they had
    explicitly excluded — and did it silently, since the resulting diffs were then filtered out
    of the score. Excluding a criterion has to mean ACP leaves it alone, not that ACP edits it
    and declines to mention it.

    PHASE 3a — resolved from THIS scan's FROZEN scope (store.get_scan_scope), not the live global
    `active_scope(core.store)`. This is the actual 3a bug: remediation read the live scope, so
    changing the operator's scope after a scan altered what that OLD scan would remediate while its
    frozen Assess counts stayed put — a Remediate/Assess contradiction. Reading the recorded
    per-scan scope makes remediation honour exactly the boundary the scan was assessed under. A
    legacy scan with nothing recorded → get_scan_scope None → predicate None → nothing gated, the
    same "unscoped behaves as before" contract as ever.

    Returns None when no scope is recorded. The `except` keeps the established fail-open contract
    for THIS predicate specifically: a scope we cannot resolve must not silently become a scope
    that blocks all remediation. (get_scan_scope itself stays fail-loud; this net is the caller's
    choice, not the reader's.)
    """
    try:
        from store import in_scope, _file_format
        scope = core.store.get_scan_scope(scan_id)
        if not scope:
            return None
        fmt = _file_format(filename)
        return lambda sc: in_scope(sc, fmt, scope)
    except Exception:
        # A scope we cannot resolve must not silently become a scope that blocks everything.
        return None


def _verify_residual_scs(fixed_bytes: bytes, filename: str):
    """Re-scan the remediated bytes; return the set of WCAG SCs STILL failing, so a reported
    fix that did not actually clear is never credited. Delegates to the single shared
    implementation in api/proposals.py — the proposal lane and this loop must use the exact
    same residual re-scan (one whole-file path, never a divergent copy)."""
    from proposals import verify_residual_scs
    return verify_residual_scs(fixed_bytes, filename)


def _propose_text_findings(scan_id: str, filename: str, file_bytes: bytes, ai_enabled: bool) -> None:
    """Format-agnostic proposers (WCAG 3.1.2 language-of-parts, 1.3.3 sensory rewrite, and
    1.4.5 images-of-text). All self-gate: they yield proposals ONLY when the document actually
    mixes languages / carries a sensory instruction / bakes text into an image, so this is safe
    to run on every remediated file. The text proposers run on the extracted text (same source
    as the scan-time detectors); the 1.4.5 proposer OCRs the embedded images off the temp path.
    Enqueues prefilled one-click values onto the file's HITL rows, and never fails the job."""
    # ADR 0021 stage 2 — org house-style guidance for the prose drafts. Computed once per file
    # from the scan owner; per-rule. "" (flag off / no rules / any lookup error) leaves every
    # proposer's prompt byte-identical to pre-memory.
    try:
        import memory as _mem
        _org = (core.store.get_scan(scan_id) or {}).get("run", {}).get("owner_email")
        _fmt = filename.rsplit(".", 1)[-1].lower() if "." in filename else None

        def _g(rule):
            return _mem.guidance_for(core.store, _org, rule, _fmt)
    except Exception:
        def _g(rule):
            return ""
    try:
        import tempfile
        from pathlib import Path as _P
        import pii as _pii
        import proposals as _prop
        with tempfile.TemporaryDirectory(prefix="acp-textprop-") as _d:
            p = _P(_d) / filename
            p.write_bytes(file_bytes)
            text = _pii.extract_text(p)
            # 1.4.5 needs the file on disk (it OCRs embedded images), so compute it here while
            # the temp path is alive — and independently of `text`, since an image-only doc
            # carries no extractable text yet still fails 1.4.5.
            image_text = _prop.propose_images_of_text(p, p.suffix)
            # 2.4.4/2.4.9 link-text proposals read the OOXML zip, so same constraint.
            link_props = (_prop.propose_link_texts(p, p.suffix, ai_enabled=ai_enabled, guidance=_g("2.4.4"))
                          if p.suffix.lower() in (".docx", ".pptx", ".xlsx") else [])
            # 2.4.10 section-heading drafts (docx only) — likewise zip-bound.
            section_heads = _prop.propose_section_headings(p, p.suffix, ai_enabled=ai_enabled,
                                                           guidance=_g("2.4.10"))
            # 2.4.6 slide-title drafts (pptx only) — likewise zip-bound.
            slide_titles = _prop.propose_slide_titles(p, p.suffix, ai_enabled=ai_enabled,
                                                      guidance=_g("2.4.6"))
            # 2.4.6 xlsx label drafts — default sheet tabs / table columns get an AI-named label.
            xlsx_labels = _prop.propose_xlsx_labels(p, p.suffix, ai_enabled=ai_enabled,
                                                    guidance=_g("2.4.6"))
            # 1.3.2 docx reading-order recommendations (floating text boxes / frames) — deterministic.
            reading_order = _prop.propose_reading_order(p, p.suffix)
            # One-click deterministic layout cards (no AI): docx 1.4.8 + pptx 1.4.2.
            one_clicks = (_prop.propose_justified_fix(p, p.suffix)
                          + _prop.propose_autoplay_fix(p, p.suffix))
            # docx 1.4.1 / 1.4.11 — same shape, own criteria. Kept out of `one_clicks` above
            # because that list is enqueued under ONE criterion per format, and a colour card
            # filed under 1.4.8 would tell a reviewer they are fixing visual presentation.
            colour_cards = _prop.propose_underline_restore(p, p.suffix)
            contrast_cards = _prop.propose_outline_contrast(p, p.suffix)
            # 1.1.1 native-chart datasheets (docx/pptx/xlsx) — grounded alt from the chart's data.
            chart_sheets = _prop.propose_chart_datasheet(p, p.suffix)
            # 1.1.1 image alt — enumerate every unlabelled image and PRE-DRAFT it (vision when
            # reachable), so the review card arrives with a per-image thumbnail + AI description
            # for each, not a single "author it yourself" template. Reuses the fix-time alt logic.
            img_props, img_evidence = ([], [])
            if p.suffix.lower() in (".docx", ".pptx", ".xlsx"):
                try:
                    from remediate_office import alt_proposals_for_office
                    img_props, img_evidence = alt_proposals_for_office(
                        file_bytes, p.suffix, ai_enabled=ai_enabled, scan_id=scan_id,
                        context_file=filename)
                except Exception:
                    img_props, img_evidence = [], []
    except Exception:
        return
    if text:
        try:
            # P4.4 — independent verification gate: re-run detect_langs on each proposed span
            # before it reaches the queue. 3.1.2 is fully verifiable (langdetect, seed-fixed)
            # so proposals that pass get validated=True; any that fail the re-check are still
            # enqueued but stay validated=False. One call to _enqueue_proposals — the store
            # replaces on conflict, so two calls would discard the first batch.
            _lang_props = _prop.propose_language_parts(text)
            if _lang_props:
                _all_verified = all(
                    _prop.verify_language_part(p["before"], p["proposed_value"])
                    for p in _lang_props)
                _enqueue_proposals(scan_id, filename, "3.1.2", "Language of Parts",
                                   _lang_props, validated=_all_verified)
        except Exception:
            pass
        try:
            _enqueue_proposals(scan_id, filename, "1.3.3", "Sensory Characteristics",
                               _prop.propose_sensory_rewrite(text, filename=filename,
                                                             ai_enabled=ai_enabled, guidance=_g("1.3.3")))
        except Exception:
            pass
        try:
            _enqueue_proposals(scan_id, filename, "3.1.5", "Reading Level",
                               _prop.propose_reading_level(text, filename=filename, ai_enabled=ai_enabled))
        except Exception:
            pass
    # 2.4.10 — AI-drafted section headings for a long, heading-less docx (reads the zip, so
    # computed above while the temp path was alive; self-gates on the detector's conditions).
    try:
        _enqueue_proposals(scan_id, filename, "2.4.10", "Section Headings", section_heads)
    except Exception:
        pass
    # 2.4.6 — AI slide-title drafts for pptx title placeholders left empty.
    try:
        _enqueue_proposals(scan_id, filename, "2.4.6", "Headings and Labels", slide_titles + xlsx_labels)
    except Exception:
        pass
    # 1.3.2 — reading-order recommendations for docx floating text boxes / frames.
    try:
        _enqueue_proposals(scan_id, filename, "1.3.2", "Meaningful Sequence", reading_order)
    except Exception:
        pass
    # One-click deterministic layout cards — the fix is exact, the human elects it.
    try:
        if filename.lower().endswith(".docx"):
            _enqueue_proposals(scan_id, filename, "1.4.8", "Visual Presentation", one_clicks)
            _enqueue_proposals(scan_id, filename, "1.4.1", "Use of Color", colour_cards)
            _enqueue_proposals(scan_id, filename, "1.4.11", "Non-text Contrast", contrast_cards)
        else:
            _enqueue_proposals(scan_id, filename, "1.4.2", "Audio Control", one_clicks)
    except Exception:
        pass
    # 1.1.1 — chart datasheets + per-image alt drafts (vision when reachable) go on the SAME
    # 1.1.1 card in one enqueue: enqueue_proposals REPLACES per (scan,file,rule), so two calls
    # would clobber. Together they turn a single fill-in template into an editable AI
    # description per image/chart.
    try:
        _enqueue_proposals(scan_id, filename, "1.1.1", "Non-text Content",
                           (chart_sheets or []) + (img_props or []))
    except Exception:
        pass
    try:
        if img_evidence:
            core.store.attach_hitl_evidence(scan_id, filename, "1.1.1", img_evidence)
    except Exception:
        pass
    try:
        _enqueue_proposals(scan_id, filename, "1.4.5", "Images of Text", image_text)
    except Exception:
        pass
    # 2.4.4 / 2.4.9 — descriptive link-text proposals for Office hyperlinks (vague text /
    # text reused across destinations). Needs the file on disk like the OCR proposer, so it
    # was computed above while the temp path was alive; split by the sc each proposal carries.
    try:
        for sc, rule_name in (("2.4.4", "Link Purpose (In Context)"),
                              ("2.4.9", "Link Purpose (Link Only)")):
            _enqueue_proposals(scan_id, filename, sc, rule_name,
                               [p for p in link_props if p.get("sc") == sc])
    except Exception:
        pass


def _propose_form_fields(scan_id: str, filename: str, file_bytes: bytes, ai_enabled: bool) -> None:
    """AI-assisted labels for unlabeled docx content-control form fields (WCAG 3.3.2 Labels or
    Instructions — the SC the scanner flags them under). Self-gates: yields a proposal only for
    an interactive content control that lacks a title, so it's safe to run on every docx. The
    label is derived from the field's adjacent prompt text (deterministic) and falls back to the
    local text model where there's no adjacent prompt — always a one-click value a human
    approves, never auto-applied. Enqueued only under 3.3.2 (never a fabricated 4.1.2 row).
    Never fails the remediation job."""
    try:
        import io as _io
        import propose_forms as _pf
        props = _pf.form_field_proposals(_io.BytesIO(file_bytes), filename=filename,
                                         ai_enabled=ai_enabled)
    except Exception:
        return
    _enqueue_proposals(scan_id, filename, "3.3.2", "Labels or Instructions", props)


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
    # OPERATOR SCOPE. One gate here covers every proposer — 19 call sites across 12 criteria —
    # because this is the single boundary where a proposal is still labelled with its SC. Gating
    # at each proposer instead would be 19 chances to forget one, and the one forgotten is the
    # one that writes into an excluded criterion.
    #
    # Suppression is RECORDED, never silent: an operator who narrowed the scope should be able to
    # see that the narrowing is what stopped a fix, rather than wonder why a known finding never
    # produced a review card.
    allows = _remediation_scope(filename, scan_id)
    if allows is not None and not allows(sc):
        try:
            core.store.log_decision("system", "remediate.out_of_scope", scan_id=scan_id,
                                    file=filename,
                                    detail=f"{sc} is outside the operator scope — "
                                           f"{len(proposals)} proposal(s) not enqueued")
        except Exception:
            pass
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

    # Never remediate ACP's own remediated copy. POST /scans/{sid}/remediate already can't
    # enqueue one — it iterates get_scan's filtered file list — but jobs are DURABLE: a job
    # queued before that filter existed, or retried from the dead-letter, still arrives here.
    # This guard sits before the download, so a phantom costs nothing: no Drive fetch, no
    # llava call, no HITL row asking a human to describe an image ACP itself produced.
    if core.store.is_shadowed_output(scan_id, filename):
        core.store.log_decision("system", "remediate.skipped", scan_id=scan_id, file=filename,
                                detail="ACP-generated copy shadowing its source — not a document")
        return

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

    # docx form-field label proposals (3.3.2) — prefills the unlabeled-content-control
    # deferral with one-click labels derived from each field's adjacent prompt text (or the
    # local model where none). Self-gating like the text proposers; runs on the original bytes.
    if ext == "docx":
        _propose_form_fields(scan_id, filename, data, core.store.get_ai_enabled())

    # Per-fix before→after evidence for the certification report's "Before → After"
    # section. Each remediator appends {rule_id (SC), before, after, note}; we persist
    # only the ones that verifiably cleared on the post-fix re-scan (below).
    rem_diffs: list[dict] = []

    # AI-proposed one-click values applied/drafted inline during remediation (e.g. 2.4.4
    # link text). Collected here so they can be enqueued AFTER the residual re-scan below,
    # with an honest `validated` flag (True only when the applied fix actually cleared).
    inline_proposals: list[dict] = []
    # Normalized remediation tallies for the Langfuse Remediate span (G4). Every fixer returns a
    # list of applied-fix messages and a list of skipped/deferred ones; the HTML path names the
    # latter `_deferred` and the office/pdf paths `_skipped`, so collapse both onto one name here.
    # COUNTS only reach the trace — the messages are prose and stay out (see lf.remediate_span).
    rem_skipped: list = []

    _phase(job, f"applying fixes to {filename}")
    _scope_allows = _remediation_scope(filename, scan_id)
    # The gap #137 recorded here as `remediate.scope_partial` is CLOSED. The office/pdf
    # deterministic fixers now take the same `in_scope` predicate the HTML fixer does, gated at
    # each individual fix by the SC it actually writes (remediate_office._sc_ok /
    # remediate_pdf._sc_ok) rather than at the format boundary — because several of those
    # functions write four different criteria in one pass, so a per-function gate would have been
    # the same "partial gate that looks total" in a new place.
    #
    # The `scope_partial` decision is deliberately NOT emitted any more: leaving it would tell an
    # operator their scope is being half-honoured when it is now honoured in full, which is a
    # worse lie than the one it was introduced to prevent. tests/test_remediation_scope_office_pdf.py
    # pins the closure per format, including an empty-scope case that catches an ungated fix
    # generically rather than relying on this list staying complete.
    if ext in ("html", "htm"):
        fixed_html, applied, _deferred = remediate_html(
            data.decode("utf-8", errors="replace"),
            ai_enabled=core.store.get_ai_enabled(), diffs=rem_diffs,
            proposals=inline_proposals, in_scope=_scope_allows)
        rem_skipped = _deferred
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
                    diffs=rem_diffs, proposals=_pdf_proposals, applied_fixes=_applied_fixes,
                    in_scope=_scope_allows)
                rem_skipped = _skipped
                mimetype = "application/pdf"
                # A PDF's AI-written alt text is evidence exactly like an Office document's.
                # It used to be dropped: remediate_pdf returned only prose, so no row reached
                # applied_fixes and the certification record showed the fix had never happened.
                _record_applied_fixes(scan_id, filename, _applied_fixes)
                # Untagged-PDF proposals, split by kind — 1.3.2 reading order (vision) and
                # 1.3.1 structure map (deterministic font rank). Surfaced for one-click
                # confirm, never auto-applied. Before the no-fixes early return.
                _enqueue_proposals(scan_id, filename, "1.3.2", "Meaningful Sequence",
                                   [p for p in _pdf_proposals if p.get("kind") == "reading-order"])
                _enqueue_proposals(scan_id, filename, "1.3.1", "Info and Relationships",
                                   [p for p in _pdf_proposals if p.get("kind") == "structure-map"])
                # 2.4.6 heading map (tagged PDF, no headings) — a deterministic proposal for
                # one-click confirm, never auto-applied.
                _enqueue_proposals(scan_id, filename, "2.4.6", "Headings and Labels",
                                   [p for p in _pdf_proposals if p.get("kind") == "headings-map"])
                # 2.4.4 link purpose is deliberately NOT enqueued for PDF. There is no PDF
                # write-back for link text (apply_pdf_approved routes pdf:fig:/pdf:field: only),
                # so the card could be approved but never honoured — and an approved value
                # nothing writes also blocks the file from ever certifying. The finding still
                # reaches a reviewer as a plain 2.4.4 judgement row further down. See the
                # explain-only note in remediate_pdf.py.
                # 1.1.1 per-figure alt + 4.1.2 per-field accessible name are the mirror case:
                # both carry a `pdf:fig:`/`pdf:field:` locator that _apply_approved_values DOES
                # write back through remediate_pdf.apply_pdf_approved, so they are enqueued.
                # Without these two lines the cards were built by remediate_pdf and then dropped
                # here — the reviewer never saw them, so the deferral existed only as a tally.
                _enqueue_proposals(scan_id, filename, "1.1.1", "Non-text Content",
                                   [p for p in _pdf_proposals if p.get("kind") == "pdf-figure-alt"])
                _enqueue_proposals(scan_id, filename, "4.1.2", "Name, Role, Value",
                                   [p for p in _pdf_proposals if p.get("kind") == "pdf-field-name"])
            else:  # docx / pptx / xlsx
                from remediate_office import remediate_office
                _applied_fixes: list = []
                _proposals: list = []
                _evidence: list = []
                out_path, applied, _skipped = remediate_office(
                    src, ai_enabled=core.store.get_ai_enabled(), scan_id=scan_id,
                    applied_fixes=_applied_fixes, proposals=_proposals,
                    evidence=_evidence, diffs=rem_diffs, in_scope=_scope_allows)
                rem_skipped = _skipped
                mimetype = _OFFICE_MIME[ext]
                _record_applied_fixes(scan_id, filename, _applied_fixes)
                # AI-proposed (but not auto-applied) alt: an ungrounded vision guess is
                # surfaced for one-click approval rather than silently written (WCAG 1.1.1
                # intent stays human). Attach the prefilled drafts to the file's 1.1.1 HITL
                # row — before the no-fixes early return, or they die inside the job result.
                # Route each proposal to ITS criterion. remediate_office used to return only
                # vision alt, so hard-coding 1.1.1 here was correct; it now also drafts 2.4.4,
                # 1.3.3 and 3.1.2 (see _draft_docx_assisted), and a link-text draft filed under
                # 1.1.1 would ask a reviewer to approve alt text that is not alt text — and
                # would clear the wrong finding when they did.
                #
                # Untagged proposals default to 1.1.1: every proposer that predates the `sc`
                # field emits vision alt, so the default preserves their behaviour exactly
                # rather than silently dropping them into a bucket nobody reads.
                _PROP_RULE_NAMES = {
                    "1.1.1": "Non-text Content", "2.4.4": "Link Purpose (In Context)",
                    "1.3.3": "Sensory Characteristics", "3.1.2": "Language of Parts",
                }
                _by_sc: dict[str, list] = {}
                for _p in _proposals:
                    _by_sc.setdefault((_p or {}).get("sc") or "1.1.1", []).append(_p)
                for _sc, _group in _by_sc.items():
                    _enqueue_proposals(scan_id, filename, _sc,
                                       _PROP_RULE_NAMES.get(_sc, _sc), _group)
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
                            # Merges into this file's 1.1.1 row when one already exists (the
                            # proposals row queued just above). rule_name so a row created here
                            # is headed "Non-text Content", not the raw deferral note.
                            core.store.queue_hitl_deferral(scan_id, filename, _msg, _n,
                                                           rule_name="Non-text Content")
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
    # G4: the Remediate span now carries what the fix pass DID — how many fixes applied vs
    # skipped/deferred — not just where the copy was written. `applied` and `rem_skipped` are
    # lists of prose messages; only their counts reach the trace (lf.remediate_span is PHI-safe).
    core.emit_remediation_span(scan_id, filename, drive_write_url=web_url,
                               fixes_applied=len(applied), fixes_skipped=len(rem_skipped))
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


# ── Lifecycle rule evaluation during Discover (PRD §4.3 / §6, Phase B4) ─────────
# disposition_policy now has a priority column (Lifecycle Rules build-plan item #6) —
# list_disposition_policies() sorts by it (NULLs last, then name), so `policies` below is already
# in precedence order; nothing here needs to re-sort. The archive-vs-delete precedence decision
# itself lives in disposition.resolve_candidate — shared with the conflicts report
# (routes/disposition.list_conflicts) so both make the same call from one place.


def _evaluate_discover_lifecycle_rules(scan_id: str, source: str, actor: str | None) -> None:
    """Evaluate enabled disposition policies against the freshly persisted inventory and record
    CANDIDATE outcomes (PRD §4.3 / §6, Phase B4). Candidate-first: a matching archive rule flags
    the file 'Archive Candidate' and a delete rule 'Delete Candidate' — the actual Drive
    move/delete is NEVER performed here (that stays behind the approval/execute path). A tag rule
    writes system tags. Idempotent (AC-13): re-running Discover adds no duplicate tags (file_tags
    PK) and logs no duplicate audit row (doc_has_disposition guard), so unchanged inputs+rules
    produce no new actions.

    Keying: tags/status are keyed by (scan_id, file) — the file_tags / scan_inventory grain. The
    audit doc_id is a discover-grain key ("scan:<scan_id>:<file>"), deliberately distinct from the
    approval-time drive:<fileId> key the Tag-action PR (#314) uses, so the two paths never collide.
    """
    import disposition
    import uuid
    # owner=actor is the fix for the reported "rules created by the demo account can appear in
    # your workflow" defect: this was the one caller of list_disposition_policies() that already
    # had the scan owner in scope (as `actor`) and still fetched every tenant's enabled policies.
    policies = [p for p in core.store.list_disposition_policies(owner=actor) if p.get("enabled")]
    if not policies:
        return
    for r in core.store.list_inventory(scan_id):
        file = r.get("file")
        # An Exempted file (legal hold etc.) is never moved to a candidate status, tagged, or
        # re-audited by a rule run (PRD §6).
        if r.get("lifecycle_status") == "Exempted":
            continue
        doc_id = f"scan:{scan_id}:{file}"
        doc = {
            "doc_id": doc_id,
            "source": source,
            "path": r.get("path"),
            "parent_folder": r.get("parent_folder"),
            "created_at": r.get("created_at"),
            # matches() maps source_modified -> modified_at so "modified before <date>" works.
            "source_modified": r.get("source_modified"),
            "owner": r.get("owner"),
            # doc_class/size_kb (Lifecycle Rules build-plan item #3, "file type"/"larger than")
            # were added to disposition.FIELDS and the condition builder in #610, but never wired
            # in here — a file-type or larger-than rule validated and saved fine, then silently
            # matched nothing at Discover time forever, because `values.get("doc_class")` (and
            # `size_kb`) read a key this dict never set. Both are already on the inventory row.
            "doc_class": r.get("doc_class"),
            "size_kb": r.get("size_kb"),
        }
        matched = []
        for p in policies:
            try:
                match = _json.loads(p.get("match") or "[]")
            except Exception:
                continue
            if disposition.matches(doc, match):
                matched.append(p)
        if not matched:
            continue
        # ── Tag rules: apply EVERY matching tag policy. Tag + Archive both match → tags AND the
        # Archive candidate status are applied (PRD §6), so tags are never suppressed by a
        # co-matching disposition rule.
        for p in matched:
            if p.get("action") != "tag":
                continue
            if core.store.doc_has_disposition(doc_id, p["policy_id"]):
                continue  # already tagged + audited on an earlier Discover — idempotent
            try:
                cfg = _json.loads(p.get("action_config") or "{}")
            except Exception:
                cfg = {}
            tags = disposition.tag_list(cfg)
            if not tags:
                continue
            core.store.add_file_tags(scan_id, file, tags, kind="system", rule_id=p["policy_id"])
            core.store.create_disposition_audit(
                uuid.uuid4().hex, doc_id=doc_id, policy_id=p["policy_id"], action="tag",
                result="applied", detail="tagged: " + ", ".join(tags), owner_email=actor)
        # ── Candidate status: archive-vs-delete precedence (PRD §6), shared with the conflicts
        # report — see disposition.resolve_candidate's own docstring for the precedence rule.
        chosen, new_status, reason = disposition.resolve_candidate(matched, actor)
        if chosen is None:
            continue
        if core.store.doc_has_disposition(doc_id, chosen["policy_id"]):
            continue  # this rule already flagged + audited this file on an earlier Discover
        core.store.set_lifecycle_status(scan_id, file, new_status,
                                        rule_id=chosen["policy_id"], reason=reason)
        core.store.create_disposition_audit(
            uuid.uuid4().hex, doc_id=doc_id, policy_id=chosen["policy_id"],
            action=chosen.get("action"), result="pending_approval", detail=reason,
            owner_email=actor)


def _mark_discovered(scan_id: str) -> None:
    """Record the run-level discovery-completion instant, and never fail discovery over it.

    The inventory is already written by the time this runs. Losing the timestamp costs a date on
    a screen; raising here would lose the inventory the job just spent the estate's listing budget
    producing — the same fail-quiet contract the Langfuse discover trace already follows, and for
    the same reason. A run that misses the stamp still reads correctly: the frontend falls
    back to the newest per-file `scan_inventory.discovered_at`."""
    try:
        core.store.mark_discovery_complete(scan_id)
    except Exception:
        pass


def persist_discovery_inventory(scan_id: str, inv: list[dict], source: str, actor: str | None) -> dict:
    """Persist the per-file discovery inventory and evaluate the lifecycle (archival/deletion) rules
    over it — the shared post-discovery step so a scan marks Archive/Delete candidates regardless of
    which scan path ran it. Historically only the fanout path (_scan_discover) did this inline; the
    default in-process scan (routes/scans.py) skipped it, so archive/delete rules were silently NOT
    evaluated on a normal Discover, and that path also left the per-file inventory (which the Assess
    eligibility count reads) unpopulated. Both are fixed by routing every path through here.

    Idempotent: add_inventory de-dupes on (scan_id, file) and the rule evaluation is candidate-first
    and guarded (doc_has_disposition), so a re-run adds nothing. Never executes a Drive move/delete.
    mark_discovery_complete is set-once for the same reason, so a re-run does not re-date the
    snapshot either.

    Returns the save-outcome dict from add_inventory: {"new": N, "updated": M, "unchanged": 0,
    "failed": P}.  Callers that emit progress payloads should forward these as save_new,
    save_updated, save_unchanged, save_failed so the frontend can display the saving-step KPI."""
    from scanner import _dedupe_inventory_files
    _dedupe_inventory_files(inv)
    outcome = core.store.add_inventory(scan_id, inv) if inv else {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
    _evaluate_discover_lifecycle_rules(scan_id, source, actor)
    # The discovery phase is over: the inventory is persisted and the lifecycle rules have run.
    # Stamp WHEN, because every count taken from this inventory is only true as of this instant
    # and nothing else on scan_runs records it — completed_at is the end of ASSESS. Stamped after
    # the writes above so it dates an inventory that exists rather than one that was attempted.
    _mark_discovered(scan_id)
    return outcome


@handler("scan_discover")
def _scan_discover(payload: dict, job: dict) -> None:
    """List the source (paginated, no cap), create the scan_runs row, and enqueue one
    scan_file job per file. Each file's Langfuse trace is opened later, per file, by
    _analyse_and_persist_one — not here."""
    from rubric import Rubric
    from scanner import _list, _drive_service, ACP, FANOUT_MAX_FILES, _scope_for_listing
    scan_id = payload.get("scan_id") or job.get("scan_id")
    source = payload.get("source", "drive")
    ai = bool(payload.get("ai", True)) and core.store.get_ai_enabled()
    pii = bool(payload.get("pii", False))
    user = payload.get("user")
    folder = payload.get("folder")
    # The fan-out path is the PRODUCTION listing path (see below), so multi-folder scope has to
    # be read here too — wiring only run_scan would narrow scans correctly in dev and scan the
    # whole estate in the deployment that matters.
    folders = payload.get("folders")
    exclude_folders = payload.get("exclude_folders")
    toks = core.get_scan_tokens(scan_id)
    # Prefer token from durable job payload — in-memory store is per-replica and invisible to a
    # worker container that does not share the API's memory (split topology without Redis).
    drive_token = payload.get("drive_token") or toks.get("drive")
    sp_tok = payload.get("sp_token") or toks.get("sp")
    rb = Rubric.load_active(ACP / "config")
    svc = None if source in ("local", "sharepoint") else _drive_service(drive_token)
    effective_folder = folder if folder else (None if folders else ("root" if drive_token else None))
    scope: dict = {}
    # `inventory` collects per-file rows for the NON-scannable estate (media / unsupported /
    # extensionless) — every accessible file that is NOT in the assessable `items` set. The
    # scannable rows are built from `items` below; together they inventory the WHOLE estate
    # (PRD Phase A2) while only the assessable subset is ever downloaded and analysed.
    inventory: list[dict] = []
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    defer = _defer_analysis_to_assess()
    # Create the scan_runs row NOW, before the file listing, so GET /scans/{id} returns a result
    # as soon as a worker claims the job. The frontend polls once per second and gives up at 45
    # consecutive misses — a large-estate listing takes longer than that window and triggers the
    # false "this scan never started" error. total=0 is updated by set_scan_files once _list()
    # returns; scope is written by merge_scan_scope once the listing scope dict is populated.
    core.store.init_scan_run(scan_id, source, 0, started, rb.name, rb.hash, owner=user,
                             status="running")
    # scope_files gates what is READ, not what is scored. This is the PRODUCTION listing path
    # (ADR 0007 fan-out); run_scan's is the local one, and wiring only that would leave a
    # hospital's PDFs being downloaded and OCR'd in the deployment that matters.
    # Emit live file counts during the listing so the frontend ticks up rather than showing 0
    # for the full duration. Throttled to one DB write every 2 s — the scanner does the timing
    # inside _search_drive/_search_folder; this callback just persists whatever count arrived.
    def _listing_progress(count: int) -> None:
        try:
            core.store.set_scan_files(scan_id, count)
        except Exception:  # noqa: BLE001 — a diagnostic must never fail the scan
            pass

    items = _list(source, svc, folder=effective_folder, sp_token=sp_tok,
                  max_files=FANOUT_MAX_FILES, **({"folders": folders} if folders else {}),
                  **({"exclude_folders": exclude_folders} if exclude_folders else {}),
                  exclude_remediated=bool(payload.get("exclude_remediated", False)),
                  scope_out=scope, scope_files=_scope_for_listing(user), inventory_out=inventory,
                  progress_cb=_listing_progress)
    # shadow_candidate (a file sharing a logical name with another — possibly ACP's own output
    # shadowing its source) is computed inside _enqueue_analysis from the item list, so the same
    # rule applies whether the fan-out runs now or later at Assess.
    _exclude_rem = bool(payload.get("exclude_remediated", False))

    incremental = bool(payload.get("incremental", True))
    # Freeze the enabled per-file WCAG scope rules into this scan alongside scan_scope (PRD §4.4 /
    # C4). The score and trace paths both resolve each file against THIS frozen set, so an admin
    # editing rules mid-scan can never make a file's score and its stored traces disagree — the
    # same frozen-scope discipline scan_scope already follows (Phase 3a).
    try:
        scope["scope_rules"] = [
            {k: r.get(k) for k in ("rule_id", "selector", "value", "codes",
                                   "priority", "is_override", "enabled")}
            for r in core.store.list_scope_rules(enabled_only=True)
        ]
    except Exception:
        scope["scope_rules"] = []
    # Update the file count and full scope now that listing is complete.
    core.store.set_scan_files(scan_id, len(items))
    core.store.merge_scan_scope(scan_id, scope)
    if defer:
        core.store.set_scan_status(scan_id, "discovered")
    # Normalise the source listing to the common analysis-item shape. `mime` stays the Google-
    # native EXPORT selector _download keys off; `source_mime` (the real MIME) is carried for the
    # inventory row's `mime` column, along with the source metadata each listing now surfaces.
    norm = [{"file": it["name"], "drive_file_id": it.get("id"), "mime": it.get("mime"),
             "path": it.get("path"), "checksum": it.get("checksum"),
             # THE DRIVE THE ITEM WAS LISTED FROM. _sp_list carries this per file precisely
             # because Graph item ids are unique only within a drive; dropping it here is what
             # sent every SharePoint file down _download's Google-Drive branch.
             "drive_id": it.get("driveId"),
             "source_modified": it.get("source_modified"),
             "source_mime": it.get("source_mime"), "created_at": it.get("created_at"),
             "owner": it.get("owner"), "parent_folder": it.get("parent_folder"),
             "size_kb": it.get("size_kb"),
             # SharePoint's Content Type name, best-effort (_sp_enrich_content_types). None for
             # every other source, and None here whenever the tenant did not return one — never
             # invented. See classificationData.js on the frontend for why absence must stay
             # absence all the way through this pipeline.
             "content_type": it.get("content_type")} for it in items]
    if defer:
        # ADR 0020 stage 3/4 — Discover LISTS only: classify from metadata (no file opened),
        # persist the inventory + the scan-level params, and STOP. The estate is browsable in
        # seconds; the download + WCAG analysis happen at Assess (scan_assess), which rebuilds
        # identical fan-out work from this inventory — filtered back to the assessable subset, so
        # the non-scannable rows persisted here are never downloaded. file_records stay empty
        # until then, so the finalize counter (count_files_done) is untouched by deferral.
        import classify as _cls
        from scanner import _dedupe_inventory_files
        # Scannable rows FIRST (canonical names, from the analysis set) so _dedupe_inventory_files
        # keeps their names intact; the non-scannable estate rows follow.
        inv = [{"file": it["file"], "drive_file_id": it.get("drive_file_id"),
                "mime": it.get("source_mime"), "size_kb": it.get("size_kb"),
                "doc_class": _cls.classify_from_metadata(it["file"], it.get("source_mime"))["doc_class"],
                "checksum": it.get("checksum"), "path": it.get("path"),
                "created_at": it.get("created_at"), "source_modified": it.get("source_modified"),
                "owner": it.get("owner"), "parent_folder": it.get("parent_folder"),
                # Carried into the row because Assess rebuilds its download work from the
                # INVENTORY, not from `norm` — so anything the download needs has to survive
                # the round trip through the table.
                "drive_id": it.get("drive_id"),
                "content_type": it.get("content_type")}
               for it in norm] + inventory
        _dedupe_inventory_files(inv)
        if inv:
            core.store.add_inventory(scan_id, inv)
        # Phase B4 — with the inventory persisted, run enabled disposition rules against it and
        # record candidate lifecycle outcomes (never executing the Drive move/delete here). Runs
        # before the no-assessable-items short-circuit below because a rule may match a
        # non-scannable estate row (old media to archive, a /tmp file to flag for deletion).
        _evaluate_discover_lifecycle_rules(scan_id, source, user)
        # THIS is where an ADR 0020 run's discovery ends — the estate is listed, the inventory is
        # persisted, the lifecycle rules have run, and nothing further happens until somebody
        # triggers Assess. The run stays at status='discovered' with completed_at NULL, possibly
        # forever, so without this stamp there is no record of when its inventory was taken and every
        # count rendered from that inventory is a snapshot with no date. Set-once (see the store),
        # so a re-delivered discover job does not move it.
        _mark_discovered(scan_id)
        # Discover-phase tracing (lf.discover_run_trace). Until this call, an ADR 0020
        # Discover-only run emitted NOTHING to Langfuse: the "Discover" span lives on the analyse
        # path, which under this ADR runs at Assess time, so the phase that lists the estate and
        # evaluates the lifecycle rules was invisible — and the inventoried-but-never-assessed
        # rows were invisible permanently, since nothing later opens them.
        #
        # Emitted AFTER the inventory is persisted and the rules have run, so the trace describes
        # what actually happened rather than what was about to be attempted, and wrapped because
        # a tracing failure must never lose an inventory that is already written.
        try:
            import lf as _lf                      # module-local, as every other _lf site here is
            _spans = _lf.discover_file_spans(scan_id, inv, user=user)
            _lf.discover_run_trace(scan_id, source, listed=len(norm), inventoried=len(inv),
                                   scope=scope, user=user, file_spans_emitted=_spans)
            _lf.flush()
        except Exception:
            pass
        if not items:
            # The estate is inventoried, but nothing in it is assessable — close the run rather
            # than leave it waiting for an Assess that would enqueue zero files.
            core.store.enqueue_job("scan_finalize",
                                   {"scan_id": scan_id, "source": source, "ai": ai, "pii": pii}, scan_id=scan_id)
            return
        core.store.set_setting(f"assess_params:{scan_id}", _json.dumps(
            {"source": source, "ai": ai, "pii": pii, "incremental": incremental,
             "exclude_remediated": _exclude_rem, "batch": bool(payload.get("batch"))}))
        core.store.log_decision("system", "scan.discovered", scan_id=scan_id,
                                detail=f"{len(inv)} file(s) inventoried from metadata (no file opened) — "
                                       f"{len(items)} assessable, awaiting Assess")
        return
    if not items:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source, "ai": ai, "pii": pii}, scan_id=scan_id)
        return
    # Immediate path (default today): fan out the analysis now. ADR 0008 batches large estates.
    _enqueue_analysis(scan_id, source, norm, ai=ai, pii=pii, user=user,
                      incremental=incremental, exclude_remediated=_exclude_rem,
                      force_batch=bool(payload.get("batch")))


@handler("scan_assess")
def _scan_assess(payload: dict, job: dict) -> None:
    """ADR 0020 — begin the ASSESS phase for a discovered scan: rebuild the download+analyse
    fan-out from the persisted inventory + scan params, flip the run back to 'running', and let
    the existing per-file jobs + finalize trigger take over. Idempotent: if file_records already
    exist (a prior assess ran), re-enqueuing is harmless (save_file_result upserts)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    user = payload.get("user")
    inv = core.store.list_inventory(scan_id)
    try:
        params = _json.loads(core.store.get_setting(f"assess_params:{scan_id}") or "{}")
    except Exception:
        params = {}
    source = params.get("source", payload.get("source", "drive"))
    ai = bool(params.get("ai", True)) and core.store.get_ai_enabled()
    pii = bool(params.get("pii", False))
    incremental = bool(params.get("incremental", True))
    exclude_rem = bool(params.get("exclude_remediated", False))
    # Phase C3 (PRD §4.5) — by default Assess skips inventory rows a lifecycle rule flagged for
    # archive/deletion (LIFECYCLE_EXCLUDED_DEFAULT). include_lifecycle_flagged is the authorized
    # override; it reaches here only through the assess route, which already gates on the scan
    # owner (get_scan owner=...), so being present in the payload is the owner-gate.
    include_flagged = bool(payload.get("include_lifecycle_flagged")
                           or params.get("include_lifecycle_flagged"))
    core.store.set_scan_status(scan_id, "running")
    # CRITICAL — the inventory now records the WHOLE estate, including media / unsupported /
    # extensionless files that must NEVER be downloaded or analysed. Rebuild the fan-out from the
    # ASSESSABLE rows only (a supported doc format with at least one applicable WCAG test); the
    # rest stay inventory-only. Estate capability is re-derived from name + real MIME so the gate
    # holds regardless of what doc_class label a row happens to carry.
    import estate_inventory as _est
    from scanner import EXPORT_MAP as _EXPORT_MAP
    items = []
    # ── What the lifecycle rules held back, COUNTED WHERE THE HOLDING BACK HAPPENS ────────────
    # These three are the run's own record of its lifecycle exclusion, persisted onto scope below.
    # Counted here, at the decision, rather than re-derived afterwards from the inventory: this is
    # the same discipline `skipped_out_of_scope` follows in scanner._list — the count is made by
    # the code that did the dropping, so it cannot disagree with what the run actually enqueued.
    #
    #   lifecycle_flagged   every flagged file, ANY format — the estate-wide fact.
    #   eligible_excluded   the ASSESSABLE subset actually held back. Disjoint from the
    #                       "no test exists" population by construction, because it is counted
    #                       only after the assessable gate above has already passed.
    #   overridden          flagged files an authorized override assessed anyway. They ARE
    #                       assessed, so they belong to the assessed bucket, never to a sixth one.
    lifecycle_flagged = 0
    eligible_excluded = 0
    overridden = 0
    for r in inv:
        lc = r.get("lifecycle_status")
        flagged = lc in core.store.LIFECYCLE_EXCLUDED_DEFAULT
        if flagged:
            # Counted BEFORE the assessable gate: a flagged .png was never assessable, but it is
            # still a file a lifecycle rule flagged, and the estate-wide total says so.
            lifecycle_flagged += 1
        if _est.classify({"name": r.get("file"), "mimeType": r.get("mime")})["status"] != _est.ASSESSABLE:
            continue
        # Phase C3 (PRD §4.5) — a file a lifecycle rule flagged for archive/deletion is excluded
        # from Assess by default. Either way the assess record retains the lifecycle status + the
        # exclusion reason that applied when this run was created (status/rule/reason preserved).
        if flagged:
            base = r.get("lifecycle_reason")
            if include_flagged:
                excl = (f"included in Assess despite lifecycle status '{lc}' (authorized override)"
                        + (f" — {base}" if base else ""))
                core.store.set_lifecycle_status(scan_id, r["file"], lc,
                                                rule_id=r.get("lifecycle_rule_id"), reason=base,
                                                exclusion_reason=excl)
                overridden += 1
            else:
                excl = (f"excluded from Assess: lifecycle status '{lc}'"
                        + (f" — {base}" if base else ""))
                core.store.set_lifecycle_status(scan_id, r["file"], lc,
                                                rule_id=r.get("lifecycle_rule_id"), reason=base,
                                                exclusion_reason=excl)
                eligible_excluded += 1
                continue
        # `mime` on the analysis item is the Google-native EXPORT selector, NOT the stored source
        # MIME — feeding a real "application/pdf" here would KeyError in _download's EXPORT_MAP.
        src_mime = r.get("mime")
        items.append({"file": r["file"], "drive_file_id": r.get("drive_file_id"),
                      "mime": src_mime if src_mime in _EXPORT_MAP else None,
                      "path": r.get("path"), "checksum": r.get("checksum"),
                      "drive_id": r.get("drive_id"),
                      "source_modified": r.get("source_modified")})
    # ── PERSIST THE EXCLUSION ONTO THE RUN ───────────────────────────────────────────────────
    # Recorded on `scan_runs.scope`, beside `skipped_out_of_scope`, because it is the same kind of
    # fact: part of the boundary of what this run covered. Without it the Overview reconciliation
    # can only say "not recorded" for this bucket, permanently — the panel already reads these
    # exact keys and has nothing to read.
    #
    # A ZERO HERE IS A MEASUREMENT, and that is the only reason writing zeros is allowed. This
    # code ran, walked every inventory row, and found none flagged. A run that never reached this
    # point (a Discover that was never assessed) writes NOTHING, so its scope carries no such key
    # and a reader correctly sees "not recorded" rather than a reassuring 0. merge_scan_scope
    # touches only the keys handed to it, so nothing else on the scope is disturbed.
    core.store.merge_scan_scope(scan_id, {
        "lifecycle_excluded": lifecycle_flagged,
        "lifecycle_eligible_excluded": eligible_excluded,
        "lifecycle_overridden": overridden,
    })
    # ── THE RUN'S TOTAL IS THE POPULATION ASSESS ACTUALLY ENQUEUED ───────────────────────────
    # `files` was written once, at init_scan_run, from the DISCOVERED count — correct then,
    # because at discover time that is the only population there is. The loop above has since
    # narrowed it twice: non-assessable rows are dropped, and by default so is every row a
    # lifecycle rule flagged. Only `items` was ever enqueued.
    #
    # Left unwritten, `files` keeps describing the wider population while `files_done` counts the
    # narrower one, so `files - files_done` reports deliberately-excluded files as NOT STARTED.
    # That difference is what the frontend reads to call a run partially complete — so with the
    # old numbers the likeliest cause of a "partially completed" screen was a lifecycle rule doing
    # exactly what it was asked to. After this write, `files - files_done` means precisely
    # "selected for THIS assess and never started".
    #
    # Written HERE, with `items` in hand and immediately before the fan-out, so no worker can bump
    # files_done against a total that is still the discovered one. Assignment, not accumulation: a
    # re-assess re-enters this path and must describe ITS OWN population, not the sum of both runs.
    core.store.set_scan_files(scan_id, len(items))
    _enqueue_analysis(scan_id, source, items, ai=ai, pii=pii, user=user,
                      incremental=incremental, exclude_remediated=exclude_rem,
                      force_batch=bool(params.get("batch")))


def _analyse_and_persist_one(scan_id, item, source, pii, svc, toks, now, _lf, user=None,
                             rubric_hash=None, incremental=True) -> None:
    """Per-file WALL-CLOCK safety net around the real work (_impl below).

    The sub-steps are already individually bounded — download (httpx timeout 120s), the .NET
    office CLI (ACP_OFFICE_CLI_TIMEOUT 180s), OCR (ACP_OCR_MAX_IMAGES 30 + downscale). But "each
    sub-call is bounded" is not "the file is bounded": a step that ever slips its own timeout, a
    retry loop, or a future analyser added without one would let ONE document hold its worker
    forever — and with a small worker pool that stalls the whole scan at "0 of N", exactly the
    shape seen on a cold, image-heavy SharePoint run. This converts that into a bounded per-file
    error: if a file exceeds ACP_SCAN_FILE_TIMEOUT_S (default 600s), it is recorded as an error
    and the worker is freed, so the scan always drains and finalizes.

    Safe against the finalize trigger: the caller (scan_file / scan_batch) runs its
    count_files_done → scan_finalize check AFTER this returns, and the error row here counts
    toward that total — so a timed-out LAST file still finalizes the scan. save_file_result
    upserts, so if the orphaned worker thread finishes late with a real result it simply replaces
    the error row (no double count). ACP_SCAN_FILE_TIMEOUT_S=0 disables the watchdog.
    """
    import threading
    try:
        cap = int(_os.environ.get("ACP_SCAN_FILE_TIMEOUT_S", "600") or "600")
    except ValueError:
        cap = 600
    if cap <= 0:
        return _analyse_and_persist_one_impl(scan_id, item, source, pii, svc, toks, now, _lf,
                                             user=user, rubric_hash=rubric_hash,
                                             incremental=incremental)
    outcome: dict = {}

    def _work():
        try:
            _analyse_and_persist_one_impl(scan_id, item, source, pii, svc, toks, now, _lf,
                                          user=user, rubric_hash=rubric_hash,
                                          incremental=incremental)
            outcome["done"] = True
        except BaseException as e:   # noqa: BLE001 — re-raised on the caller thread below
            outcome["error"] = e

    th = threading.Thread(target=_work, name=f"scanfile:{item.get('file')}", daemon=True)
    th.start()
    th.join(cap)
    if th.is_alive():
        name = item.get("file")
        print(f"[scan] {name}: exceeded the {cap}s per-file limit — recording it as an error and "
              f"moving on so the scan can finish (the file's own bounded sub-calls will let the "
              f"stuck worker thread exit on its own)", flush=True)
        try:
            core.store.log_decision("system", "scan.file_timeout", scan_id=scan_id, file=name,
                                    detail=f"exceeded per-file limit {cap}s")
        except Exception:
            pass
        # Record an error row so count_files_done reaches total and the scan finalizes. Upsert, so a
        # late-finishing orphan thread just overwrites this with its real result.
        try:
            core.store.save_file_result(scan_id, {
                "file": name, "engine": "n/a", "status": "error", "score": None,
                "compliant": 0, "skipped_rules": 0, "issues": [],
                "drive_file_id": item.get("drive_file_id")}, now)
        except Exception:
            pass
        # Flag the timed-out file ERROR in its trace (item 2), so it stands out in Langfuse instead
        # of looking like a clean discover-only trace. Best-effort.
        try:
            import lf as _lf2
            _lf2.file_error_span(_lf2.file_trace(scan_id, name, user=user),
                                 f"exceeded per-file limit {cap}s")
        except Exception:
            pass
        return
    if "error" in outcome:
        raise outcome["error"]   # preserve the impl's original error propagation


def _analyse_and_persist_one_impl(scan_id, item, source, pii, svc, toks, now, _lf, user=None,
                                  rubric_hash=None, incremental=True) -> None:
    """Download + analyse + assess + persist ONE file and emit its Discover span on that
    file's own Langfuse trace. Shared by scan_file (per-file fan-out) and scan_batch
    (ADR 0008). A
    fetch/analyse failure is recorded as an 'error' file so the scan still finalizes."""
    from scanner import _download, analyse_and_assess
    import time as _time
    import stage_timing as _st
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
    _timings = _st.ScanTimings()          # ADR 0037 Step 0 — measure download vs analyse (side-channel)
    try:
        if dedup:
            dedup_of = dedup.pop("dedup_of", None)
            reused_from_scan = dedup.pop("reused_from_scan", None)
            pinfo = dedup.pop("pii")
            fdict = {"file": name, **dedup}
            # RE-SCORE UNDER THE CURRENT SCOPE. The findings are reused; the SCORE is not.
            #
            # `score`, `compliant` and `skipped_rules` are scope-dependent — `_scoped_for_scoring`
            # decides which findings `Rubric.assess` ever sees — but `find_prior_analysis` gates
            # reuse on rubric_hash alone. So narrowing the operator's scope and re-scanning
            # returned the score computed under the OLD scope: one measured .docx with a 1.1.1 and
            # a 1.3.1 finding scores 60 unscoped and 75 with only 1.1.1 in scope, and the reuse
            # handed back 60. Silently, and looking exactly like the scope had done nothing.
            #
            # That is the same class of staleness rubric_hash already guards ("a stale analysis
            # under an old rubric is not valid evidence once the rule set has changed") — a stale
            # score under an old SCOPE is not valid evidence either.
            #
            # Re-scored rather than invalidated, which is the cheaper and more faithful fix: the
            # full issue list comes back with the reuse, and scoring is a pure function over it.
            # No download, no engine, no OCR — the entire point of ADR 0011 survives. This is
            # what `_scoped_for_scoring`'s own note already promises: "Every finding stays on the
            # record, so re-reporting the same scan under a different scope needs no re-scan."
            try:
                from scanner import rescore_reused
                # PHASE 3a — re-score the reused analysis under THIS scan's FROZEN scope
                # (get_scan_scope), not the live global, so the reused score matches the scope the
                # run was started under and the traces save_file_result writes for it below.
                # C4 — resolve this file's per-file scope, the same as save_file_result and
                # analyse_and_assess, so a reused score also honours folder/owner scope rules.
                fdict.update(rescore_reused(fdict.get("issues") or [], name,
                                            fdict.get("status"),
                                            scope=core.store.scope_for_file(
                                                scan_id, name, core.store.get_scan_scope(scan_id))))
            except Exception:
                # Deliberately narrow: a rescore failure leaves the reused score in place rather
                # than failing the file. Logged, because a silent fallback here is how the stale
                # score came back unnoticed the first time.
                print(f"[scan] {name}: could not re-score reused analysis — "
                      "keeping the prior score", flush=True)
            if reused_from_scan and pinfo and pinfo.get("total"):
                # PII carries more sensitivity than a WCAG score -- copying it forward
                # gets its own audit entry rather than a silent inherit (ADR 0011).
                core.store.log_decision("system", "pii.copied_forward", scan_id=scan_id, file=name,
                                        detail=f"from scan {reused_from_scan}: {pinfo['total']} item(s)")
        else:
            try:
                # An earlier file in this scan already proved the credential cannot read Drive.
                # Downloading anyway costs six HTTP round-trips (MediaIoBaseDownload retries
                # five times) to re-learn it, per file. Raise the known reason instead and let
                # the handler below record the row exactly as it would have.
                # Drive only, and never a local file: `source` is what decides which credential
                # the download will use, so it is what decides whether a Drive credential
                # failure is relevant. A SharePoint or local-corpus scan is unaffected.
                halted = (drive_download_halted(scan_id)
                          if source == "drive" and not item.get("path") else None)
                if halted:
                    raise RuntimeError(halted)
                it = {"name": name, "id": item.get("drive_file_id")}
                if item.get("mime"):
                    it["mime"] = item["mime"]
                if item.get("path"):                       # local source — read from disk
                    it["path"] = item["path"]
                # SHAREPOINT GOES THROUGH GRAPH, NOT THE DRIVE CLIENT. Derived from the scan's own
                # `source` rather than carried as a flag: a stored marker can drift out of step
                # with the scan it belongs to, and this cannot. Without it `_download` fell through
                # to files().get_media() with a Graph item id and every SharePoint file recorded
                # status='error' — surfacing as "could not analyse — file unreadable" for files
                # that were never fetched at all.
                if source == "sharepoint" and not item.get("path"):
                    it["sp"] = True
                    # May be absent for a OneDrive listing, which genuinely has no driveId;
                    # _sp_download reads that as /me/drive, which is correct there and ONLY there.
                    if item.get("drive_id"):
                        it["driveId"] = item["drive_id"]
                _dl_t0 = _time.monotonic()
                _download(it, tmp, svc, sp_token=toks.get("sp"))
                # ADR 0020 §1 — cache the source bytes for a later Assess phase (best-effort,
                # never blocks the scan). Dedup'd files skip this branch entirely: their bytes
                # live under the PRIOR scan's key, which the stage-3 reader will fall back to.
                from scanner import cache_source_bytes
                cache_source_bytes(tmp, name, scan_id, user)
                _timings.add("download", _time.monotonic() - _dl_t0)   # ADR 0037 Step 0
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
                    # scan_id threads the per-rule progress line through. This is the PRODUCTION
                    # fan-out path (ADR 0007) — run_scan's in-process pool is the local one — so
                    # without it the line works in development and is silent where users are.
                    _an_t0 = _time.monotonic()
                    fdict, pinfo = analyse_and_assess(tmp, name, detect_pii=pii, scan_id=scan_id)
                    _timings.add("analyse", _time.monotonic() - _an_t0)   # ADR 0037 Step 0
            except Exception as e:
                # A credential failure is true of the whole scan, so it is named once, acted on
                # once, and every remaining file skips its doomed download (drive_auth_failure).
                # Anything else is this file's own problem and is recorded verbatim.
                _reason = drive_auth_failure(e)
                if _reason:
                    _stop_scan_downloads(scan_id, _reason)
                _msg = _reason or f"{type(e).__name__}: {e}"
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
        fdict["source_modified"] = item.get("source_modified")
        if pinfo:
            fdict["pii"] = pinfo
        core.store.save_file_result(scan_id, fdict, now)
        # ADR 0037 Step 0 — record this file's stage timing (side-channel, best-effort: a timing write
        # must never fail the scan). Skipped when nothing was measured — the reuse/dedup path downloads
        # and analyses nothing, so it has no timing to record.
        try:
            _t = _timings.as_dict()
            if _t.get("totals_s"):
                core.store.record_file_timing(scan_id, name, _t)
        except Exception:
            pass
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
            # owner_email from the same `user` — see store.save_scan's note: the tenant gets its
            # own column now, and `owner` keeps whatever it had so nothing changes today.
            core.store.upsert_document(doc_id, source=source, path=name, content_hash=checksum,
                                       owner=user, owner_email=user,
                                       created_at=created_at, last_seen=now,
                                       triage_score=tscore, triage_rationale=rationale,
                                       classify=fdict.get("classify"),   # ADR 0020 stage 2
                                       size_kb=item.get("size_kb"))
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
        # Item 1 — write this file's ASSESS result to its trace NOW (not only in the finalize
        # batch), so scores show up in Langfuse as the scan progresses. Item 2 — a file that could
        # not be assessed gets an ERROR-level span so it stands out in the trace list instead of
        # looking like a clean discover-only trace. Both best-effort — tracing never breaks a scan.
        try:
            if str(fdict.get("status")) in ("error", "unanalysable"):
                _lf.file_error_span(ftrace, fdict.get("error") or fdict.get("status"))
            else:
                _emit_realtime_file_assess(scan_id, name, _assess_level(scan_id), user=user)
        except Exception:
            pass
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


# ── Drive credential failures that are true of the SCAN, not of one file ──────────────────
#
# Every download in a scan uses the same credential, so when the credential is the problem the
# first file's failure has already decided the other N-1. The fan-out did not know that: each
# file ran its own download, MediaIoBaseDownload retried it five times, and each one landed as
# its own 'error' record. A 77-file estate spent ~460 HTTP requests establishing one fact, and
# then reported it as 77 unreadable documents rather than as one unusable credential.
#
# Observed live 2026-07-31 on scan f529ed607a26 (77 files, awaiting Assess). The deployed ADC
# credential is a stock `gcloud auth application-default login` grant — openid, email,
# cloud-platform, sqlservice.login — with no Drive scope at all, so every Drive call returns
# 403 "Request had insufficient authentication scopes". Nothing in the product said so: 403 was
# not classified, and the operator-facing outcome would have been an estate of 77 documents ACP
# claimed it could not read.
#
# 401 was already classified here, and its comment already says the condition is scan-wide
# ("on a long scan every remaining file fails with 401") — it just never acted on that.
_DRIVE_STOP_KEY = "drive_auth_stop:%s"


def drive_auth_failure(exc: Exception) -> str | None:
    """The operator-facing reason this Drive call failed, when no other file will fare better.

    Returns None for an ordinary per-file failure (a corrupt document, a file over the download
    cap, a transient 5xx) — those are genuinely about that one file and must not stop a scan.

    The two that ARE scan-wide:
      * 401 / Invalid Credentials — a GIS access token expired mid-scan (they live ~1h and
        cannot be refreshed server-side).
      * 403 insufficient scopes — the credential is valid and simply was not granted Drive.
        Distinct from a 403 on ONE file (`insufficientFilePermissions`), which is that file's
        own sharing and leaves the rest of the scan perfectly readable.
    """
    msg = f"{type(exc).__name__}: {exc}"
    low = msg.lower()
    if "401" in msg or "Invalid Credentials" in msg or "authError" in msg:
        return ("Drive authorization expired mid-scan — sign in again and re-run the scan "
                "to cover this file")
    scope_403 = ("insufficient authentication scopes" in low
                 or "access_token_scope_insufficient" in low
                 or "insufficientpermissions" in low)
    if scope_403 and "insufficientfilepermissions" not in low:
        return ("The server's Google credential is not authorized for Drive — it needs the "
                "drive.readonly scope. Re-authorize ADC and restart the worker; no file in "
                "this scan can be read until then")
    return None


def _stop_scan_downloads(scan_id: str, reason: str) -> None:
    """Record that this scan's credential is unusable, so the remaining files skip the download.

    A marker rather than an exception: count_files_done() counts file_records against
    scan_runs.files, so a file that never persists a row leaves the scan permanently
    unfinalized — the UI sits at N/M with no error, which is the "stuck scan" false alarm this
    codebase has already produced three times in one day. Every file still gets its row; what
    it no longer gets is a doomed download.
    """
    try:
        if not core.store.get_setting(_DRIVE_STOP_KEY % scan_id):
            core.store.set_setting(_DRIVE_STOP_KEY % scan_id, reason)
            print(f"[scan] {scan_id}: halting downloads — {reason}", flush=True)
            core.store.log_decision("system", "scan.drive_unusable", scan_id=scan_id,
                                    detail=reason[:200])
    except Exception:
        pass    # a marker that cannot be written must not take the scan down with it


def drive_download_halted(scan_id: str) -> str | None:
    """The reason downloads were halted for this scan, or None to proceed."""
    try:
        return core.store.get_setting(_DRIVE_STOP_KEY % scan_id) or None
    except Exception:
        return None


def clear_drive_stop(scan_id: str) -> None:
    """Forget a previous credential failure so a re-run actually retries.

    Called from _enqueue_analysis, the ONE choke point both the immediate scan path and the
    deferred Assess path go through. Without this, fixing the credential and pressing Assess
    again on the same scan id would short-circuit every file against a stale marker — the fix
    would look like it had not worked.
    """
    try:
        core.store.set_setting(_DRIVE_STOP_KEY % scan_id, "")
    except Exception:
        pass


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
    pii = bool(payload.get("pii", False))
    user = payload.get("user")
    items = payload.get("items", [])
    toks = core.get_scan_tokens(scan_id)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    svc = _make_svc(source, toks)
    rubric_hash = core.active_rubric().hash
    incremental = bool(payload.get("incremental", True))
    try:
        workers = max(1, int(_os.environ.get("ACP_SCAN_BATCH_WORKERS", "4") or "4"))
    except ValueError:
        workers = 4

    def _run_one(it):
        _analyse_and_persist_one(scan_id, it, source, pii, svc, toks, now, _lf, user=user,
                                 rubric_hash=rubric_hash, incremental=incremental)

    if workers <= 1 or len(items) <= 1:
        for it in items:
            _run_one(it)
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
            futures = [ex.submit(_run_one, it) for it in items]
        # collect results after all complete; re-raise first exception if any
        exc = None
        for f in futures:
            try:
                f.result()
            except Exception as e:
                if exc is None:
                    exc = e
        if exc is not None:
            raise exc
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
    pii = bool(payload.get("pii", False))
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
    # ADR 0020 — for a DEFERRED scan the Assess-phase analysis just completed, so this IS the
    # assessment: stamp assessed_at + build the assess trace now (in the immediate-scan model the
    # user runs Assess manually later, so we don't auto-mark there). assess_params exists only for
    # deferred scans, so this gate never fires on a normal scan.
    if core.store.get_setting(f"assess_params:{scan_id}"):
        core.store.mark_assessed(scan_id, now)
        core.store.enqueue_job("assess_trace", {"scan_id": scan_id, "level": "AA"}, scan_id=scan_id)
    core.clear_scan_tokens(scan_id)


def _assess_level(scan_id: str) -> str:
    """The WCAG conformance target this scan is assessed against — the deferred-Assess param when
    present, else the AA legal default. Used to write per-file assess results in real time."""
    try:
        lvl = _json.loads(core.store.get_setting(f"assess_params:{scan_id}") or "{}").get("level")
        if lvl:
            return str(lvl)
    except Exception:
        pass
    return "AA"


def _file_assess_from_traces(rule_rows: list[dict], level: str):
    """(sc_counts, outcomes, conformant) for ONE file from its scan_rule_traces rows — the same
    reduction ensure_assess_trace does per file, factored out so the real-time and finalize paths
    cannot diverge. `conformant` = no FAIL at or below the target WCAG level."""
    RANK = {"A": 1, "AA": 2, "AAA": 3}
    target = RANK.get(str(level).upper(), 2)
    sc_counts: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    blocking = False
    for r in rule_rows:
        oc = r.get("outcome") or "NOT_EVALUATED"
        outcomes[oc] = outcomes.get(oc, 0) + 1
        if r.get("outcome") == "FAIL":
            sc_counts[r["rule_id"]] = r.get("finding_count") or 1
            if RANK.get((r.get("level") or "A").upper(), 1) <= target:
                blocking = True
    return sc_counts, outcomes, (not blocking)


def _emit_file_assess(scan_id: str, fname: str, level: str, *, sc_counts, outcomes, conformant,
                      score, pii_payload, remediation, user=None) -> None:
    """Write ONE file's assessment to its Langfuse trace: the Assess span (level-flagged so a
    non-conformant file stands out), its per-rule ✓/✗ children, the file score, and the trace-level
    verdict/output. Shared by the finalize pass (ensure_assess_trace) and the real-time per-file
    path so both write identically; Langfuse upserts by id, so calling it twice just refreshes."""
    import lf as _lf
    from store import RULE_CATALOG
    ftrace = _lf.file_trace(scan_id, fname, user=user)
    aspan = _lf.assess_span(ftrace, level, blocking=(not conformant), findings=bool(sc_counts))
    if sc_counts:
        _lf.rule_spans(aspan, sc_counts, RULE_CATALOG, filename=fname, scan_id=scan_id, user=user)
    aspan.end(output={"conformant": conformant, "failing_criteria": len(sc_counts or {})})
    _lf.file_score(scan_id, fname, score)
    _lf.file_assessment_result(scan_id, fname, score=score, conformant=conformant, level=level,
                               failing_criteria=sc_counts, outcomes=outcomes,
                               pii=pii_payload, remediation=remediation)
    # Outcome tags so the native Langfuse list filters by result / PII, not only document + format.
    # result:fail when a finding blocks conformance; needs-review when there are findings or review
    # items that don't block; pass when clean. This is the authoritative tag write (it re-includes
    # the base + rule-fail tags, since Langfuse replaces a trace's tags).
    result = ("fail" if not conformant
              else "needs-review" if (sc_counts or (outcomes or {}).get("REVIEW")) else "pass")
    _lf.set_outcome_tags(scan_id, fname, user, result=result,
                         pii_flagged=bool(pii_payload and pii_payload.get("flagged")),
                         failing_rule_ids=list((sc_counts or {}).keys()))


def _emit_realtime_file_assess(scan_id: str, fname: str, level: str, user=None) -> None:
    """Item 1: write a file's assessment to its trace as soon as it is scored, so scores appear in
    Langfuse AS a scan runs instead of only in one batch at finalize (the mid-run blind spot).
    Minimal on purpose — score / conformance / failing criteria / per-check breakdown from the
    file's own rule traces; the finalize pass adds PII + the complete record and upserts over it.
    Best-effort: observability must never break the scan, and it does no work when tracing is off."""
    import lf as _lf
    if not _lf.enabled():
        return
    rows = core.store.get_scan_traces(scan_id, file=fname)
    if not rows:
        return   # not scored yet (discover-only / errored) — nothing to assess
    rec = core.store.get_file_record(scan_id, fname) or {}
    sc_counts, outcomes, conformant = _file_assess_from_traces(rows, level)
    remediation = {"remediated": bool(rec.get("remediated_at")),
                   "written_back": bool(rec.get("drive_write_url")),
                   "published": bool(rec.get("published_at"))}
    _emit_file_assess(scan_id, fname, level, sc_counts=sc_counts, outcomes=outcomes,
                      conformant=conformant, score=rec.get("score"), pii_payload=None,
                      remediation=remediation, user=user)


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
    outcomes_by_file: dict[str, dict] = {}     # file → {PASS/FAIL/REVIEW/NOT_EVALUATED: count}
    blocking_files: set[str] = set()           # files with a failure at/below the target level
    for r in rows:
        f = r["file"]
        by_file.setdefault(f, {})
        oc = outcomes_by_file.setdefault(f, {})
        outcome = r.get("outcome") or "NOT_EVALUATED"
        oc[outcome] = oc.get(outcome, 0) + 1
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
    # PII flag per file — fetched once, grouped by file. `pii_type` is a CATEGORY ('us_ssn',
    # 'email_address'), never the value (the same `sensitive_data_types` the PII span already
    # sends); masked samples are deliberately not read here.
    pii_by_file: dict[str, dict] = {}
    for p in core.store.list_pii(scan_id):
        e = pii_by_file.setdefault(p["file"], {"types": set(), "findings": 0, "critical": False})
        if p.get("pii_type"):
            e["types"].add(p["pii_type"])
        e["findings"] += int(p.get("count") or 0)
        if str(p.get("severity") or "").lower() in ("critical", "high"):
            e["critical"] = True
    for f in (res or {}).get("files", []):
        fname = f["file"]
        sc_counts = by_file.get(fname) or {}
        if sc_counts:
            conformant = fname not in blocking_files
            # Seed a remediation_state row for every violation newly seen at Assess time.
            ident = identities.get(fname) or {}
            try:
                doc_id = resolve_doc_id(source, ident.get("drive_file_id"), fname, ident.get("checksum"))
                for rule_id in sc_counts:
                    core.store.seed_remediation_state(doc_id, rule_id, scan_id)
            except Exception:
                pass
        else:
            conformant = not bool(f.get("issues"))
        pe = pii_by_file.get(fname)
        pii_payload = ({"flagged": True, "types": sorted(pe["types"]),
                        "findings": pe["findings"], "critical": pe["critical"]}
                       if pe else {"flagged": False, "types": [], "findings": 0, "critical": False})
        remediation = {"remediated": bool(f.get("remediated_at")),
                       "written_back": bool(f.get("drive_write_url")),
                       "published": bool(f.get("published_at"))}
        # The Assess span (level-flagged), per-rule ✓/✗ children, file score, and the trace-level
        # verdict — the SAME emit the real-time per-file path uses, so a scan's finalize pass and
        # its incremental writes can never disagree. Structured only (see lf.file_assessment_result).
        _emit_file_assess(scan_id, fname, level, sc_counts=sc_counts,
                          outcomes=outcomes_by_file.get(fname), conformant=conformant,
                          score=f.get("score"), pii_payload=pii_payload,
                          remediation=remediation, user=owner)
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
    pii = bool(payload.get("pii", False))
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


# ── Applying reviewer-approved content (WCAG 1.1.1, Office) ───────────────────────────────
_OFFICE_ALT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# The criteria the link-text write-back may CREDIT, per format — never the union.
#
# Credit is granted by re-scanning the written bytes and finding the criterion absent
# (_apply_one_value_kind). A criterion no detector emits for this format is absent from every
# re-scan there will ever be, so crediting it on that evidence proves nothing: the gate passes
# vacuously and the file is certified against a criterion nobody checked. So a criterion
# appears here only where a detector actually emits it for that format — the pairing
# tests/test_applier_detector_parity.py asserts, and the reason 2.4.9 (duplicate display text,
# docx_checks/pptx_checks) is not claimed for xlsx, which has no such check.
_LINK_SCS_BY_EXT = {
    "docx": ("2.4.4", "2.4.9"),
    "pptx": ("2.4.4", "2.4.9"),
    "xlsx": ("2.4.4",),
}
_OFFICE_LINK_EXTS = tuple(_LINK_SCS_BY_EXT)

# The text-span lanes: a sentence rewrite (1.3.3) and a language mark (3.1.2), both keyed by a
# prose prefix rather than a part#rId or an href, both written by apply_text_values. Same rule
# as _LINK_SCS_BY_EXT above: a format appears here only where a detector actually emits the
# criterion, so the re-scan credit means something.
#
# The two lists differ, and the difference is structural rather than a gap in the roadmap.
# 1.3.3 is a text rewrite, which every Office format can carry. 3.1.2 needs somewhere to
# record a language, and SpreadsheetML's rich-text run properties have no language element at
# all — so an xlsx language lane could never clear its criterion and would strand every
# approval it accepted. xlsx is therefore absent from _LANGUAGE_EXTS on purpose.
_SENSORY_EXTS = ("docx", "pptx", "xlsx")
_LANGUAGE_EXTS = ("docx", "pptx")
# 2.4.6 structure labels: sheet tab and table column renames (xlsx only).
_STRUCTURE_LABEL_EXTS = ("xlsx",)

# The lanes that exist only for PDF: figure alt (`pdf:fig:…` → /Alt) and form-field accessible
# names (`pdf:field:…` → /TU), both written by remediate_pdf.apply_pdf_approved.
_PDF_APPLY_EXTS = ("pdf",)

# 4.1.2 accessible names, per format. PDF writes /TU on an AcroForm field
# (remediate_pdf.apply_pdf_field_name); Word writes w:alias on a content control
# (apply_field_name.apply_docx_field_name) — different writers, one store getter, because
# both answer the same approved-value shape. pptx/xlsx have no content-control equivalent,
# so their 4.1.2 signal stays the ActiveX/OLE advisory no static write can resolve.
_FIELD_NAME_EXTS = ("pdf", "docx")

# Every format an approved value can actually be WRITTEN into — the format scope
# _apply_approved_values gates on, derived from the per-lane constants rather than restated, so
# the two can never disagree. scripts/gen_matrix_coverage.py reads it to derive the matrix's
# applier surface, so a format here with no real writer behind it would over-claim.
_APPLY_VALUE_EXTS = tuple(_OFFICE_ALT_MIME) + _PDF_APPLY_EXTS


def _apply_one_value_kind(
        *, scan_id: str, filename: str, working: bytes,
        values: dict[str, str], scs_to_clear: set[str],
        write_fn, diff_rule_id: str, credit_rule_ids: tuple[str, ...],
        noun: str, job: dict, extra_work: bool = False) -> tuple[bytes, bool]:
    """Shared write → verify → credit sequence for one kind of approved value (alt text or
    link text) applied on top of `working`. Returns (new_working, uploaded_this_kind).

    The values are NOT credited on a successful write. They are credited when a re-scan of the
    written bytes shows the criterion no longer failing, exactly as `verified_diffs` credits an
    automatic fix. A write that does not clear the criterion leaves the row unapplied and the
    file uncertified, which is the honest outcome: something about the document still fails.

    extra_work: this lane's `write_fn` carries approved work of its own that is not expressible
    as {locator: text} — today, the decorative markings closed over by the alt lane, whose whole
    point is that they write no text. Without it a file whose only approved 1.1.1 decision was
    "decorative" short-circuits here and the marking never reaches the document.
    """
    if not values and not extra_work:
        return working, False

    _phase(job, f"writing the approved {noun}")
    fixed, applied, unresolved = write_fn(working, values)
    if unresolved:
        # A locator that no longer resolves means the reviewer approved a value for content
        # this document no longer has. Never guess at different content — record and move on.
        core.store.log_decision(
            "system", "apply.unresolved", scan_id=scan_id, file=filename,
            detail=f"{len(unresolved)} approved {noun} value(s) had no matching content: "
                   + ", ".join(unresolved[:5]))
    if not applied:
        return working, False

    _phase(job, f"re-verifying the corrected copy ({noun})")
    residual = _verify_residual_scs(fixed, filename)
    cleared = residual is None or not (scs_to_clear & residual)
    if not cleared:
        # The value went in but the criterion still fails (content we never saw, or the engine
        # reads it differently). Credit nothing: the row stays unapplied and the file stays
        # uncertified, which is what is actually true of the document.
        core.store.log_decision(
            "system", "apply.unverified", scan_id=scan_id, file=filename,
            detail=f"wrote {len(applied)} {noun} value(s) but {sorted(scs_to_clear)} still fails on re-scan")
        return working, False

    try:
        existing = core.store.get_remediation_diffs(scan_id, filename) or []
        core.store.record_remediation_diffs(scan_id, filename, list(existing) + [
            {"rule_id": diff_rule_id, "before": a["before"], "after": a["after"],
             "note": f"approved by a reviewer · {a['locator']}"} for a in applied])
    except Exception:
        pass

    for rule_id in credit_rule_ids:
        for item_id in core.store.approved_unapplied_item_ids(scan_id, filename, rule_id):
            core.store.mark_row_applied(item_id)
    core.store.log_decision(
        "system", "apply.applied", scan_id=scan_id, file=filename,
        detail=f"wrote {len(applied)} reviewer-approved {noun} value(s); "
               f"{sorted(scs_to_clear)} cleared on re-scan")
    return fixed, True


@handler("apply_approved_values")
def _apply_approved_values(payload: dict, job: dict) -> None:
    """Write reviewer-approved content (alt text, link text, PDF form-field names) into the
    remediated copy, then verify it.

    This closes the remediate → review → publish loop. Approving a 1.1.1, 2.4.4/2.4.9 or 4.1.2
    item used to store the value as evidence and stop: nothing wrote it in, so
    store.mark_file_compliant_if_reviewed correctly refused to certify — leaving the file
    approved but permanently unpublishable.

    Each criterion is its own write → verify → credit lane (_apply_one_value_kind), because a
    lane may only credit what its own re-scan observed. They run in sequence on the same
    `working` bytes, so a file with both alt text and field names approved gets one upload.

    payload: {scan_id, file}
    """
    scan_id = payload.get("scan_id") or job.get("scan_id")
    filename = payload.get("file")
    if not (scan_id and filename):
        raise FatalJobError("apply_approved_values job missing scan_id/file")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _APPLY_VALUE_EXTS:
        # No applier for this format. Say so rather than silently succeeding: the row stays
        # unapplied, so the file stays out of Publish.
        core.store.log_decision("system", "apply.unsupported", scan_id=scan_id, file=filename,
                                detail=f".{ext}: no approved-value applier for this format")
        return

    alt_values = core.store.approved_alt_values(scan_id, filename)
    # Images a reviewer resolved as DECORATIVE. Office only: the marking is an OOXML extLst
    # marker (apply_alt), and the PDF equivalent — re-tagging the figure as an /Artifact — is a
    # structure edit no writer here performs, so on PDF the exception stays a recorded judgement.
    deco_locators = (core.store.approved_decorative_locators(scan_id, filename)
                     if ext in _OFFICE_ALT_MIME else [])
    link_values = core.store.approved_link_values(scan_id, filename) if ext in _OFFICE_LINK_EXTS else {}
    field_values = (core.store.approved_field_values(scan_id, filename)
                    if ext in _FIELD_NAME_EXTS else {})
    sensory_values = (core.store.approved_sensory_values(scan_id, filename)
                      if ext in _SENSORY_EXTS else {})
    language_values = (core.store.approved_language_values(scan_id, filename)
                       if ext in _LANGUAGE_EXTS else {})
    structure_label_values = (core.store.approved_structure_label_values(scan_id, filename)
                              if ext in _STRUCTURE_LABEL_EXTS else {})
    if not (alt_values or deco_locators or link_values or field_values
            or sensory_values or language_values or structure_label_values):
        return                                   # nothing approved awaiting a write

    import blob as _blob
    owner = (core.store.get_scan(scan_id) or {}).get("run", {}).get("owner_email")
    _phase(job, "fetching the corrected copy")
    working = _blob.download_remediated(owner, scan_id, filename)
    if not working:
        # The remediated copy is what we edit; the original is never modified. Without it
        # there is nothing to write into, and pretending otherwise would strand the reviewer.
        core.store.log_decision("system", "apply.no_remediated_copy", scan_id=scan_id,
                                file=filename, detail="no stored remediated copy to write into")
        return

    # Office images carry part#rId locators written by apply_alt; PDF figures carry the
    # `pdf:fig:{page}:{seq}` locator minted by remediate_pdf and are written by
    # apply_pdf_approved. Same (bytes, {locator: value}) -> (fixed, applied, unresolved)
    # contract either way, so only the writer differs.
    if ext in _PDF_APPLY_EXTS:
        from remediate_pdf import apply_pdf_approved
        alt_write_fn = apply_pdf_approved
    else:
        from apply_alt import apply_alt_text
        # Decorative markings go through the SAME lane as the descriptions, not one of their own.
        # A lane only credits what its own re-scan observed, and a re-scan cannot see 1.1.1 clear
        # while the other lane's images are still unresolved — split in two, each would verify
        # against the other's unfinished work and neither would ever be credited.
        alt_write_fn = lambda d, v: apply_alt_text(d, v, decorative=deco_locators)  # noqa: E731
    working, alt_uploaded = _apply_one_value_kind(
        scan_id=scan_id, filename=filename, working=working,
        values=alt_values, extra_work=bool(deco_locators),
        scs_to_clear={"1.1.1"}, write_fn=alt_write_fn,
        diff_rule_id="1.1.1", credit_rule_ids=("1.1.1",), noun="description", job=job)

    # 4.1.2 form-field accessible names. PDF keys on `pdf:field:…` and writes /TU; Word keys
    # on `docx:sdt:…` and writes w:alias. One lane, one criterion, the writer chosen by format.
    # Run as its own lane because it verifies and credits a DIFFERENT criterion: folding it
    # into the alt lane would credit 1.1.1 for a field name, and clear 4.1.2 on no evidence.
    field_uploaded = False
    if ext in _FIELD_NAME_EXTS and field_values:
        if ext in _PDF_APPLY_EXTS:
            from remediate_pdf import apply_pdf_approved
            field_write_fn = apply_pdf_approved
        else:
            from apply_field_name import apply_docx_field_name
            field_write_fn = apply_docx_field_name
        working, field_uploaded = _apply_one_value_kind(
            scan_id=scan_id, filename=filename, working=working,
            values=field_values, scs_to_clear={"4.1.2"}, write_fn=field_write_fn,
            diff_rule_id="4.1.2", credit_rule_ids=("4.1.2",), noun="field name", job=job)

    link_uploaded = False
    if link_values:
        from apply_link_text import apply_link_text
        link_write_fn = lambda data, values: apply_link_text(data, ext, values)  # noqa: E731
        # Every approved link value is WRITTEN whichever criterion it came from — the text is
        # better either way. Only the crediting is narrowed to what this format can re-verify.
        link_scs = _LINK_SCS_BY_EXT.get(ext, ())
        working, link_uploaded = _apply_one_value_kind(
            scan_id=scan_id, filename=filename, working=working,
            values=link_values, scs_to_clear=set(link_scs), write_fn=link_write_fn,
            diff_rule_id="2.4.4", credit_rule_ids=link_scs, noun="link text", job=job)

    # 1.3.3 sensory rewrites and 3.1.2 language marks (Word). Two lanes, not one, even though a
    # single module writes both: each lane may only credit the criterion its OWN re-scan saw
    # clear, and folding them together would credit 1.3.3 for a language mark.
    sensory_uploaded = False
    if sensory_values:
        from apply_text_values import apply_sensory_rewrite
        sensory_write_fn = lambda d, v: apply_sensory_rewrite(d, ext, v)  # noqa: E731
        working, sensory_uploaded = _apply_one_value_kind(
            scan_id=scan_id, filename=filename, working=working,
            values=sensory_values, scs_to_clear={"1.3.3"}, write_fn=sensory_write_fn,
            diff_rule_id="1.3.3", credit_rule_ids=("1.3.3",), noun="rewrite", job=job)

    language_uploaded = False
    if language_values:
        from apply_text_values import apply_language_parts
        language_write_fn = lambda d, v: apply_language_parts(d, ext, v)  # noqa: E731
        working, language_uploaded = _apply_one_value_kind(
            scan_id=scan_id, filename=filename, working=working,
            values=language_values, scs_to_clear={"3.1.2"}, write_fn=language_write_fn,
            diff_rule_id="3.1.2", credit_rule_ids=("3.1.2",), noun="language mark", job=job)

    structure_label_uploaded = False
    if structure_label_values:
        from apply_xlsx_labels import apply_xlsx_labels
        working, structure_label_uploaded = _apply_one_value_kind(
            scan_id=scan_id, filename=filename, working=working,
            values=structure_label_values, scs_to_clear={"2.4.6"},
            write_fn=apply_xlsx_labels,
            diff_rule_id="2.4.6", credit_rule_ids=("2.4.6",),
            noun="structure label", job=job)

    if not (alt_uploaded or link_uploaded or field_uploaded
            or sensory_uploaded or language_uploaded or structure_label_uploaded):
        return

    _phase(job, "storing the corrected copy")
    _blob.upload_remediated(owner, scan_id, filename, working, _OFFICE_ALT_MIME.get(ext, "application/pdf"))

    # The file may now be fully resolved. This is the same seam routes/hitl.py runs on every
    # approval; it was returning False for this file until the values actually landed.
    try:
        if core.store.mark_file_compliant_if_reviewed(scan_id, filename):
            core.store.log_decision(
                "system", "revalidate.certified", scan_id=scan_id, file=filename,
                detail="all findings resolved (auto-fixed + approved values written) — advanced to Publish")
    except Exception:
        pass
