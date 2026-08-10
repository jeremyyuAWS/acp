"""EVERY registered detector must survive a malformed upload — return a list, never raise.

`rule_registry.assess` calls a registration's detector as `reg.detector(path) or []` with no
try/except around it (rule_registry.py:157). A detector that raises on a corrupt file therefore
does not fail one criterion — it fails the whole assessment of the document. Real users upload
truncated, mislabelled and hand-forged files, so this is a contract, not an edge case.

`tests/test_docx_detector_robustness.py` pins it for the three docx registry detectors with rich,
docx-shaped malformed packages. THIS file is the wide net: it enumerates the registry itself and
feeds every detector — docx, xlsx, pdf, html, and anything registered later — a format-agnostic
battery (missing path, empty file, random bytes, an empty zip). Because it is driven by
`all_registrations()`, a detector added tomorrow is covered the day it is registered, with no edit
here. That is the point: the contract is registry-wide, so the test is too.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import formats  # noqa: E402

# Importing each format subpackage is what runs its register() calls and populates the registry.
for _m in pkgutil.iter_modules(formats.__path__):
    try:
        importlib.import_module(f"formats.{_m.name}")
    except Exception:  # noqa: BLE001 — a format that won't import is a different test's problem
        pass

import rule_registry as reg  # noqa: E402

REGISTERED = [r for r in reg.all_registrations() if r.detector is not None]


def _write_broken(tmp_path: Path, kind: str) -> Path:
    """One malformed file per `kind`, none of which is a valid document of any format."""
    if kind == "missing":
        return tmp_path / "does_not_exist.bin"          # never created
    if kind == "empty":
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        return p
    if kind == "garbage":
        p = tmp_path / "garbage.bin"
        p.write_bytes(b"\x00\x01\x02 not a document \xff\xfe\x89PNG\r\n")
        return p
    if kind == "empty_zip":                             # a valid zip container, no members
        p = tmp_path / "empty.zip"
        with zipfile.ZipFile(p, "w"):
            pass
        return p
    raise AssertionError(kind)


BROKEN = ["missing", "empty", "garbage", "empty_zip"]


@pytest.mark.parametrize("kind", BROKEN)
@pytest.mark.parametrize("registration", REGISTERED, ids=[f"{r.fmt}:{r.rule}" for r in REGISTERED])
def test_registered_detector_returns_list_never_raises(registration, kind, tmp_path):
    path = _write_broken(tmp_path, kind)
    label = f"{registration.fmt}:{registration.rule} ({registration.detector.__module__})"
    try:
        out = registration.detector(path)
    except Exception as e:  # noqa: BLE001 — the contract is that this never happens
        pytest.fail(f"{label} raised {type(e).__name__} on a {kind} file: {e}")
    assert isinstance(out, list), f"{label} returned {type(out).__name__} on a {kind} file, not a list"


def test_registry_actually_populated():
    """Guard the guard: if the format imports silently stopped registering, the parametrised test
    above would vacuously pass on zero detectors. Pin the floor so that failure is loud."""
    assert len(REGISTERED) >= 11, f"expected >= 11 registered detectors, found {len(REGISTERED)}"
