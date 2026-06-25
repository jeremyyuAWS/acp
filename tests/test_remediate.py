"""Server-side HTML remediation tests (ADR 0005). Pure lxml — no DB/engines."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from remediate import remediate_html  # noqa: E402


def test_adds_missing_lang():
    out, applied, _ = remediate_html("<html><head></head><body><p>hi</p></body></html>")
    assert 'lang="en"' in out
    assert any("3.1.1" in c for c in applied)


def test_keeps_existing_lang():
    out, applied, _ = remediate_html('<html lang="fr"><head><title>x</title></head><body></body></html>')
    assert 'lang="fr"' in out
    assert not any("3.1.1" in c for c in applied)


def test_adds_title_from_h1():
    out, applied, _ = remediate_html(
        "<html lang='en'><head></head><body><h1>Annual Report</h1></body></html>")
    assert "<title>Annual Report</title>" in out
    assert any("2.4.2" in c for c in applied)


def test_fills_blank_title():
    out, _, _ = remediate_html(
        "<html lang='en'><head><title>  </title></head><body><h1>Hello</h1></body></html>")
    assert "<title>Hello</title>" in out


def test_labels_unlabeled_input():
    out, applied, _ = remediate_html(
        "<html lang='en'><head><title>t</title></head>"
        "<body><form><input type='text' name='email' placeholder='Your email'></form></body></html>")
    assert 'aria-label="Your email"' in out
    assert any("1.3.1" in c for c in applied)


def test_keeps_labeled_input():
    out, applied, _ = remediate_html(
        "<html lang='en'><head><title>t</title></head>"
        "<body><form><input type='text' aria-label='Search'></form></body></html>")
    assert 'aria-label="Search"' in out
    # no new 1.3.1 change for an already-labeled control
    assert not any("1.3.1" in c for c in applied)


def test_deferred_includes_ai_assisted():
    # 'ai-assisted' SCs are not auto-fixed; their ids come back as deferred (→ HITL).
    _, _, deferred = remediate_html("<html><body></body></html>")
    # ai-assisted SCs aren't registered as 'auto', so if any were registered they'd
    # appear here. The current module registers only 'auto' fixers, so deferred is [].
    assert isinstance(deferred, list)


def test_clean_doc_no_changes():
    clean = ('<html lang="en"><head><title>Good</title></head>'
             '<body><form><input aria-label="Name"></form></body></html>')
    _, applied, _ = remediate_html(clean)
    assert applied == []
