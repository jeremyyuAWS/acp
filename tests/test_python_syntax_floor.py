"""The repo must stay parseable on the oldest Python it claims to run on.

WHY THIS EXISTS. `api/routes/scans.py` carried one f-string that reused its own delimiter inside
a replacement field — PEP 701, which landed in 3.12. CI pins 3.12, so every check was green while
`import api.routes` failed outright on 3.11 and took ~26 test modules with it. Two sessions hit
it and worked around it before anyone fixed the line; nothing in the repo could have told them,
because the failure is invisible to the interpreter that finds it acceptable.

WHY IT IS NOT `ast.parse`. Measured on 3.12.3: the nested form parses under plain `ast.parse`,
under `ast.parse(..., feature_version=(3, 11))`, and under `compile(..., PyCF_ONLY_AST)`.
`feature_version` gates some grammar but does not reverse the 3.12 tokenizer change, so a guard
built on it would pass on every input and never fail. This walks the token stream instead and
reproduces the pre-3.12 f-string rules directly — and `test_the_detector_agrees_with_a_real_311`
holds it to a real 3.11 interpreter wherever one is installed, so the reimplementation cannot
drift from the thing it models without saying so.
"""
from __future__ import annotations

import configparser
import io
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The floor is DECLARED in setup.cfg, not here. One fact, one place: a constant in this file and
# a number in the config would be free to drift, and the drift would be silent in the direction
# that matters — a raised declaration with the old rules still sweeping, or rules retired while
# the declaration still promised the older Python.
_FLOOR_RE = re.compile(r">=\s*(\d+)\.(\d+)\s*$")


