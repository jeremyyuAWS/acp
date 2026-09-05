"""The generated service inventory must stay current, and its --check must be able to fail.

A --check that cannot fail is indistinguishable from one that passed, so this deliberately
corrupts the generated file and asserts the guard notices — then restores it in a finally.
Same shape as tests/test_scope_presets_frontend_sync.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "gen_service_inventory.py"
TARGET = ROOT / "packaging" / "docs" / "service-inventory.md"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GENERATOR), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_generated_inventory_is_current():
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_check_fails_when_the_file_is_stale():
    original = TARGET.read_text()
    try:
        TARGET.write_text(original.replace("| `acp-assess` |", "| `acp-assess-RENAMED` |", 1))
        result = _run("--check")
        assert result.returncode == 1, (
            "the generated inventory was corrupted and --check still passed, so it is not "
            "guarding anything")
        assert "STALE" in result.stderr
    finally:
        TARGET.write_text(original)
    assert _run("--check").returncode == 0


def test_the_generator_produces_a_non_empty_block():
    result = _run("--stdout")
    assert result.returncode == 0, result.stderr
    assert "## Platform support" in result.stdout
    assert "acp-assess" in result.stdout


def test_every_example_appears_in_the_generated_document():
    text = TARGET.read_text()
    for path in sorted((ROOT / "packaging" / "examples").glob("*.acp-deployment.yaml")):
        assert path.name in text, f"{path.name} is not described in the generated inventory"
