"""The mutation harness's own wiring (P5.4), guarded so a silent misconfiguration cannot ship.

WHY THIS EXISTS AT ALL. The campaign itself is on-demand and never runs in CI, so nothing else
would notice if the harness rotted. The specific rot that matters is not "mutmut is broken" — it
is a config that RUNS and reports a clean-looking number while measuring less than it claims.
Three ways that can happen, all of them cheap to prevent and none of them visible in the output:

  * `source_paths` names a module that `mutmut_module_alias.TARGETS` does not alias. mutmut then
    stops with "no mutant key matched" for it, and if OTHER modules are aliased the campaign still
    produces a score — over a smaller set of modules than the reader thinks.
  * The test selection names a file that no longer exists. mutmut collects fewer tests, more
    mutants come back "no tests", and the score over reached mutants can go UP.
  * `also_copy` loses a directory the suite needs, and every test errors during stats collection.
    That one is loud (it stopped this harness twice while being built: first `config/`, then
    `scripts/`), but only because a human was watching the runtime.

These tests are pure config-vs-filesystem checks. They do not run mutmut, take no measurable time,
and are safe in CI precisely because the expensive part is somewhere else.
"""
from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP))

import mutmut_module_alias  # noqa: E402


def _config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(ACP / "setup.cfg")
    return parser