def declared_floor() -> tuple[int, int] | None:
    """(major, minor) from setup.cfg's `python_requires`, or None when it is absent or is not a
    plain `>=X.Y`. None is a failure the tests name, never a default quietly substituted."""
    parser = configparser.ConfigParser()
    parser.read(ROOT / "setup.cfg")
    match = _FLOOR_RE.fullmatch(parser.get("options", "python_requires", fallback="").strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def floor_python(floor: tuple[int, int]) -> str:
    return f"python{floor[0]}.{floor[1]}"


def test_setup_cfg_declares_the_python_floor():
    """The declaration is what the sweep below enforces. Losing it must fail here rather than
    turning the sweep into a check with nothing to check."""
    assert declared_floor() is not None, (
        "setup.cfg no longer declares [options] python_requires as a plain '>=X.Y'. The syntax "
        "floor guard reads it; without it the repo's oldest supported Python is undeclared "
        "again, which is the state that let a 3.12-only f-string ship unnoticed.")

# The three things a pre-3.12 f-string may not carry inside a replacement field. Every one was
# verified against 3.11.15 and 3.12.3 rather than read off the PEP — see the probe matrix in
# `_FORMS` below, which is asserted against a real interpreter when one is available.
#
# A `#` comment is deliberately NOT a fourth rule. It runs to end of line, so a replacement field
# holding one can only close on a later line — and without that newline even 3.12 refuses the
# source ("'{' was never closed"). The comment case is therefore always a newline case, and a
# branch for it could never be the signal that fired. That is not a guess: removing the branch
# changed no verdict in the matrix below, which is how it was found.
_SAME_QUOTE = "reuses the f-string's own {delim} delimiter inside a replacement field"
_BACKSLASH = "has a backslash inside a replacement field"
_NEWLINE = "spans lines inside a replacement field"


def _delimiter(fstring_start: str) -> str:
    """'rf\"\"\"' -> '\"\"\"'. The prefix letters are stripped; what remains is the quote run."""
    return fstring_start.lstrip("fFrRbBuU")


def offending_fstrings(source: str) -> list[tuple[int, str]]:
    """(line, reason) for every f-string in `source` that Python 3.11 would reject.

    Empty for source 3.11 accepts. Returns rather than raises so a caller can report every hit in
    a file at once; the tokenizer stops at the first genuine syntax error either way.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        # Not tokenizable by THIS interpreter — a different problem, and not one this guard is
        # entitled to describe. The suite's own import of the module is what catches those.
        return []
    if not hasattr(tokenize, "FSTRING_START"):
        return []                      # < 3.12 tokenizes f-strings as one STRING; nothing to walk

    found: list[tuple[int, str]] = []
    stack: list[tuple[str, int]] = []          # (delimiter, line) of each open f-string
    depth = 0                                  # replacement-field nesting inside the innermost
    for tok in tokens:
        if tok.type == tokenize.FSTRING_START:
            delim = _delimiter(tok.string)
            if stack and depth > 0 and delim == stack[-1][0]:
                found.append((stack[-1][1], _SAME_QUOTE.format(delim=delim)))
            stack.append((delim, tok.start[0]))
            depth = 0
            continue
        if tok.type == tokenize.FSTRING_END:
            if stack:
                stack.pop()
            continue
        if not stack:
            continue
        delim, line = stack[-1]
        if tok.type == tokenize.OP and tok.string == "{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string == "}":
            depth = max(0, depth - 1)
        elif depth > 0:
            if tok.type == tokenize.STRING:
                quote = tok.string.lstrip("rRbBuUfF")[:1]
                run = delim[0] * len(delim)
                if tok.string.lstrip("rRbBuUfF").startswith(run) or (
                        len(delim) == 1 and quote == delim):
                    found.append((line, _SAME_QUOTE.format(delim=delim)))
                if "\\" in tok.string:
                    found.append((line, _BACKSLASH))
            elif tok.type in (tokenize.NL, tokenize.NEWLINE):
                found.append((line, _NEWLINE))
    # One report per (line, reason): a replacement field repeating the same mistake is one defect.
    return sorted(set(found))


# ── the guard ─────────────────────────────────────────────────────────────────

def _tracked_python_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"],
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / rel for rel in out]


def test_every_tracked_module_parses_on_the_oldest_supported_python():
    floor = declared_floor()
    assert floor is not None, "see test_setup_cfg_declares_the_python_floor"
    if floor >= (3, 12):
        # The rules below ARE the pre-3.12 f-string grammar. On a 3.12 floor there is nothing
        # left for them to catch, and a sweep that cannot fail is worse than no sweep: it reads
        # as coverage. Say so and retire the file rather than letting it go quietly green.
        pytest.skip(
            f"setup.cfg declares a {floor[0]}.{floor[1]} floor; the PEP 701 constructs this "
            "guard detects are legal there, so it has nothing to enforce and should be deleted "
            "along with this skip.")
    files = _tracked_python_files()
    assert len(files) > 500, f"expected the whole tree, got {len(files)} files"
    offenders: list[str] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line, reason in offending_fstrings(source):
            offenders.append(f"{path.relative_to(ROOT)}:{line}: an f-string {reason}")
    assert not offenders, (
        f"these parse on {sys.version_info.major}.{sys.version_info.minor} but not on "
        f"{floor[0]}.{floor[1]} — the floor setup.cfg declares — so the module they are in "
        "cannot be imported there at all:\n  " + "\n  ".join(offenders))


# ── the detector, held to the real thing ──────────────────────────────────────
#
# Each form is source that 3.12 accepts. `rejected` is what 3.11.15 actually answered, measured
# rather than assumed; test_the_detector_agrees_with_a_real_311 re-measures wherever a 3.11 is
# installed, so this table cannot quietly go stale.
_FORMS = {
    "plain": ('x = f"a-{v}"', False),
    "single-in-double": ("""x = f"a-{d['k']}\"""", False),
    "double-in-single": ('x = f\'a-{d["k"]}\'', False),
    "same-quote-double": ('x = f"a-{d["k"]}"', True),
    "same-quote-single": ("x = f'a-{d['k']}'", True),
    "nested-fstring-alt-quote": ('x = f"{a or f\'b-{c}\'}"', False),
    "nested-fstring-same-quote": ('x = f"{a or f"b-{c}"}"', True),
    "regex-same-quote": ('x = f"{re.sub(r"[a]", "_", s)}"', True),
    "regex-alt-quote": ('x = f"{re.sub(r\'[a]\', \'_\', s)}"', False),
    "backslash-in-expr": ('x = f"{chr(92).join(v)}"', False),
    "real-backslash-in-expr": ('x = f"{\'\\n\'.join(v)}"', True),
    "triple-double-single-inside": ('x = f"""{d[\'k\']}"""', False),
    "triple-double-double-inside": ('x = f"""{d["k"]}"""', False),
    "comment-in-expr": ('x = f"{v  # note\n}"', True),
    "multiline-expr": ('x = f"{(\n  a + b\n)}"', True),
}


