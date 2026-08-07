"""The SPA's copy of the operator scope presets must be GENERATED, never retyped.

`SCOPE_PRESETS` is the customer's agreed checklist, and the "By WCAG criterion" panel now
defaults to it — a customer-facing surface, read by their accessibility specialist. The obvious
shortcut when wiring that up is to retype the 14 criteria into a JS constant, which works
perfectly until somebody edits the Python. Then there are two lists of one checklist, the
backend gates on one and the customer reads the other, and nothing anywhere reports it.

`documents20.js` is the precedent worth naming: it calls itself the "single source of truth" for
the 20-check document core and is nonetheless a hand-typed list with no mechanical tie to the
code. This suite is the tie the scope presets get instead.

So: `scripts/gen_scope_presets.py` emits `frontend/src/scopePresets.js`, and these tests fail if
the file on disk is stale, if the generator's output stops parsing as the module the SPA imports,
or if a preset stops being expressible. The generator's `--check` is what CI runs; the rest is
here because a `--check` that cannot fail would be worse than no check at all.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen_scope_presets.py"
OUT = ROOT / "frontend" / "src" / "scopePresets.js"
# The redesign fork gets the same generated module and the same guard. Imported from the
# generator rather than retyped: a second hand-maintained list of where the generated files go
# is the identical failure mode this whole module exists to prevent, one level up.
sys.path.insert(0, str(ROOT / "scripts"))
from gen_scope_presets import OUTS  # noqa: E402

sys.path.insert(0, str(ROOT / "api"))


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run the generator, reading the GENERATOR's exit status — not a pipeline's.

    A `cmd | tail; echo $?` here would report tail's 0 no matter how the generator died, and a
    stale-file check that cannot fail is indistinguishable from one that passed (CLAUDE.md,
    "Verify before you diagnose").
    """
    return subprocess.run([sys.executable, str(GEN), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_generated_file_is_current():
    """Every committed scopePresets.js matches what the Python defines right now."""
    r = _run("--check")
    assert r.returncode == 0, (
        "a generated scopePresets.js is stale — the tables moved without regenerating it.\n"
        "Fix: python scripts/gen_scope_presets.py\n\n" + r.stderr)


@pytest.mark.parametrize("out", OUTS, ids=lambda p: p.parent.parent.name)
def test_every_target_exists_and_is_current(out):
    """Each SPA's copy individually, so a failure names the one that drifted.

    The aggregate check above would go red either way; this says WHICH. That mattered on
    2026-08-07: #145 generated the file from a base that predated #149's removal of docx from
    the 4.1.2 tables, and frontend-v2/ had never been generated at all — two different staleness
    causes in one run, and one message naming only "frontend/" would have hidden the second.
    """
    assert out.exists(), f"{out.relative_to(ROOT)} was never generated"
    r = _run("--stdout")
    assert r.returncode == 0, r.stderr
    assert out.read_text() == r.stdout, (
        f"{out.relative_to(ROOT)} is stale — regenerate with: python scripts/gen_scope_presets.py")


def test_both_spas_get_byte_identical_content():
    """The two SPAs must not be allowed to diverge into 'nearly the same' generated module.

    A fork that is 99% identical is worse than one that is obviously different: the drift hides
    in the 1%, and the v2 panel would render a scope the backend does not gate on.
    """
    texts = {out.relative_to(ROOT).as_posix(): out.read_text() for out in OUTS}
    assert len(set(texts.values())) == 1, (
        "generated scopePresets.js differs between SPAs: " + ", ".join(texts))


def test_check_actually_fails_on_drift(tmp_path, monkeypatch):
    """--check must FAIL on a stale file. Without this, the guard above proves nothing."""
    original = OUT.read_text()
    try:
        OUT.write_text(original.replace('"1.1.1"', '"9.9.9"', 1))
        r = _run("--check")
        assert r.returncode == 1, "--check passed on a file it should have rejected"
        assert "stale" in r.stderr
    finally:
        OUT.write_text(original)
    assert _run("--check").returncode == 0, "the drift test did not restore the file"


def test_stdout_mode_does_not_write():
    """--stdout is the inspection path; it must not touch the working tree."""
    before = OUT.read_text()
    r = _run("--stdout")
    assert r.returncode == 0, r.stderr
    assert r.stdout == before
    assert OUT.read_text() == before


def test_every_preset_reaches_the_frontend_intact():
    """Every criterion and format in every preset survives the round trip.

    Parsed out of the emitted JS rather than compared against a second literal here — a fixture
    listing the 14 would be the third copy of the thing this file exists to keep to one.
    """
    import store

    js = OUT.read_text()
    for name, scope in store.SCOPE_PRESETS.items():
        assert f'{json.dumps(name)}: {{' in js, f"preset {name} missing from the generated module"
        for sc, fmts in scope.items():
            want = f'{json.dumps(sc)}: [{", ".join(json.dumps(f) for f in sorted(fmts))}],'
            assert want in js, f"{name}/{sc} not emitted as {want!r}"

    # And nothing extra: a criterion in the JS that the Python does not define would be a scope
    # the backend never gates on, silently widening what the panel calls "agreed".
    emitted = set(re.findall(r'^    "(\d+\.\d+\.\d+)":', js, flags=re.M))
    defined = {sc for scope in store.SCOPE_PRESETS.values() for sc in scope}
    assert emitted == defined


def test_deva_final_is_the_fourteen_the_panel_claims():
    """The panel's header says 14 and its note says "6 of the 20". Pin the 14 server-side.

    Not a duplicate of the frontend's own assertion: that one proves the SPA renders what it
    imported, this one proves the backend still defines a scope of that size. They fail on
    different mistakes — the first on a UI regression, the second on someone editing the preset.
    """
    import store

    scope = store.SCOPE_PRESETS["deva-final"]
    assert len(scope) == 14
    assert all(fmts for fmts in scope.values()), "a criterion in scope for no format is not in scope"


@pytest.mark.parametrize("fmt", ["docx", "xlsx", "pptx", "pdf"])
def test_frontend_gate_agrees_with_in_scope(fmt):
    """The emitted per-format lists are exactly what `store.in_scope()` answers.

    The JS `inScope()` is a transliteration of the Python one, so the risk is not the logic but
    the DATA behind it disagreeing per format. 1.3.2, 2.1.1, 2.4.3 and 4.1.2 are scoped to a
    subset of the four formats, so a whole-format drift shows up here rather than in a count.
    """
    import store

    scope = store.SCOPE_PRESETS["deva-final"]
    js = OUT.read_text()
    for sc in scope:
        emitted = re.search(rf'^    "{re.escape(sc)}": \[(.*?)\],$', js, flags=re.M)
        assert emitted, f"{sc} not found in the generated module"
        in_js = fmt in json.loads(f"[{emitted.group(1)}]")
        assert in_js is store.in_scope(sc, fmt, scope), (
            f"{sc} × {fmt}: generated module says {in_js}, store.in_scope says the opposite")
