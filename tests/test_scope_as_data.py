"""A scan scope can be written as DATA, not only chosen from the presets compiled into the code.

`scan_scope` has always held a preset NAME, so every engagement whose criteria list differed from
`engagement-14` needed a code change, a review and a deploy to express what is really a
configuration fact. The setting now also accepts a JSON map, and both forms resolve to the same
`{criterion: frozenset(formats)}` shape — so `in_scope`, every denominator and the /config report
cannot tell which was used, and none of them changed.

Two design decisions are pinned here because they are the ones a future edit would get wrong:

  * an unusable value fails OPEN (no restriction) and reports why. Failing closed on a typo would
    stop scanning a whole estate, and the symptom — every criterion NOT_EVALUATED — is
    indistinguishable from a correctly narrow scope.
  * `{}` means NO RESTRICTION, not "nothing in scope". `in_scope` has always treated a falsy
    scope that way; making `{}` a total block would turn two characters into the most
    destructive thing an operator could type.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import assessment_policy as ap  # noqa: E402


class _Store:
    """Minimal stand-in: active_scope only ever calls get_setting."""

    def __init__(self, value: str):
        self._v = value

    def get_setting(self, key, default=""):
        return self._v if key == ap.SCOPE_SETTING else default


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    """The module-level override wins over the store; clear it so tests read the setting."""
    monkeypatch.setattr(ap, "_scope_override", None)


# ── the presets still work, unchanged ─────────────────────────────────────────────────────────
def test_a_preset_name_still_resolves():
    scope = ap.active_scope(_Store("engagement-14"))
    assert scope == ap.SCOPE_PRESETS["engagement-14"]
    assert ap.scope_problem(_Store("engagement-14")) is None


def test_no_setting_means_no_restriction():
    assert ap.active_scope(_Store("")) is None
    assert ap.scope_problem(_Store("")) is None
    assert ap.in_scope("1.4.3", "docx", ap.active_scope(_Store(""))) is True


# ── the new data form ─────────────────────────────────────────────────────────────────────────
def test_a_json_map_resolves_to_the_same_shape_as_a_preset():
    raw = json.dumps({"1.4.3": ["docx", "pdf"], "2.4.2": ["docx"]})
    scope = ap.active_scope(_Store(raw))
    assert scope == {"1.4.3": frozenset({"docx", "pdf"}), "2.4.2": frozenset({"docx"})}
    # Same type as a preset, so no caller can tell them apart.
    assert all(isinstance(v, frozenset) for v in scope.values())
    assert ap.scope_problem(_Store(raw)) is None


def test_the_gate_honours_a_data_scope():
    raw = json.dumps({"1.4.3": ["docx"]})
    scope = ap.active_scope(_Store(raw))
    assert ap.in_scope("1.4.3", "docx", scope) is True
    assert ap.in_scope("1.4.3", "pdf", scope) is False    # in scope, wrong format
    assert ap.in_scope("2.4.2", "docx", scope) is False   # criterion not named at all


def test_a_single_format_may_be_written_as_a_bare_string():
    """`{"1.4.3": "docx"}` is what a human writes; rejecting it would be pedantry."""
    scope = ap.active_scope(_Store(json.dumps({"1.4.3": "docx"})))
    assert scope == {"1.4.3": frozenset({"docx"})}


# ── failure is loud, and open ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,fragment", [
    ("{not json",                              "not valid JSON"),
    (json.dumps(["1.4.3"]),                    "must be a JSON object"),
    (json.dumps({"nope": ["docx"]}),           "not a WCAG criterion id"),
    (json.dumps({"9.9.9": ["docx"]}),          "not a criterion this build knows"),
    (json.dumps({"1.4.3": ["docx", "rtf"]}),   "unknown format"),
    (json.dumps({"1.4.3": 7}),                 "formats must be a list"),
    ("no-such-preset",                         "unknown scope preset"),
])
def test_an_unusable_scope_fails_open_and_says_why(raw, fragment):
    assert ap.active_scope(_Store(raw)) is None, "an unusable scope must not restrict anything"
    problem = ap.scope_problem(_Store(raw))
    assert problem and fragment in problem, f"expected {fragment!r} in {problem!r}"


def test_failing_open_really_means_everything_is_in_scope():
    """The half that matters operationally: a broken scope must not silently block a scan."""
    scope = ap.active_scope(_Store("{oops"))
    assert ap.in_scope("1.4.3", "docx", scope) is True
    assert ap.in_scope("4.1.2", "pdf", scope) is True


@pytest.mark.parametrize("raw", ["{}", json.dumps({"1.4.3": []})])
def test_an_empty_scope_is_no_restriction_not_a_total_block(raw):
    """Two characters must not be able to mean "assess nothing"."""
    assert ap.active_scope(_Store(raw)) is None
    assert ap.scope_problem(_Store(raw)) is None      # empty is legal, just inert
    assert ap.in_scope("1.4.3", "docx", ap.active_scope(_Store(raw))) is True


# ── the override path tests use must keep working ─────────────────────────────────────────────
def test_the_module_override_accepts_both_forms(monkeypatch):
    monkeypatch.setattr(ap, "_scope_override", "engagement-14")
    assert ap.active_scope() == ap.SCOPE_PRESETS["engagement-14"]
    monkeypatch.setattr(ap, "_scope_override", json.dumps({"2.4.2": ["pptx"]}))
    assert ap.active_scope() == {"2.4.2": frozenset({"pptx"})}


def test_store_reexports_the_new_helpers():
    """~40 call sites do `from store import ...`; the new names must arrive the same way."""
    import store
    assert store.parse_scope_setting is ap.parse_scope_setting
    assert store.scope_problem is ap.scope_problem
