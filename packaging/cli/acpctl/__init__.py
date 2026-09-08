"""acpctl — the ACP deployment installer CLI.

This package deliberately sits at packaging/cli/acpctl rather than packaging/acpctl so that the
importable name is `acpctl` and nothing in this repository ever puts a directory named
`packaging` on sys.path as an importable package. `packaging` is a real PyPI distribution that
pip, setuptools and several test dependencies import; a top-level package of that name in the
repo root would shadow it, and the failure would surface as an unrelated tool breaking.
tests/test_packaging_layout.py holds that property.

PRD S10 specifies twelve commands. This release implements eight: the read-only ones (validate,
plan, inventory, values, adapter, doctor, status, and `init`, which writes a file only when asked
with -o), plus `install`, `uninstall` and `support-bundle`. The remaining four — upgrade,
rollback, backup, restore — are listed by `acpctl --help` as not yet implemented rather than
omitted, so an operator reading the CLI sees the whole shape.

THE MUTATION BOUNDARY IS A FILE, NOT A CONVENTION. `cluster.py` still refuses any kubectl verb
that is not a read, and doctor, status and support-bundle go through it, so those three remain
safe to point at production from a laptop. Everything that can change a cluster lives in
`helm.py` behind its own, narrower allow-list. Widening `cluster.READ_VERBS` to let an installer
through would have retired that guarantee for every command at once, including the ones whose
help text promises they change nothing.
"""

__all__ = ["__version__"]

# The contract version this CLI speaks, not an ACP release version.
__version__ = "0.1.0-alpha"
