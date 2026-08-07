"""The Progress Log GENERATOR — the half that renders the public log, as opposed to the CI guard.

`--check` has tests (test_progress_log_guard.py); generation had none, which is how it came to
emit NOTHING AT ALL for months while CI stayed green: CI only runs --check, which never reaches
collect(). #47 repaired that — line-based WCAG parsing, qualified `none` spellings, and
report-and-skip instead of a hard exit — but left generation with no coverage of its own. These
lock in that behaviour, and add the one case #47 did not cover.

That case: an untracked SC declared ALONGSIDE a tracked one killed the whole entry. Three of this
history's eight entries were lost to it (6d48285, a3a5d44, 2caaa6c), each of which names a
criterion the matrix tracks and one it doesn't. Severity follows fixability here exactly as #47
argued for whole entries: fatal under --check, where the trailer can still be corrected; announced
and omitted afterwards, when it cannot.

parse_commit is pure — a git record in, an entry out — so most of this is unit-level. collect()'s
resilience needs a real repository, because that is where git actually is.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
SCRIPT = ACP / "scripts" / "gen_progress_log.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_progress_log", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


glog = _load()


def _record(body: str, sha: str = "abc1234def", subject: str = "fix(x): a change") -> str:
    """One `git log --format=%H\\x1f%aI\\x1f%s\\x1f%b` record."""
    return "\x1f".join([sha, "2026-07-29T06:00:00-07:00", subject, body])


def _parse(body: str, strict: bool = False):
    return glog.parse_commit(_record(body), "owner/repo", strict=strict)


# ── WCAG: line spellings ──────────────────────────────────────────────────────────────────────

def test_comma_separated_scs_on_one_line_are_all_read():
    """Three commits in this history write the trailer this way; every one parsed to zero SCs
    before #47, and then raised 'has a Matrix-Note: but no WCAG: trailer'."""
    e = _parse("WCAG: 1.3.1 (docx), 2.4.6 (docx)\nMatrix-Note: Real note.")
    assert e["scs"] == ["1.3.1", "2.4.6"]


def test_repeated_wcag_lines_still_work():
    """The documented spelling must not regress while the undocumented one is supported."""
    e = _parse("WCAG: 1.1.1 (pdf)\nWCAG: 4.1.2 (pdf)\nMatrix-Note: Real note.")
    assert e["scs"] == ["1.1.1", "4.1.2"]
    assert e["formats"] == ["pdf"]


def test_commas_inside_the_format_list_are_not_confused_with_sc_separators():
    """`(xlsx, pptx)` is one SC with two formats — not two SCs."""
    e = _parse("WCAG: 1.4.11 (xlsx, pptx)\nMatrix-Note: Real note.")
    assert e["scs"] == ["1.4.11"]
    assert e["formats"] == ["xlsx", "pptx"]


def test_a_version_number_in_prose_is_not_harvested_as_an_sc():
    """Item matching stays anchored to WCAG: lines. Scanning the whole body for x.y.z would turn
    any version number in a paragraph into a matrix claim."""
    e = _parse("WCAG: 1.1.1 (pdf)\nMatrix-Note: Bumped docx from 2.4.6 to 3.1.2 in passing.")
    assert e["scs"] == ["1.1.1"]


def test_formats_omitted_means_all_four():
    e = _parse("WCAG: 1.1.1\nMatrix-Note: Real note.")
    assert e["formats"] == list(glog.FORMATS)


# ── "no matrix impact", in the spellings people actually use ──────────────────────────────────

@pytest.mark.parametrize("note", [
    "none", "none — no capability lane changes.", "none - docs only",
    "none: docs only", "none.", "N/A", "-",
])
def test_deliberate_omission_is_recognised(note):
    assert _parse(f"Matrix-Note: {note}") is None


def test_none_with_the_reason_on_the_next_line_is_an_omission():
    """b13c700's shape: a bare `none`, then prose. parse_note folds continuations into one
    string, so this has to be judged on the raw trailer before that happens."""
    assert _parse("Matrix-Note: none\nDocs only; no rule code or capability lanes touched.") is None