@pytest.mark.skipif(sys.version_info < (3, 12),
                    reason="f-strings are one STRING token before 3.12; nothing to walk")
@pytest.mark.parametrize("name", sorted(_FORMS))
def test_the_detector_matches_the_measured_grammar(name):
    source, rejected = _FORMS[name]
    assert bool(offending_fstrings(source)) is rejected, (
        f"{name}: {source!r} -> {offending_fstrings(source)}")


def _floor_interpreter(name: str | None = None) -> str | None:
    """Path to a real interpreter for the declared floor on this machine, or None.

    `shutil.which` rather than a subprocess probe. `subprocess.run` RAISES FileNotFoundError for
    a missing executable instead of returning a non-zero code, so a returncode check never runs
    on the machine that lacks the interpreter — which is precisely the machine the check exists
    for. Shipped that way once and CI, which has no python3.11, errored where it should have
    skipped; test_a_missing_floor_interpreter_is_reported_not_raised is the guard for it.
    """
    if name is None:
        floor = declared_floor()
        if floor is None:
            return None
        name = floor_python(floor)
    return shutil.which(name)


def test_a_missing_floor_interpreter_is_reported_not_raised():
    assert _floor_interpreter("python3.11-definitely-not-installed") is None


def test_the_detector_agrees_with_the_real_floor_interpreter():
    """The reimplementation is held to the interpreter it models. Skips where no interpreter for
    the declared floor exists — including CI, which pins 3.12 — so this is a developer-machine
    check, and the parametrized table above is what actually runs everywhere."""
    floor = declared_floor()
    assert floor is not None, "see test_setup_cfg_declares_the_python_floor"
    if floor >= (3, 12):
        # Same retirement as the sweep, and it has to be the same. The detector encodes the
        # PRE-3.12 grammar, so measuring it against a 3.12+ interpreter reports a disagreement on
        # every rejected form — a confusing hard failure right beside a polite skip, when both
        # are saying the one thing: this file's subject no longer exists.
        pytest.skip(
            f"setup.cfg declares a {floor[0]}.{floor[1]} floor; this detector models the "
            "pre-3.12 grammar and has nothing left to model. Delete the file.")
    interpreter = _floor_interpreter()
    if interpreter is None:
        pytest.skip(f"no {floor_python(floor)} on this machine")
    disagreed = []
    for name, (source, _expected) in sorted(_FORMS.items()):
        real = subprocess.run(
            [interpreter, "-c", "import ast,sys; ast.parse(sys.stdin.read())"],
            input=source, capture_output=True, text=True)
        really_rejected = real.returncode != 0
        if bool(offending_fstrings(source)) != really_rejected:
            disagreed.append(f"{name}: {floor_python(floor)} rejected={really_rejected}, "
                             f"detector said {bool(offending_fstrings(source))}")
    assert not disagreed, (
        f"the detector has drifted from the grammar {floor_python(floor)} actually enforces:\n  "
        + "\n  ".join(disagreed))


def test_the_construct_this_guard_was_written_for_is_caught():
    """The exact line that shipped, verbatim."""
    shipped = ('filename = f\'{package_name or f"acp-release-'
               '{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}"}.zip\'')
    assert offending_fstrings(shipped), "the original defect would pass this guard"
    fixed = ("default_name = f\"acp-release-{re.sub(r'[^A-Za-z0-9._-]', '_', sid)}\"\n"
             'filename = f"{package_name or default_name}.zip"')
    assert offending_fstrings(fixed) == []
