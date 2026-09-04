"""A JSON Schema evaluator covering exactly the keywords acp-deployment.schema.json uses.

WHY NOT `jsonschema`. Nothing in this repo's runtime or test requirements installs it, and
`acpctl validate` has to run in a customer's air-gapped installer bundle (PRD S17) where the
answer to a missing dependency is not `pip install`. The subset here is small enough to read in
one sitting and is pinned to the schema by `tests/test_packaging_schema.py`, which fails if the
schema ever grows a keyword this file does not implement. That test is what stops the subset from
silently under-validating: an unsupported keyword is invisible otherwise, because an evaluator
that ignores a constraint reports the document as VALID.

Errors are (path, message) pairs with a dotted human path (`workers.assess.replicas.min`) rather
than a JSON Pointer, because the audience is an operator reading their own YAML.
"""
from __future__ import annotations

import re
from typing import Any

# Keywords that constrain the instance. Anything here is implemented below.
SUPPORTED = frozenset({
    "$ref", "type", "enum", "const",
    "properties", "required", "additionalProperties",
    "items", "minItems", "maxItems", "uniqueItems",
    "minimum", "maximum",
    "minLength", "maxLength", "pattern",
})
# Keywords that carry no constraint. Ignored deliberately, not by omission.
ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "title", "description", "examples", "default"})

_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, name: str) -> bool:
    if name == "integer":
        # bool is an int in Python and is never an acceptable integer here.
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _TYPES.get(name)
    if expected is None:
        raise ValueError(f"unsupported type keyword: {name!r}")
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected) and not isinstance(value, bool)


def _describe(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return f"the string {value!r}"
    return repr(value)


def _join(path: str, key: str) -> str:
    return key if not path else f"{path}.{key}"


class Validator:
    """Evaluates one schema document. Reusable and stateless between calls."""

    def __init__(self, schema: dict) -> None:
        self.schema = schema
        self.defs = schema.get("$defs", {})

    # -- keyword dispatch ---------------------------------------------------
    def _resolve(self, ref: str) -> dict:
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"only local #/$defs/ references are supported, got {ref!r}")
        name = ref[len("#/$defs/"):]
        try:
            return self.defs[name]
        except KeyError:
            raise ValueError(f"unresolvable $ref: {ref!r}") from None

    def validate(self, instance: Any) -> list[tuple[str, str]]:
        errors: list[tuple[str, str]] = []
        self._check(instance, self.schema, "", errors)
        return errors

    def _check(self, value: Any, schema: dict, path: str, errors: list) -> None:
        if "$ref" in schema:
            self._check(value, self._resolve(schema["$ref"]), path, errors)
            return

        if "const" in schema and value != schema["const"]:
            errors.append((path, f"must be {schema['const']!r}, got {_describe(value)}"))
            return

        if "enum" in schema and value not in schema["enum"]:
            allowed = ", ".join(repr(v) for v in schema["enum"])
            errors.append((path, f"must be one of: {allowed} — got {_describe(value)}"))
            return

        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_type_ok(value, n) for n in names):
                errors.append((path, f"must be {' or '.join(names)}, got {_describe(value)}"))
                return

        if isinstance(value, dict):
            self._check_object(value, schema, path, errors)
        elif isinstance(value, list):
            self._check_array(value, schema, path, errors)
        elif isinstance(value, str):
            self._check_string(value, schema, path, errors)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self._check_number(value, schema, path, errors)

    def _check_object(self, value: dict, schema: dict, path: str, errors: list) -> None:
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append((_join(path, name), "is required and is missing"))
        extra = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in props:
                self._check(sub, props[key], _join(path, key), errors)
            elif extra is False:
                known = ", ".join(sorted(props)) or "(none)"
                errors.append((_join(path, key), f"is not a known field here; allowed: {known}"))
            elif isinstance(extra, dict):
                self._check(sub, extra, _join(path, key), errors)

    def _check_array(self, value: list, schema: dict, path: str, errors: list) -> None:
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append((path, f"must have at least {schema['minItems']} item(s), got {len(value)}"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append((path, f"must have at most {schema['maxItems']} item(s), got {len(value)}"))
        if schema.get("uniqueItems") and len(value) != len({repr(v) for v in value}):
            errors.append((path, "must not contain duplicate entries"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                self._check(item, item_schema, f"{path}[{i}]", errors)

    def _check_string(self, value: str, schema: dict, path: str, errors: list) -> None:
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append((path, f"must be at least {schema['minLength']} character(s) long"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append((path, f"must be at most {schema['maxLength']} character(s) long"))
        pattern = schema.get("pattern")
        if pattern is not None and not re.search(pattern, value):
            errors.append((path, f"must match {pattern} — got {value!r}"))

    def _check_number(self, value: Any, schema: dict, path: str, errors: list) -> None:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append((path, f"must be >= {schema['minimum']}, got {value}"))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append((path, f"must be <= {schema['maximum']}, got {value}"))


def keywords_used(schema: Any) -> set[str]:
    """Every schema keyword appearing anywhere in `schema`.

    Walks only the positions where a keyword can legally appear, so a PROPERTY named `type` or
    `items` in an application schema is not mistaken for the keyword of that name.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key, sub in node.items():
            found.add(key)
            if key == "properties" and isinstance(sub, dict):
                for child in sub.values():
                    walk(child)
            elif key == "$defs" and isinstance(sub, dict):
                for child in sub.values():
                    walk(child)
            elif key in ("items", "additionalProperties"):
                walk(sub)
            elif key in ("enum", "const", "required", "type"):
                continue
            else:
                walk(sub)

    walk(schema)
    return found