def test_a_real_note_that_merely_opens_with_none_is_NOT_swallowed():
    """The failure direction that matters: silently dropping a genuine capability change because
    its first word happened to be 'none'."""
    e = _parse("WCAG: 1.1.1 (pdf)\n"
               "Matrix-Note: none of the detectors changed, but the applier now writes back.")
    assert e is not None
    assert e["summary"].startswith("none of the detectors")


# ── Untracked SCs degrade the entry; they do not destroy it ───────────────────────────────────

def test_an_untracked_sc_is_dropped_but_its_tracked_siblings_survive(capsys):
    """2caaa6c's shape: 1.4.3 (tracked) declared alongside 1.4.6 (no matrix row). Killing the
    entry loses the 1.4.3 the matrix CAN render."""
    e = _parse("WCAG: 1.4.3 (pdf)\nWCAG: 1.4.6 (pdf)\nMatrix-Note: Real note.")
    assert e is not None and e["scs"] == ["1.4.3"]
    assert "1.4.6" in capsys.readouterr().err          # announced, not silent


def test_an_untracked_sc_is_still_fatal_under_check_where_it_can_be_fixed():
    """The complement, and the reason the leniency above is safe: severity follows fixability.
    Softening generation must not soften the gate."""
    with pytest.raises(glog.TrailerProblem):
        _parse("WCAG: 1.4.3 (pdf)\nWCAG: 1.4.6 (pdf)\nMatrix-Note: Real note.", strict=True)


def test_an_entry_whose_only_sc_is_untracked_is_still_dropped(capsys):
    """Nothing left to place in the matrix, so there is no entry to render."""
    assert _parse("WCAG: 1.4.6 (pdf)\nMatrix-Note: Real note.") is None
    assert "1.4.6" in capsys.readouterr().err


def test_a_note_with_no_wcag_line_is_reported_and_skipped(capsys):
    assert _parse("Matrix-Note: A real note that forgot to say which criterion.") is None
    assert "no WCAG" in capsys.readouterr().err


def test_an_unknown_format_is_reported_and_skipped(capsys):
    assert _parse("WCAG: 1.1.1 (rtf)\nMatrix-Note: Real note.") is None
    assert "rtf" in capsys.readouterr().err


# ── The skip message must name the cause the code actually established (#57) ───────────────────
#
# One message used to cover three different failures, and the cause it named — the author omitted
# the trailer — was the one case it could not distinguish. That is not a wording preference: on
# 2026-07-29 it was read at face value off 51a673b and 676f081, whose trailers were valid and
# comma-separated, and the wrong cause reached a commit message, PR #49 and five other sessions.

def test_a_present_but_unparseable_wcag_line_does_not_blame_the_author(capsys):
    """The regression that matters. A `WCAG:` line is RIGHT THERE, so "no WCAG: trailer" asserts
    something about the author that the code has not established."""
    assert _parse("WCAG: none\nMatrix-Note: A real note.") is None
    err = capsys.readouterr().err
    assert "no WCAG: trailer" not in err
    assert "no criterion parsed out of it" in err


def test_the_unparseable_message_echoes_the_offending_line(capsys):
    """Echoing it back is what makes the message self-correcting — the comma, or here the missing
    third part, becomes the obvious suspect in one read instead of sending you to audit a commit."""
    assert _parse("WCAG: 1.1 (pdf)\nMatrix-Note: A real note.") is None
    assert "`WCAG: 1.1 (pdf)`" in capsys.readouterr().err


def test_an_all_untracked_entry_is_not_reported_as_a_missing_trailer(capsys):
    """The clearest case, because the tool got it right and then talked itself out of it: it named
    1.4.6 as untracked, then announced a missing trailer it had just quoted."""
    assert _parse("WCAG: 1.4.6 (pdf)\nMatrix-Note: Real note.") is None
    err = capsys.readouterr().err
    assert "1.4.6" in err                       # still announced
    assert "no WCAG: trailer" not in err        # and no longer contradicted
    assert "untracked" in err


