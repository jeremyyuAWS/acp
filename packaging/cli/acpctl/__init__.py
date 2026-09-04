"""acpctl — the ACP deployment installer CLI.

This package deliberately sits at packaging/cli/acpctl rather than packaging/acpctl so that the
importable name is `acpctl` and nothing in this repository ever puts a directory named
`packaging` on sys.path as an importable package. `packaging` is a real PyPI distribution that
pip, setuptools and several test dependencies import; a top-level package of that name in the
repo root would shadow it, and the failure would surface as an unrelated tool breaking.
tests/test_packaging_layout.py holds that property.

PRD S10 specifies twelve commands. This release implements the read-only three (validate, plan,
inventory) and nothing else — the first slice makes the packaging CONTRACT reviewable before any
provisioning code exists (PRD S23). The remaining commands are listed by `acpctl --help` as not
yet implemented rather than omitted, so an operator reading the CLI sees the whole shape.
"""

__all__ = ["__version__"]

# The contract version this CLI speaks, not an ACP release version.
__version__ = "0.1.0-alpha"
