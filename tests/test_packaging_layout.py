"""The repository-layout properties the packaging tree depends on.

Small, but each one is load-bearing and silent when broken.
"""
from __future__ import annotations

from packaging_helpers import PACKAGING, ROOT


def test_no_top_level_packaging_python_package():
    """`packaging` must not be importable as a package from the repo root.

    `packaging` is a real PyPI distribution that pip, setuptools and pytest plugins import. A
    top-level package of that name in this repo would shadow it whenever the repo root is on
    sys.path, and the failure surfaces somewhere else entirely — an unrelated tool breaking, with
    nothing pointing back here. Keeping the CLI at packaging/cli/acpctl costs one path segment
    and removes the hazard.
    """
    assert not (PACKAGING / "__init__.py").exists(), (
        "packaging/__init__.py would shadow the PyPI `packaging` distribution for anything that "
        "imports it with the repo root on sys.path. Keep the CLI under packaging/cli/acpctl.")


def test_acpctl_is_importable_as_a_top_level_name():
    import acpctl
    assert acpctl.__version__


def test_schema_is_where_the_cli_looks_for_it():
    from acpctl.spec import SCHEMA_PATH
    assert SCHEMA_PATH.exists()
    assert SCHEMA_PATH == ROOT / "packaging" / "schema" / "acp-deployment.schema.json"
