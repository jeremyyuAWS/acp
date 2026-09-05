"""A test may not gate itself on a dependency nobody declared.

THE GAP THIS WAS WRITTEN TO DEMONSTRATE. `pytest.importorskip("yaml")` at the top of
tests/test_ci_alert_workflow.py reads as defensive. It is not: PyYAML was declared in neither
api/requirements.txt nor tests/requirements.txt, so on CI — which installs exactly those two
files — the import always failed and every test in that module always skipped. It had never run
there. Not once, in any pull request, since the day it was written.

What it guards makes that worse than a wasted file. ci-alert.yml is what says out loud that CI
has gone red on main, and its docstring opens with the outage it exists to catch: on 2026-08-20
deploy.yml quietly SKIPPED every deploy for an hour while six commits landed, and it was found by
the owner opening the app and asking where the work had gone. The guard against that recurring was
itself silent.

The failure is invisible in both directions. Locally the module imports and passes, because a
developer machine has PyYAML ambiently. On CI it skips, and pytest exits 0 on a skip. Nothing
anywhere renders the difference between "these assertions hold" and "these assertions were never
evaluated" — which is the same false-green shape as tests/test_pg_destructive_guard.py, and the
reason the Postgres job carries an explicit anti-skip step.

So the rule is not "don't use importorskip". It is: if you skip on an import, the thing you are
importing must be DECLARED, so that skipping means the operator chose a partial install rather
than that CI silently lost a test.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

# The two files CI installs, and the only evidence that a dependency is meant to be present.
REQUIREMENTS = (REPO / "api" / "requirements.txt", REPO / "tests" / "requirements.txt")

# Import name -> distribution name, for the handful where they differ. Kept explicit rather than
# resolved from the installed environment: importlib.metadata can only answer for packages that
# are installed, so on the machine where this matters most — one WITHOUT the dependency — it
# would answer "not declared" for everything and the guard would fire on correct code.
#
# A new mismatch fails this test rather than passing quietly, which is the intended direction:
# the author adds one line here and the mapping stays true.
IMPORT_TO_DISTRIBUTION = {
    "yaml": "pyyaml",
    # api/requirements.txt pins psycopg2-binary, which is what provides `import psycopg2`. The
    # skip in test_overload_message_scope.py is therefore legitimate: the dependency IS declared,
    # and it only skips on a deliberately partial install.
    "psycopg2": "psycopg2-binary",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    # `opentelemetry` is a NAMESPACE package: opentelemetry-api provides `opentelemetry.trace`
    # and opentelemetry-sdk provides `opentelemetry.sdk.*`, both under the same top-level name,
    # so the top-level split above cannot tell which distribution a site needs. Mapped to the
    # SDK because that is the half this repo imports (api/telemetry.py's SpanProcessor) and
    # because the SDK depends on the API — declaring the SDK therefore covers either import.
    "opentelemetry": "opentelemetry-sdk",
}


def _declared() -> set[str]:
    """Distribution names declared in the requirements CI installs, normalised for comparison."""
    names = set()
    for path in REQUIREMENTS:
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            # strip extras and any version specifier: `uvicorn[standard]>=0.30` -> `uvicorn`
            name = re.split(r"[<>=!~\[;]", line, 1)[0].strip()
            if name:
                names.add(name.lower().replace("_", "-"))
    return names


def _importorskip_sites() -> list[tuple[str, int, str]]:
    """(file, line, module) for every pytest.importorskip("X") in the suite."""
    sites = []
    for path in sorted(TESTS.rglob("test_*.py")) + sorted(TESTS.glob("conftest.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "importorskip" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                sites.append((path.name, node.lineno, arg.value))
    return sites


def test_every_importorskip_names_a_declared_dependency():
    """The whole rule, asserted structurally.

    Structural rather than behavioural because a behavioural test can only observe the modules a
    given run actually imports — and the failing case is precisely the module that DID NOT run.
    Reading the source instead means this holds on a machine that has every dependency installed,
    which is where it will usually be run and where the problem is otherwise invisible.
    """
    declared = _declared()
    undeclared = []
    for file, line, module in _importorskip_sites():
        top = module.split(".")[0]
        dist = IMPORT_TO_DISTRIBUTION.get(top, top).lower().replace("_", "-")
        if dist not in declared:
            undeclared.append((file, line, module, dist))

    assert not undeclared, (
        "importorskip on a dependency that is declared nowhere CI installs — these tests skip "
        "silently and forever there:\n"
        + "\n".join(f"  {f}:{ln} importorskip({m!r}) -> needs '{d}' in tests/requirements.txt"
                    for f, ln, m, d in undeclared)
        + "\nDeclare it, or import it unconditionally and let a missing dependency FAIL.")


def test_the_walk_looks_at_the_files_that_matter():
    """Anti-vacuity. The assertion above passes when the suite is clean AND when the walk is
    broken, and those must not look alike — so prove the walk parsed a real, populated suite."""
    scanned = sorted(TESTS.rglob("test_*.py"))
    assert len(scanned) > 100, f"only {len(scanned)} test modules found — the walk is not walking"
    assert (TESTS / "test_ci_alert_workflow.py") in scanned, "the module this was written for"


def test_the_requirements_reader_finds_the_known_declarations():
    """Anti-vacuity for the other half: an empty `declared` set would make every importorskip
    look undeclared, and a reader that returned everything would make none of them look it."""
    declared = _declared()
    assert "pytest" in declared and "python-docx" in declared, declared
    assert "this-was-never-declared" not in declared