def _listy(value: str) -> list[str]:
    """setup.cfg multi-line values arrive as one newline-joined string."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def test_setup_cfg_declares_a_mutmut_section():
    """Without it mutmut refuses to start at all, with a FileNotFoundError about source_paths."""
    assert _config().has_section("mutmut"), (
        "setup.cfg lost its [mutmut] section — scripts/mutation_test.py cannot run a campaign")


def test_every_mutated_module_is_aliased():
    """THE ONE THAT MATTERS. A mutated-but-unaliased module is silently excluded from the score.

    mutmut names mutants after the file path (`api/office_structure.py` -> `api.office_structure`)
    while this repo's tests import the module bare (`office_structure`), because conftest puts
    `api/` on sys.path. mutmut_module_alias reconciles the two. A module in `source_paths` with no
    entry in TARGETS produces no matching mutant keys — and when other modules DO match, the
    campaign still prints a score, computed over strictly less than it appears to cover.
    """
    source_paths = _listy(_config().get("mutmut", "source_paths"))
    assert source_paths, "source_paths is empty — the campaign would mutate nothing"

    aliased = {qualified for qualified, _bare in mutmut_module_alias.TARGETS}
    for path in source_paths:
        dotted = path.removesuffix(".py").replace("/", ".")
        assert dotted in aliased, (
            f"setup.cfg mutates {path} but mutmut_module_alias.TARGETS does not alias {dotted!r}. "
            f"mutmut would report 'no mutant key matched' for it and measure the rest silently. "
            f"Add ({dotted!r}, {dotted.rsplit('.', 1)[-1]!r}) to TARGETS.")


def test_every_aliased_module_actually_exists():
    """An alias for a module that has been moved or renamed fails at plugin-import time, which
    pytest reports as a plugin error rather than as a mutation result — easy to misread as the
    campaign simply not working."""
    for qualified, _bare in mutmut_module_alias.TARGETS:
        path = ACP / (qualified.replace(".", "/") + ".py")
        assert path.exists(), f"{qualified} is aliased but {path} does not exist"


def test_the_selected_tests_all_exist():
    """A selection naming a deleted file quietly shrinks the campaign, and the score over reached
    mutants can go UP as a result — a smaller, easier set measured as if it were the same one."""
    selection = _listy(_config().get("mutmut", "pytest_add_cli_args_test_selection", fallback=""))
    assert selection, "no tests are selected — every mutant would come back 'no tests'"
    missing = [t for t in selection if not (ACP / t).exists()]
    assert not missing, f"the mutation test selection names files that do not exist: {missing}"


def test_the_copied_tree_covers_what_the_suite_imports():
    """`also_copy` must carry every directory the tests reach for, or stats collection errors out.

    Each entry here was added because its absence broke a real run: `config/` (store.py reads
    config/rule-catalog.json at import), `scripts/` (test_docx_metamorphic imports
    corpus_expectations), `test-corpus/` (the oracle fixtures), `engine/` (the vendored PDF
    analyser), `api/` (the target's bare sibling imports), and the alias plugin itself.
    """
    also_copy = set(_listy(_config().get("mutmut", "also_copy", fallback="")))
    for required in ("api", "config", "engine", "rules", "scripts", "test-corpus",
                     "mutmut_module_alias.py"):
        assert required in also_copy, (
            f"also_copy is missing {required!r}; the mutation run's pytest collection will fail")
        assert (ACP / required).exists(), f"also_copy names {required!r}, which does not exist"


def test_the_alias_plugin_is_actually_loaded_by_the_campaign():
    """The alias only helps if pytest loads it. It is wired through `pytest_add_cli_args`, and a
    campaign that dropped that flag would fail the same way the unaliased one did."""
    args = _config().get("mutmut", "pytest_add_cli_args", fallback="")
    assert "mutmut_module_alias" in args, (
        "setup.cfg no longer loads the alias plugin, so mutmut will not match any mutant key")


def test_the_alias_gives_one_module_object_under_both_names():
    """The property the whole approach rests on: bare and qualified must be the SAME object.

    Two objects would mean the tests exercising one while mutmut instrumented the other — a
    campaign that reports mutants killed by tests that never touched them.

    RUN IN A SUBPROCESS, DELIBERATELY. Installing the alias mutates `sys.modules` process-wide, so
    doing it inside the suite would hand every later test in this shard the `api.office_structure`
    instance — and the assertion itself would then depend on whether some earlier test had already
    imported the bare name, since `install_aliases` refuses to displace an existing one. A test
    whose result depends on collection order is not a guard. The subprocess gives a clean
    interpreter where the question has one answer.
    """
    probe = (
        "import sys; sys.path.insert(0, %r)\n"
        "import mutmut_module_alias as a\n"
        "installed = a.install_aliases()\n"
        "assert installed, 'the alias installed nothing'\n"
        "for qualified, bare in a.TARGETS:\n"
        "    assert sys.modules[bare] is sys.modules[qualified], bare\n"
        "    assert sys.modules[bare].__name__ == qualified, sys.modules[bare].__name__\n"
        "print('ok')\n" % str(ACP)
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ACP,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_importing_the_plugin_does_not_alias_anything_by_itself():
    """Importing the module must be inert; only pytest_configure may touch `sys.modules`.

    This is the regression guard for a defect this harness actually had: the alias was installed
    at import time, so merely importing the plugin — as this very test module does — rewired
    `sys.modules` for every other test in the process, and made the guard above order-dependent.
    """
    probe = (
        "import sys; sys.path.insert(0, %r)\n"
        "import mutmut_module_alias as a\n"
        "leaked = [bare for _q, bare in a.TARGETS if bare in sys.modules]\n"
        "assert not leaked, 'importing the plugin aliased %%r without pytest_configure' %% leaked\n"
        "assert a.ALIASED == [], a.ALIASED\n"
        "print('inert')\n" % str(ACP)
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ACP,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inert" in result.stdout


def test_mutation_testing_is_not_wired_into_ci():
    """P5.4 was accepted as ON DEMAND ONLY. A campaign takes tens of minutes; adding it to CI is a
    budget decision, not something a later edit should be able to make by accident."""
    workflows = list((ACP / ".github/workflows").glob("*.yml"))
    assert workflows, "no workflows found — this guard is not looking where it thinks it is"
    offenders = [w.name for w in workflows if "mutmut" in w.read_text()]
    assert not offenders, (
        f"{offenders} now run mutmut. That is a deliberate decision to make explicitly (and to "
        f"record in docs/BACKLOG.md), not one to arrive at by editing a workflow.")
