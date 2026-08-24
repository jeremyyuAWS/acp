"""Format packages. Importing this imports every format's registrations as a side effect.

`rule_registry.load()` is the only thing that should import this — going through one named
entry point keeps "which formats exist" answerable in one place, and keeps modules that merely
want to READ the registry (the WCAG-matrix generator does) from having to pull in every
format's parser dependencies.
"""
from __future__ import annotations

from formats import docx, html, pdf, pptx, xlsx  # noqa: F401  — registration happens on import
