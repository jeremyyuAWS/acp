"""Make ACP's flat `api/` imports legible to mutmut. Loaded ONLY during a mutation run.

THE MISMATCH THIS EXISTS TO CLOSE, because it is not obvious and mutmut's own error message is
the best description of the symptom:

    Stopping early, because tests recorded trampoline hits but none match any mutant key.
    Recorded keys (e.g.): ['office_structure.x__docx_hyperlinks', ...]
    Expected keys (e.g.): ['api.office_structure.x__apply_lum_mod_off', ...]

mutmut names each mutant after the module's dotted path AS DERIVED FROM THE FILE — `api/
office_structure.py` becomes `api.office_structure`. This repo does not import it that way:
`tests/conftest.py` puts `api/` on `sys.path`, so every test says `import office_structure` and the
module's own `__name__` is the bare one. The mutated code really is being exercised — the file in
`mutants/api/` is what gets imported — but mutmut cannot match its bookkeeping to the hits, so it
refuses to report anything.

REFUSING IS THE RIGHT BEHAVIOUR AND IS WHY THIS IS SAFE TO FIX. Had mutmut instead reported "all
mutants killed", the campaign would have looked like a clean bill of health for a suite that was
never measured — the exact class of vacuous green this repo keeps finding (see the round-trip
harness's own history in tests/test_docx_libreoffice_roundtrip.py). The tool failing closed is
what makes the alias below a correction to bookkeeping rather than a way of getting past a
warning.

WHY AN ALIAS RATHER THAN CHANGING THE IMPORTS. The alternative is rewriting ~100 test modules and
`conftest.py` to say `from api import office_structure`, which is a large diff whose only purpose
is to satisfy a tool that runs on demand. Worse, it would not even work on its own: the target
modules use BARE SIBLING IMPORTS (`from swallowed import swallowed` inside office_structure.py),
so `api/` has to stay on `sys.path` regardless. The import style is load-bearing, not incidental.

WHAT IT DOES. Imports each target under its fully-qualified name and registers that same module
object under the bare name, so a later `import office_structure` gets a module whose `__name__` is
`api.office_structure`. One object, two names, no copy — so there is no possibility of the tests
exercising a different instance from the one mutmut instrumented.

INERT OUTSIDE A MUTATION RUN. Nothing loads this file during an ordinary `pytest tests/`; it is
named in `setup.cfg`'s `pytest_add_cli_args` and reaches pytest only via mutmut. It also refuses
to alias a module that has already been imported (`setdefault`), so it can never swap a module out
from under code that is already using it.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

#: The modules a mutation campaign targets, as (package-qualified, bare) pairs. Keep this in step
#: with `source_paths` in setup.cfg — a module mutated but not aliased produces exactly the
#: "no mutant key matched" stop this file exists to prevent, and the message names the module.
TARGETS = [("api.office_structure", "office_structure")]

_ROOT = Path(__file__).resolve().parent


def _prepare_sys_path() -> None:
    """Both roots, and both are needed for different reasons.

    `api/` satisfies the target modules' own bare sibling imports; the repository root makes `api`
    resolvable as an implicit namespace package (there is no `api/__init__.py`). Missing either
    one turns the alias below into an ImportError at plugin-load time, which pytest reports as a
    plugin failure rather than as a mutation result.
    """
    for path in (str(_ROOT / "api"), str(_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)


def install_aliases() -> list[str]:
    """Install every alias in TARGETS. Returns the ones actually installed, for reporting."""
    _prepare_sys_path()
    installed = []
    for qualified, bare in TARGETS:
        module = importlib.import_module(qualified)
        # setdefault, never assignment: if something has already imported the bare name, replacing
        # it would leave two module objects alive and the tests could exercise the one mutmut did
        # not instrument — silently halving the campaign.
        if sys.modules.setdefault(bare, module) is module:
            installed.append(f"{bare} -> {qualified}")
    return installed


#: Filled in by `pytest_configure`, NOT at import time. Importing this module has no side effects.
#:
#: THAT SEPARATION IS LOAD-BEARING, and it was a real defect before it was a design note. Aliasing
#: on import meant that anything importing this file — including its own guard test — mutated
#: `sys.modules` for every other test sharing the process. Two consequences, both bad and both
#: invisible: an ordinary `pytest tests/` run would start handing other modules the
#: `api.office_structure` instance, and the guard test's own assertion would pass or fail
#: depending on whether some earlier test had already imported the bare name (`setdefault` does
#: nothing once it has). A harness whose correctness depends on test ORDER is not a harness.
#:
#: `pytest_configure` runs after plugins load and before collection imports any test module, which
#: is early enough for the alias to be in place before anything asks for the bare name.
ALIASED: list[str] = []


def pytest_configure(config) -> None:
    ALIASED.extend(install_aliases())


def pytest_report_header(config) -> str:
    """Say what was aliased, in the pytest header of every mutation run.

    A campaign whose result depends on this file having worked should not have to be taken on
    trust; if the header is missing or the list is short, the numbers that follow are about fewer
    modules than intended.
    """
    return f"mutmut module alias: {', '.join(ALIASED) if ALIASED else 'NONE — mutants will not be matched'}"
