"""Assessment-time HuggingFace escalation for LOW-confidence WCAG findings.

When analyse_and_assess returns a finding whose (rule, fmt) registration carries
Confidence.LOW, _escalate_low_confidence_findings annotates it with an hf_provenance
dict and emits a structured log line. Provider is cloud_vision_provider() — HuggingFace
when configured. AI-off mode and absent provider both short-circuit without a network call.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_store(ai_enabled=True):
    return types.SimpleNamespace(get_ai_enabled=lambda: ai_enabled)


class _FakeCloud:
    """Minimal cloud vision provider stub."""
    def __init__(self, ok=True, provider="huggingface", zone="eu-west", cost=0.0):
        self.name = provider
        self._ok = ok
        self._zone = zone
        self._cost = cost
        self.calls = []

    def generate(self, prompt, image_bytes, *, model=None, timeout=120.0):
        self.calls.append({"prompt": prompt, "img_len": len(image_bytes)})
        return {"ok": self._ok, "provider": self.name, "zone": self._zone,
                "cost_usd": self._cost, "text": "form field detected" if self._ok else None}


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Wire core.store + render, create a dummy PDF file, return its path."""
    import core
    import render
    monkeypatch.setattr(core, "store", _make_store(ai_enabled=True))
    monkeypatch.setattr(render, "render_page1_png", lambda data, ext: b"FAKEPNG")
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF-1.4")
    return doc


# ── escalation fires ─────────────────────────────────────────────────────────

def test_escalation_annotates_low_confidence_finding(env, monkeypatch):
    """A finding whose (rule=1.3.5, fmt=pdf) registration has Confidence.LOW is escalated."""
    import handlers
    import providers
    cloud = _FakeCloud(ok=True, provider="huggingface", zone="eu-west", cost=0.0)
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: cloud)

    fdict = {
        "status": "complete",
        "issues": [{"ruleId": "pdf.input-purpose", "wcag": "1.3.5 Identify Input Purpose",
                    "severity": "SERIOUS"}],
    }
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")

    issue = fdict["issues"][0]
    assert "hf_provenance" in issue, "LOW-confidence finding must carry hf_provenance"
    p = issue["hf_provenance"]
    assert p["provider"] == "huggingface"
    assert p["escalated"] is True
    assert p["zone"] == "eu-west"
    assert p["cost_usd"] == 0.0


def test_provenance_cost_recorded(env, monkeypatch):
    """Non-zero cost_usd from the provider is faithfully written into provenance."""
    import handlers
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider",
                        lambda: _FakeCloud(ok=True, cost=0.005))

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    assert fdict["issues"][0]["hf_provenance"]["cost_usd"] == 0.005


def test_only_low_confidence_issues_annotated(env, monkeypatch):
    """Mixed findings: only the LOW-confidence one gets hf_provenance."""
    import handlers
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider",
                        lambda: _FakeCloud(ok=True))

    fdict = {"status": "complete",
             "issues": [
                 {"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose", "severity": "SERIOUS"},
                 {"ruleId": "y", "wcag": "1.1.1 Non-text Content", "severity": "SERIOUS"},
             ]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")

    assert "hf_provenance" in fdict["issues"][0]  # 1.3.5/pdf → LOW
    assert "hf_provenance" not in fdict["issues"][1]  # 1.1.1/pdf → HIGH


# ── skipped cases ─────────────────────────────────────────────────────────────

def test_escalation_skipped_when_no_cloud_provider(env, monkeypatch):
    """cloud_vision_provider() returning None short-circuits without touching fdict."""
    import handlers
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    assert "hf_provenance" not in fdict["issues"][0]


def test_escalation_skipped_when_ai_off(env, monkeypatch):
    """get_ai_enabled() returning False must bypass the provider entirely."""
    import core
    import handlers
    import providers
    monkeypatch.setattr(core, "store", _make_store(ai_enabled=False))
    cloud = _FakeCloud(ok=True)
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: cloud)

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    assert cloud.calls == [], "provider must not be called when AI is off"
    assert "hf_provenance" not in fdict["issues"][0]


def test_escalation_skipped_when_no_low_confidence_finding(env, monkeypatch):
    """A finding whose rule/fmt registration has HIGH confidence is not escalated."""
    import handlers
    import providers
    cloud = _FakeCloud(ok=True)
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: cloud)

    # 1.1.1 / pdf → Confidence.HIGH in the registry
    fdict = {"status": "complete",
             "issues": [{"ruleId": "pdf.image-alt", "wcag": "1.1.1 Non-text Content",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    assert cloud.calls == [], "provider must not be called when all findings are high confidence"
    assert "hf_provenance" not in fdict["issues"][0]


def test_escalation_skipped_for_unsupported_format(env, monkeypatch):
    """A file format not mapped to a registry fmt string is silently skipped."""
    import handlers
    import providers
    cloud = _FakeCloud(ok=True)
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: cloud)

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="report.csv")
    assert cloud.calls == []
    assert "hf_provenance" not in fdict["issues"][0]


def test_escalation_skipped_when_render_returns_none(env, monkeypatch):
    """If the page cannot be rendered to PNG, the escalation is skipped gracefully."""
    import handlers
    import providers
    import render
    monkeypatch.setattr(render, "render_page1_png", lambda data, ext: None)
    cloud = _FakeCloud(ok=True)
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: cloud)

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    assert cloud.calls == []
    assert "hf_provenance" not in fdict["issues"][0]


# ── structured log ────────────────────────────────────────────────────────────

def test_structured_log_emitted_on_escalation(env, monkeypatch, capsys):
    """One [hf-escalation] line is printed when escalation fires."""
    import handlers
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider",
                        lambda: _FakeCloud(ok=True, provider="huggingface"))

    fdict = {"status": "complete",
             "issues": [{"ruleId": "x", "wcag": "1.3.5 Identify Input Purpose",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="scan42", file="doc.pdf")
    out = capsys.readouterr().out
    assert "[hf-escalation]" in out
    assert "scan=scan42" in out
    assert "provider=huggingface" in out
    assert "findings=1" in out


def test_no_log_when_no_low_confidence_findings(env, monkeypatch, capsys):
    """No [hf-escalation] line when no LOW-confidence findings are present."""
    import handlers
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: _FakeCloud(ok=True))

    fdict = {"status": "complete",
             "issues": [{"ruleId": "y", "wcag": "1.1.1 Non-text Content",
                         "severity": "SERIOUS"}]}
    handlers._escalate_low_confidence_findings(fdict, env, scan_id="s1", file="doc.pdf")
    out = capsys.readouterr().out
    assert "[hf-escalation]" not in out