def test_a_genuinely_missing_wcag_line_still_says_so(capsys):
    """The one case the old message was right about, pinned so splitting it did not lose it."""
    assert _parse("Matrix-Note: A real note that forgot to say which criterion.") is None
    assert "no WCAG: trailer" in capsys.readouterr().err


def test_an_sc_inside_a_larger_token_is_not_harvested(capsys):
    """`_WCAG_ITEM` matched the digits inside a bigger token, so `SC1.1.1` parsed as 1.1.1 — the
    same class of gap as the old `$` anchor, in the opposite direction. Now rejected, and the echo
    shows why."""
    assert _parse("WCAG: SC1.1.1 (pdf)\nMatrix-Note: A real note.") is None
    assert "`WCAG: SC1.1.1 (pdf)`" in capsys.readouterr().err


@pytest.mark.parametrize("body", [
    "Matrix-Note: A real note that forgot to say which criterion.",
    "WCAG: 1.1.1 (rtf)\nMatrix-Note: Real note.",
    "WCAG: none\nMatrix-Note: A real note.",
    "WCAG: SC1.1.1 (pdf)\nMatrix-Note: A real note.",
])
def test_check_stays_strict_on_every_malformed_trailer(body):
    with pytest.raises(glog.TrailerProblem):
        _parse(body, strict=True)


# ── collect(): one bad commit must not brick the whole log ────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _git(r, "remote", "add", "origin", "https://github.com/owner/repo.git")
    return r


def _commit(repo: Path, message: str) -> None:
    (repo / "f.txt").write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_one_unparseable_commit_does_not_suppress_the_others(repo):
    """The amplifier #47 removed: this used to exit(1) with EMPTY stdout, so a single bad trailer
    anywhere in history meant no log at all — uncorrectable, the message having already landed."""
    _commit(repo, "fix(a): good\n\nWCAG: 1.1.1 (pdf)\nMatrix-Note: First real note.")
    _commit(repo, "fix(b): malformed\n\nMatrix-Note: A note with no WCAG line at all.")
    _commit(repo, "fix(c): good\n\nWCAG: 2.4.2 (docx)\nMatrix-Note: Second real note.")

    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert [e["scs"] for e in json.loads(r.stdout)] == [["2.4.2"], ["1.1.1"]]   # newest first
    assert "fix(b)" not in r.stdout
    assert "skipped" in r.stderr                                               # announced


def test_a_skip_is_annotated_so_a_green_run_still_shows_it(repo):
    """A skip is the whole safety net for severity-follows-fixability: the entry never reaches
    the matrix, and the job stays green. Without the `::warning::` prefix that report is a line
    in a log nobody opens for a passing job — announced in principle, invisible in practice."""
    _commit(repo, "fix(b): malformed\n\nMatrix-Note: A note with no WCAG line at all.")

    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0
    assert "::warning::" in r.stderr, "the skip must surface on the Actions run summary"


def test_a_dropped_sc_is_annotated_too(repo):
    """The other skip: the entry survives, one criterion silently does not."""
    _commit(repo, "fix(c): part-tracked\n\nWCAG: 1.4.3 (pdf)\nWCAG: 1.4.6 (pdf)\n"
                  "Matrix-Note: Real note.")

    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0
    assert [e["scs"] for e in json.loads(r.stdout)] == [["1.4.3"]]
    assert "::warning::" in r.stderr and "1.4.6" in r.stderr


def test_generation_succeeds_over_this_repos_real_history():
    """The end-to-end claim, against the history that actually broke it. Guards the whole chain —
    a future trailer style that defeats the parser fails here rather than in the published log."""
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=ACP, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    entries = json.loads(r.stdout)
    assert entries, "the generator produced an empty log over real history"
    assert all(e["scs"] for e in entries), "an entry rendered with no SC to place it under"


