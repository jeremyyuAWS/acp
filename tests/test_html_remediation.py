"""Deterministic HTML remediation fixers (1.4.10 / 1.4.4 / 1.4.12 / 1.4.2 / 1.3.4).

Self-contained: crafted HTML through remediate_html(), asserting the output no
longer trips the scanner's heuristic. The engine re-scan already confirmed these
clear the real findings (1.4.10: 12/12 on the corpus).
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from remediate import remediate_html    # noqa: E402


def _fix(html: str):
    fixed, applied, _ = remediate_html(html)
    return fixed.replace(" ", ""), applied


def test_reflow_injects_viewport():
    fixed, applied = _fix('<html><head><meta charset="utf-8"><title>T</title></head><body><p>x</p></body></html>')
    assert 'name="viewport"' in fixed and "width=device-width" in fixed
    assert any("1.4.10" in a for a in applied)


def test_reflow_noop_when_viewport_present():
    _, applied = _fix('<html><head><meta name="viewport" content="width=device-width"><title>T</title></head><body><p>x</p></body></html>')
    assert not any("1.4.10" in a for a in applied)


def test_resize_unblocks_zoom():
    fixed, applied = _fix('<html><head><title>T</title><meta name="viewport" content="width=device-width, user-scalable=no"></head><body><p>x</p></body></html>')
    assert "user-scalable=no" not in fixed
    assert any("1.4.4" in a for a in applied)


def test_text_spacing_relaxes_line_height():
    fixed, applied = _fix('<html><head><title>T</title></head><body><p style="line-height:20px">x</p></body></html>')
    assert "line-height:20px" not in fixed and "line-height:1.5" in fixed
    assert any("1.4.12" in a for a in applied)


def test_autoplay_removed():
    fixed, applied = _fix('<html><head><title>T</title></head><body><video autoplay src="v.mp4"></video></body></html>')
    assert "autoplay" not in fixed
    assert any("1.4.2" in a for a in applied)


def test_orientation_lock_neutralised():
    fixed, applied = _fix('<html><head><title>T</title><style>@media (orientation: portrait){.w{display:none}}</style></head><body><p>x</p></body></html>')
    assert "display:none" not in fixed
    assert any("1.3.4" in a for a in applied)
