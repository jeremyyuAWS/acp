"""Shared loading for the packaging contract tests.

`acpctl` lives at packaging/cli/acpctl so that the importable name is `acpctl` and nothing puts a
directory named `packaging` on sys.path as a package — see tests/test_packaging_layout.py.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
if str(PACKAGING / "cli") not in sys.path:
    sys.path.insert(0, str(PACKAGING / "cli"))

EXAMPLES = sorted((PACKAGING / "examples").glob("*.acp-deployment.yaml"))
EXAMPLE_IDS = [p.name.replace(".acp-deployment.yaml", "") for p in EXAMPLES]


def load(path) -> dict:
    from acpctl.spec import load_document
    return load_document(path)


def load_example(name: str) -> dict:
    """A fresh copy of one example, safe to mutate."""
    matches = [p for p in EXAMPLES if p.name.startswith(name)]
    assert matches, f"no example named {name!r}; have {EXAMPLE_IDS}"
    return copy.deepcopy(load(matches[0]))


def errors_for(doc: dict) -> list[str]:
    """The rule ids a document trips. Rule ids, not messages: an assertion on prose fails when
    the wording is improved, which trains people to loosen the assertion."""
    from acpctl.spec import validate
    return [f.rule for f in validate(doc).errors]


def findings_for(doc: dict):
    from acpctl.spec import validate
    return validate(doc)