# ── A squash carries as many Matrix-Notes as it squashed ──────────────────────
# GitHub pre-fills the merge description with the concatenated commit messages, so a squash of N
# trailer-bearing commits arrives here with N notes. The parser used to take the FIRST via
# `_NOTE_RE.search()`, which published one and silently dropped the rest.
#
# Both real outcomes came from that one rule, and only their ORDER differed:
#   acp #144 — real note then `Matrix-Note: none`  -> published correctly, by luck.
#   acp #146 — four real notes                     -> would have dropped three, and only
#              published in full because a human rewrote the description at the merge screen.

def _squashed(*notes: str) -> str:
    """A merge body shaped like GitHub's: `* subject`, blank line, body, trailers, repeat.

    Each part ends with a `Key: value` trailer on purpose — that is what terminates a note body
    (_NOTE_RE stops at the next `^\\S+:`). Without one the note runs on into the FOLLOWING
    commit's `* subject` line and swallows it as a bullet. Real messages always carry a
    Co-authored-by, so this mirrors them rather than the degenerate case.
    """
    return "\n\n".join(
        f"* commit {i} subject\n\nWCAG: 1.3.3 (docx)\nMatrix-Note: {n}\n"
        f"Co-authored-by: A <a@example.com>"
        for i, n in enumerate(notes, 1))


def test_every_note_in_a_squash_is_kept():
    body = _squashed(
        "Word got the write-back.\n  - **DOCX 1.3.3** — the Word half.",
        "PowerPoint got it too.\n  - **PPTX 1.3.3** — the slide half.",
        "Excel completes it.\n  - **XLSX 1.3.3** — the spreadsheet half.",
    )
    notes = glog.collect_notes(body)
    assert len(notes) == 3
    lead, bullets = glog.merge_notes(notes)
    assert [b["label"] for b in bullets] == ["DOCX 1.3.3", "PPTX 1.3.3", "XLSX 1.3.3"]
    # The lead is what the matrix shows COLLAPSED, so keeping only the first would describe one
    # change and hide two.
    assert lead == "Word got the write-back. PowerPoint got it too. Excel completes it."


def test_a_none_among_real_notes_is_ignored_not_counted():
    """acp #144's exact shape. `none` is a statement about its OWN commit, not the others."""
    body = _squashed("The real note.\n  - **DOCX 4.1.2** — a bullet.", "none")
    notes = glog.collect_notes(body)
    assert len(notes) == 1
    lead, bullets = glog.merge_notes(notes)
    assert lead == "The real note."
    assert [b["label"] for b in bullets] == ["DOCX 4.1.2"]


def test_a_none_that_arrives_first_does_not_suppress_the_real_note():
    """The ordering that first-match got wrong in the other direction — and the reason ordering
    must stop mattering at all."""
    body = _squashed("none", "The real note.\n  - **DOCX 4.1.2** — a bullet.")
    lead, bullets = glog.merge_notes(glog.collect_notes(body))
    assert lead == "The real note."
    assert [b["label"] for b in bullets] == ["DOCX 4.1.2"]


def test_all_notes_being_omissions_still_skips_the_entry():
    """Today's behaviour, preserved exactly: nothing to declare stays nothing to declare."""
    assert glog.collect_notes(_squashed("none", "none — considered, no matrix impact")) == []


def test_a_squashed_commit_publishes_every_note(repo):
    """End to end through the generator, not just the helpers."""
    _commit(repo, _squashed(
        "Word got it.\n  - **DOCX 1.3.3** — one.",
        "PowerPoint too.\n  - **PPTX 1.3.3** — two."))
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    entry = json.loads(r.stdout)[0]
    assert [p["label"] for p in entry["points"]] == ["DOCX 1.3.3", "PPTX 1.3.3"]
    assert entry["summary"] == "Word got it. PowerPoint too."
    # Merging is normal but worth seeing — reported, never silent.
    assert "::notice::" in r.stderr and "merged 2 Matrix-Note" in r.stderr
