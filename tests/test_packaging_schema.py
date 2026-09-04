"""The published schema and the evaluator that enforces it must not drift apart.

The failure this guards is invisible in the direction that matters: an evaluator which ignores a
keyword reports an invalid document as VALID. Nothing errors, nothing warns, and the first sign
is a deployment shaped wrongly.
"""
from __future__ import annotations

import json

import pytest

from packaging_helpers import EXAMPLE_IDS, EXAMPLES, load


def _schema():
    from acpctl.spec import load_schema
    return load_schema()


def test_schema_uses_no_keyword_the_evaluator_ignores():
    from acpctl.jsonschema_mini import ANNOTATIONS, SUPPORTED, keywords_used
    unknown = keywords_used(_schema()) - SUPPORTED - ANNOTATIONS
    assert not unknown, (
        f"the schema uses {sorted(unknown)}, which jsonschema_mini does not implement. An "
        f"unimplemented keyword is not a partial check — it is NO check, and the document passes. "
        f"Implement it in jsonschema_mini.py or take it out of the schema.")


def test_every_ref_resolves():
    from acpctl.jsonschema_mini import Validator
    schema = _schema()
    validator = Validator(schema)
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert refs, "the schema has no $refs at all — this test would pass vacuously"
    for ref in refs:
        validator._resolve(ref)


def test_evaluator_rejects_an_unknown_field():
    """additionalProperties: false has to actually bite."""
    from acpctl.jsonschema_mini import Validator
    doc = load(EXAMPLES[0])
    doc["runtime"]["nonsense"] = "x"
    errors = Validator(_schema()).validate(doc)
    assert any(path == "runtime.nonsense" for path, _ in errors)


def test_evaluator_rejects_a_wrong_type():
    from acpctl.jsonschema_mini import Validator
    doc = load(EXAMPLES[0])
    doc["api"]["replicas"]["min"] = "two"
    errors = Validator(_schema()).validate(doc)
    assert any(path == "api.replicas.min" for path, _ in errors)


def test_booleans_are_not_accepted_as_integers():
    """Python's bool is an int. An evaluator that forgets this accepts `min: true` as `min: 1`."""
    from acpctl.jsonschema_mini import Validator
    doc = load(EXAMPLES[0])
    doc["api"]["replicas"]["min"] = True
    errors = Validator(_schema()).validate(doc)
    assert any(path == "api.replicas.min" for path, _ in errors)


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_examples_are_structurally_valid(path):
    from acpctl.jsonschema_mini import Validator
    assert Validator(_schema()).validate(load(path)) == []


def test_schema_is_valid_json_and_declares_its_version():
    schema = _schema()
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["apiVersion"]["const"] == "packaging.acp.mova.io/v1alpha1"
    json.dumps(schema)
