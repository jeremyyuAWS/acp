"""A SharePoint remediation job must read the cache, never the Drive client.

THE FAILURE THIS PINS (live 2026-09-04, scan 8b83e9e1ca5c). `_remediate_file` special-cased
`source == "local"` for cached source bytes and let EVERY other source fall through to the Drive
branch. A SharePoint run therefore asked for a Drive token it was never given, and all 147 jobs
died with "no Drive token for this scan (expired/restarted) — re-trigger".

Three things made it expensive rather than merely wrong:

  * The bytes were already there. Assess downloads through Graph and caches the originals
    (ADR 0020, scanner.cache_source_bytes) whatever the source is, so nothing needed downloading.
  * The error named Drive, so it read as an authorization problem with a SharePoint scan — which
    is not a thing — and the "re-trigger" it asks for is what caused the batch to be submitted a
    second time.
  * Nothing failed loudly for an unrecognised source at all; it just became a Drive job.

So the tests below assert the shape, not only the outcome: a SharePoint job must reach the
remediator with the cached bytes AND must never construct a Drive client, an unsupported source
must fail by name, and a SharePoint cache miss must say so rather than borrow Drive's message.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class _ReachedRemediator(Exception):
    """Raised by the stubbed remediator so a test can stop at the point it cares about."""


@pytest.fixture()
def wired(monkeypatch):
    """Everything `_remediate_file` touches before the format branch, stubbed out.

    `_drive_client` is replaced with a tripwire rather than removed: a test that only asserted
    "the job succeeded" would still pass if the job quietly built a Drive client on the way.
    """
    import core
    import handlers

    calls = {"drive_client": 0, "cached": []}

    monkeypatch.setattr(core.store, "is_shadowed_output", lambda sid, f: False)
    monkeypatch.setattr(core.store, "list_auto_fail_rules", lambda sid, f: [])
    monkeypatch.setattr(handlers, "_phase", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_text_findings", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_form_fields", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **k: None)

    def _tripwire(token):
        calls["drive_client"] += 1
        raise AssertionError("a non-Drive remediation job built a Drive client")

    monkeypatch.setattr(handlers, "_drive_client", _tripwire)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    return calls


def _sp_payload(**over):
    p = {"scan_id": "sp-1", "file": "policy.docx", "source": "sharepoint",
         "owner": "demo@example.com", "checksum": "quickxor-abc"}
    p.update(over)
    return p


def test_a_sharepoint_job_remediates_from_the_cached_source_bytes(monkeypatch, wired):
    import handlers
    import scanner
    import remediate_office

    monkeypatch.setattr(scanner, "read_cached_source",
                        lambda sid, name, owner, checksum=None: b"sharepoint-office-bytes")

    def _remediate(path, **kwargs):
        assert path.read_bytes() == b"sharepoint-office-bytes"
        raise _ReachedRemediator()

    monkeypatch.setattr(remediate_office, "remediate_office", _remediate)

    with pytest.raises(_ReachedRemediator):
        handlers._remediate_file(_sp_payload(), {})
    assert wired["drive_client"] == 0, "a SharePoint job must never ask for a Drive token"


def test_a_sharepoint_job_with_no_drive_file_id_is_still_admitted(monkeypatch, wired):
    """The identity guard applies `drive_file_id` to Drive jobs only. A SharePoint job carries a
    Graph item id that means nothing to Drive, and a local one carries no id at all."""
    import handlers
    import scanner
    import remediate_office

    monkeypatch.setattr(scanner, "read_cached_source",
                        lambda sid, name, owner, checksum=None: b"bytes")
    monkeypatch.setattr(remediate_office, "remediate_office",
                        lambda path, **kw: (_ for _ in ()).throw(_ReachedRemediator()))

    with pytest.raises(_ReachedRemediator):
        handlers._remediate_file(_sp_payload(drive_file_id=None), {})


def test_a_checksum_miss_falls_back_to_this_scans_own_cache_key(monkeypatch, wired):
    """The cache is written under the checksum key only when the LISTING carried a checksum.

    A file recorded with a checksum computed later misses that key while its bytes sit under
    {owner}/{scan_id}/{filename}. Reading only the checksum key is a miss that looks exactly like
    "never cached" — and, before this change, sent the job to Drive."""
    import handlers
    import scanner
    import remediate_office

    def _read(sid, name, owner, checksum=None):
        return None if checksum else b"scan-keyed-bytes"

    monkeypatch.setattr(scanner, "read_cached_source", _read)

    def _remediate(path, **kwargs):
        assert path.read_bytes() == b"scan-keyed-bytes"
        raise _ReachedRemediator()

    monkeypatch.setattr(remediate_office, "remediate_office", _remediate)

    with pytest.raises(_ReachedRemediator):
        handlers._remediate_file(_sp_payload(), {})
    assert wired["drive_client"] == 0


def test_a_sharepoint_cache_miss_fails_by_name_not_as_a_missing_drive_token(monkeypatch, wired):
    import handlers
    import scanner

    monkeypatch.setattr(scanner, "read_cached_source", lambda *a, **k: None)

    with pytest.raises(handlers.FatalJobError) as err:
        handlers._remediate_file(_sp_payload(), {})
    message = str(err.value)
    assert "SharePoint" in message and "re-run Assess" in message
    assert "Drive token" not in message, (
        "the Drive message is what sent an operator down an authorization path that did not "
        "exist, and what asked for the re-trigger that doubled the batch")
    assert wired["drive_client"] == 0


def test_an_unsupported_source_fails_explicitly_instead_of_becoming_a_drive_job(monkeypatch, wired):
    import handlers

    with pytest.raises(handlers.FatalJobError) as err:
        handlers._remediate_file(_sp_payload(source="smb"), {})
    assert "unsupported remediation source" in str(err.value)
    assert "'smb'" in str(err.value), "the failure must name the source it could not serve"
    assert wired["drive_client"] == 0


def test_a_sharepoint_media_job_drafts_captions_without_a_drive_token(monkeypatch, wired):
    """The media lane had the same shape: it demanded a Drive token before every download,
    whatever the job's source, so a SharePoint recording could not even be offered a caption
    draft. It reads the cache now, like the document lane."""
    import handlers
    import scanner

    monkeypatch.setattr(scanner, "read_cached_source", lambda *a, **k: b"mp4-bytes")
    seen = {}

    def _propose_captions(path, suffix):
        seen["bytes"] = path.read_bytes()
        return []          # no draft — the point is only that we got the bytes, tokenless

    import proposals
    monkeypatch.setattr(proposals, "propose_captions", _propose_captions)
    monkeypatch.setattr(handlers.core.store, "log_decision", lambda *a, **k: None)

    handlers._remediate_file(_sp_payload(file="townhall.mp4"), {})
    assert seen.get("bytes") == b"mp4-bytes"
    assert wired["drive_client"] == 0
