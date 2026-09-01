"""Slice 4: an approved caption file can be CORRECTED and can LEAVE the system.

THE DEFECT THIS FIXES IS ONE SLICE 3 SHIPPED, and naming it plainly is the point of this file.

#1177 made the caption draft `explain_only=True`. That was right about the certify gate — no
applier will ever write a caption track into a customer's .mp4, so counting the approved value as
"content the file does not yet carry" would block certification for good on a correct approval.
It was wrong about everything else, because `explain_only` in this codebase means two things at
once and only one of them is true here:

    api/store.py:_row_approved_values   skip it — no applier will write it        TRUE for captions
    EvidenceCard.jsx:explainOnly        read-only; confirming sends no value      FALSE for captions

The consequences, measured on `origin/main` at 709d883b:

  * `editable = !explainOnly && …` — the reviewer gets a READ-ONLY box. The card ACP writes says
    "Check the wording: speech recognition mishears names, numbers and homophones", and then
    offers no way to change a word of it.
  * `approvedValues = (… && !explainOnly && …) ? … : null` and `finalValue = … null` — confirming
    stores NOTHING. Even if the box were editable, the correction would be discarded.
  * Nothing anywhere reads a caption value back out. `git grep` for a download or export of a
    proposal value: no hits. The approved WebVTT existed only as the machine's draft, inside a
    JSON blob, reachable by no route.

So slice 3 delivered a caption file nobody could correct and nobody could obtain. The finding
could be signed off; the artefact could not be produced. That is a worse failure than no draft at
all, because the sign-off looks like the problem was solved.

THE MISSING DISTINCTION is between two things `explain_only` conflates:

    a CONFIRMATION   a derived PDF structure map. The reviewer agrees it is right. The value is
                     evidence; there is nothing to author and nothing to hand back.
    a COMPANION      a caption file. The reviewer EDITS it, and the edited text is the
                     DELIVERABLE — a separate file that ships beside the media.

Both are alike in the one way the certify gate cares about (nothing is written into the source
document) and opposite in every way the reviewer cares about. `companion_file` says the second.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "api", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import proposals as prop  # noqa: E402
from store import Store  # noqa: E402

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.400\nWelcome to the quarterly all-hands.\n"


def _caption_proposal(approved_value=None, **kw):
    """A caption proposal as it exists on a stored row.

    `approved_value` is set AFTER construction, because that is how it really arrives:
    `proposal()` never takes one, and `store.approve_proposal_values` writes it onto the JSON
    blob when the reviewer approves. Passing it as a constructor argument (the first draft of
    this helper did) tests a shape the database never holds.
    """
    base = dict(locator="townhall.mp4", before="", proposed_value=VTT,
                rationale="drafted from the soundtrack", source="local speech recognition (tiny)",
                companion_file="townhall.en.vtt", sc="1.2.2")
    base.update(kw)
    p = prop.proposal(**base)
    if approved_value is not None:
        p["approved_value"] = approved_value
    return p


def _row(props, **kw):
    row = {"proposals": props, "evidence": [], "approved_value": "", "resolution": None}
    row.update(kw)
    return row


# ── the shape ────────────────────────────────────────────────────────────────────────────────
def test_a_proposal_can_declare_itself_a_companion_file():
    """The flag carries the FILENAME, not just a boolean.

    A caption file has to be delivered under a name a player will find — `talk.en.vtt` beside
    `talk.mp4`. A boolean would push that decision to whichever consumer happened to write the
    file first, and two consumers inventing it separately is how the same artefact ends up with
    two names.
    """
    p = _caption_proposal()
    assert p["companion_file"] == "townhall.en.vtt"
    assert "explain_only" not in p, (
        "a companion file is not explain-only: the reviewer authors its content, and the value "
        "is handed back rather than merely confirmed")


def test_the_caption_proposer_produces_a_companion_not_a_confirmation(tmp_path, monkeypatch):
    """The whole point, at the source. Slice 3's proposer set explain_only."""
    import media
    monkeypatch.setattr(media, "media_kind", lambda name: "video")
    monkeypatch.setattr(media, "asr_available", lambda: True)
    monkeypatch.setattr(media, "probe", lambda p: media.MediaInfo(
        duration=5.0, has_audio=True, has_video=True, has_captions=False))
    monkeypatch.setattr(media, "extract_audio", lambda src, dest: dest)
    monkeypatch.setattr(media, "transcribe", lambda *a, **kw: media.Transcript(
        segments=[{"start": 0.0, "end": 2.4, "text": "Welcome to the all-hands."}],
        language="en", duration=2.4, model="stub-tiny"))

    clip = tmp_path / "townhall.mp4"
    clip.write_bytes(b"\x00")
    props = prop.propose_captions(clip, ".mp4")
    assert props, "the stubbed pipeline produced no proposal — the control failed"
    p = props[0]
    assert p.get("companion_file") == "townhall.en.vtt", (
        f"the caption draft is not declared a companion file: {p.get('companion_file')!r}")
    assert not p.get("explain_only"), (
        "still explain-only, so the reviewer cannot correct a transcription the card itself "
        "tells them to check")


def test_an_audio_transcript_is_a_txt_companion(tmp_path, monkeypatch):
    """1.2.1's deliverable is prose, not cues, so it must not be handed back as a .vtt — a
    player offered a .vtt of flowing text with no timings shows nothing."""
    import media
    monkeypatch.setattr(media, "media_kind", lambda name: "audio")
    monkeypatch.setattr(media, "asr_available", lambda: True)
    monkeypatch.setattr(media, "probe", lambda p: media.MediaInfo(
        duration=5.0, has_audio=True, has_video=False, has_captions=False))
    monkeypatch.setattr(media, "extract_audio", lambda src, dest: dest)
    monkeypatch.setattr(media, "transcribe", lambda *a, **kw: media.Transcript(
        segments=[{"start": 0.0, "end": 2.4, "text": "Welcome."}],
        language="en", duration=2.4, model="stub-tiny"))

    pod = tmp_path / "interview.mp3"
    pod.write_bytes(b"\x00")
    p = prop.propose_captions(pod, ".mp3")[0]
    assert p["companion_file"] == "interview.en.txt", p["companion_file"]


# ── the certify gate: unchanged, and that is the half slice 3 got right ──────────────────────
def test_a_companion_value_still_never_blocks_certification():
    """The property `explain_only` was reached for. No applier writes a .vtt into an .mp4, so an
    approved caption value is not content the file "does not yet carry" — counting it would wedge
    the file permanently on an approval that was entirely correct."""
    row = _row([_caption_proposal(approved_value=VTT)])
    assert Store._row_approved_values(row) == {}, (
        "a companion file entered the applier's work list; nothing will ever write it into the "
        "media, so the file could never certify")


def test_a_companion_only_row_owes_the_document_nothing():
    """The second half of the same gate. `_row_is_explain_only` made such a row "owe nothing"; a
    companion row must be treated the same way, or the legacy approved_value column re-opens the
    dead end from the other side."""
    row = _row([_caption_proposal(approved_value=VTT)], approved_value=VTT)
    assert Store._row_owes_no_document_content(row) is True


def test_a_row_that_really_does_owe_content_is_untouched():
    """The control. Widening the "owes nothing" predicate is exactly the change that could
    silently let a genuine alt-text row certify unwritten, so it is asserted in both directions."""
    alt = prop.proposal(locator="image1.png", before="", proposed_value="A bar chart",
                        rationale="vision", source="llava", sc="1.1.1")
    alt["approved_value"] = "A bar chart of Q3 revenue"
    row = _row([alt])
    assert Store._row_owes_no_document_content(row) is False
    assert Store._row_approved_values(row) == {"image1.png": "A bar chart of Q3 revenue"}


# ── the deliverable can be obtained ──────────────────────────────────────────────────────────
def test_the_approved_text_is_what_is_delivered_not_the_draft():
    """A reviewer who corrected "all-hands" to "All Hands" must get THEIR file. Falling back to
    the draft when an approved value exists would hand back the machine's version of a document a
    person had already fixed — and would do it silently, because both are valid WebVTT."""
    corrected = VTT.replace("all-hands", "All Hands")
    row = _row([_caption_proposal(approved_value=corrected)])
    files = Store._row_companion_files(row)
    assert files == {"townhall.en.vtt": corrected}


def test_an_unapproved_companion_falls_back_to_the_draft():
    """A reviewer who edits nothing has agreed to exactly the draft — the same reasoning
    `_row_approved_values` gives for its own fallback."""
    row = _row([_caption_proposal()])
    assert Store._row_companion_files(row) == {"townhall.en.vtt": VTT}


def test_a_proposal_with_no_companion_flag_yields_no_file():
    """Only a declared companion is deliverable. Without this an alt-text value would be offered
    for download as a file, which is neither what it is nor what anyone asked for."""
    alt = prop.proposal(locator="image1.png", before="", proposed_value="A bar chart",
                        rationale="vision", source="llava", sc="1.1.1")
    assert Store._row_companion_files(_row([alt])) == {}


def test_a_companion_name_cannot_escape_its_directory():
    """The filename reaches a Content-Disposition header and, later, a path. It is derived from
    the media file's own name, which comes from a customer's estate — so it is attacker-adjacent
    input, and a `../` in it would be a path traversal handed to whatever writes the file.
    Sanitised where it is READ, not only where it is built, because the JSON blob is the boundary:
    a row written by an older build has not been through today's builder.
    """
    bad = _caption_proposal(companion_file="../../etc/passwd")
    files = Store._row_companion_files(_row([bad]))
    assert files == {"passwd": VTT}, files
    nested = _caption_proposal(companion_file="a/b/talk.vtt")
    assert list(Store._row_companion_files(_row([nested]))) == ["talk.vtt"]


def test_an_empty_or_missing_name_is_not_deliverable():
    for name in ("", "   ", None):
        assert Store._row_companion_files(_row([_caption_proposal(companion_file=name)])) == {}


# ── the reviewer can edit it ─────────────────────────────────────────────────────────────────
# PINNED IN VITEST, NOT HERE — frontend/src/companionFile.test.jsx.
#
# Two tests lived here that read EvidenceCard.jsx out of the backend suite, and a bite check
# showed why that was worth undoing rather than tightening. One asserted `"const companionRow" in
# CARD`; replacing the predicate's whole right-hand side with `false` left it green, because the
# NAME survived. The other asserted `"companionRow" not in body or "!companionRow" not in body`,
# which is true of every possible string — a tautology dressed as a guard.
#
# The vitest file asserts the complete expressions (the `.every((p) => p.companion_file)` body,
# the `editable` line containing `companionRow` and not `!companionRow`, the `approvedValues` gate
# excluding it) and runs in the job that owns the frontend. A weaker second copy in another
# language is not defence in depth; it is a guard that reports green while the thing it names is
# gone, which is the shape this repo has paid for more than once.


# ── the artefact can leave the system ───────────────────────────────────────────────────────
# GET /hitl/queue/{id}/companion — the half of "export companion caption/transcript files" that
# #1177 left undone. Before this the approved WebVTT existed only inside a JSON column that no
# route read back: the finding could be signed off and the file could not be obtained.

@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    import tempfile
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "companion.db")
    return store_mod.Store()


@pytest.fixture()
def client(st, monkeypatch):
    import core as core_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import hitl as hitl_routes
    monkeypatch.setattr(core_mod, "store", st)
    app = FastAPI()
    app.include_router(hitl_routes.router)
    return TestClient(app)


def _queued(st, props, sid="s1", f="townhall.mp4", rule="1.2.2"):
    st.init_scan_run(sid, "drive", 1, "t0", "r", "h")
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,"
            "remediated_at) VALUES(%s,%s,'av','fail',60,0,0,'2026-09-01T00:00:00')", (sid, f))
    st.queue_hitl_deferral(sid, f, "captions needed", 1, rule_id=rule)
    item = next(i for i in st.list_hitl_queue(scan_id=sid))
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE hitl_queue SET proposals=%s WHERE id=%s",
                       (json.dumps(props), item["id"]))
    return item["id"]


def test_the_caption_file_can_be_downloaded(st, client):
    item_id = _queued(st, [_caption_proposal()])
    r = client.get(f"/hitl/queue/{item_id}/companion")
    assert r.status_code == 200, r.text
    assert r.text == VTT, "the bytes handed back are not the caption file"
    assert r.headers["content-disposition"] == 'attachment; filename="townhall.en.vtt"'
    assert r.headers["content-type"].startswith("text/vtt"), (
        f"a player keys off the media type; got {r.headers['content-type']!r}")


def test_the_download_is_the_reviewer_s_corrected_text(st, client):
    corrected = VTT.replace("all-hands", "All Hands")
    item_id = _queued(st, [_caption_proposal(approved_value=corrected)])
    assert client.get(f"/hitl/queue/{item_id}/companion").text == corrected


def test_a_row_with_no_companion_404s_rather_than_returning_an_empty_file(st, client):
    alt = prop.proposal(locator="image1.png", before="", proposed_value="A bar chart",
                        rationale="vision", source="llava", sc="1.1.1")
    item_id = _queued(st, [alt], f="report.docx", rule="1.1.1")
    r = client.get(f"/hitl/queue/{item_id}/companion")
    assert r.status_code == 404, (
        "an empty 200 is indistinguishable from a caption track for a silent video, and a player "
        "handed one shows nothing rather than reporting a problem")


def test_an_unknown_item_404s(client):
    assert client.get("/hitl/queue/nope/companion").status_code == 404


def test_a_transcript_is_served_as_plain_text(st, client):
    item_id = _queued(st, [_caption_proposal(companion_file="interview.en.txt")],
                      f="interview.mp3", rule="1.2.1")
    r = client.get(f"/hitl/queue/{item_id}/companion")
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"].endswith('"interview.en.txt"')


def test_a_stored_traversal_name_cannot_reach_the_header(st, client):
    """The row is the boundary. Nothing a CALLER sends reaches the header — there is no filename
    in the path — but a row could still hold one, from an older build or a proposer added later,
    and this is what stops it being served as written."""
    item_id = _queued(st, [_caption_proposal(companion_file="../../etc/passwd")])
    r = client.get(f"/hitl/queue/{item_id}/companion")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="passwd"'
