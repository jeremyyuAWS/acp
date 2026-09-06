#!/usr/bin/env python3
"""Verify an approved SharePoint release canary from a credential-free evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalized(value: Any) -> Any:
    """Canonicalize permission arrays whose provider order is not meaningful."""
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [_normalized(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return value


def verify(bundle: dict, *, base: Path) -> dict:
    """Return a machine-readable report; every required claim must pass."""
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    response = bundle.get("manifest_response") or {}
    manifest = response.get("manifest") or {}
    recorded = ((response.get("content_digest") or {}).get("value") or "").lower()
    actual = _canonical_digest(manifest)
    check("manifest digest", recorded == actual,
          f"recorded={recorded or 'missing'} computed={actual}")
    check("SharePoint source", manifest.get("source") == "sharepoint",
          f"source={manifest.get('source')!r}")
    check("non-destructive release claim", manifest.get("original_files_unchanged") is True,
          f"original_files_unchanged={manifest.get('original_files_unchanged')!r}")
    counts = manifest.get("counts") or {}
    check("single successful document",
          counts == {"total": 1, "published": 1, "failed": 0, "remaining": 0},
          f"counts={counts}")
    documents = manifest.get("documents") or []
    check("one manifest document", len(documents) == 1,
          f"documents={len(documents)}")
    document = documents[0] if len(documents) == 1 else {}
    check("published and verified",
          document.get("status") == "published" and bool(document.get("verification")),
          f"status={document.get('status')!r} verification={document.get('verification')!r}")
    source_id = document.get("source_document_id")
    released_id = document.get("released_document_id")
    check("distinct provider identities", bool(source_id and released_id and source_id != released_id),
          f"source={source_id!r} released={released_id!r}")
    check("usable destination link",
          str(document.get("released_document_url") or "").startswith("https://"),
          f"url={document.get('released_document_url')!r}")

    expected = bundle.get("expected") or {}
    check("source path", document.get("source_relative_path") == expected.get("source_relative_path"),
          f"actual={document.get('source_relative_path')!r}")
    check("destination path",
          document.get("destination_relative_path") == expected.get("destination_relative_path"),
          f"actual={document.get('destination_relative_path')!r}")
    release_folder = manifest.get("release_folder")
    roots = manifest.get("roots") or []
    check("release folder identity",
          bool(release_folder and len(roots) == 1 and
               roots[0].get("folder_name") == release_folder and roots[0].get("folder_id") and
               str(roots[0].get("folder_url") or "").startswith("https://")),
          f"release_folder={release_folder!r} roots={len(roots)}")
    expected_provider_path = "/".join(filter(None, [
        "Remediated", release_folder, document.get("destination_relative_path")]))
    observed_provider_path = str(expected.get("provider_destination_path") or "").strip("/")
    check("provider folder placement", observed_provider_path == expected_provider_path,
          f"observed={observed_provider_path!r} expected={expected_provider_path!r}")

    artifacts = bundle.get("artifacts") or {}
    try:
        before = _sha256(base / artifacts["original_before"])
        after = _sha256(base / artifacts["original_after"])
        corrected = _sha256(base / artifacts["corrected"])
        check("original unchanged", before == after, f"before={before} after={after}")
        check("corrected checksum", corrected == document.get("corrected_sha256"),
              f"file={corrected} manifest={document.get('corrected_sha256')!r}")
    except (KeyError, OSError) as exc:
        check("artifact evidence", False, str(exc))

    permissions = bundle.get("permissions") or {}
    try:
        source_before = _json(base / permissions["source_before"])
        source_after = _json(base / permissions["source_after"])
        destination = _json(base / permissions["destination"])
        expected_destination = _json(base / permissions["expected_destination"])
        source_same = _normalized(source_before) == _normalized(source_after)
        destination_same = _normalized(destination) == _normalized(expected_destination)
        check("source permissions unchanged", source_same,
              "canonical permission snapshots match" if source_same else
              "source permission snapshots differ")
        check("destination permissions", destination_same,
              "destination matches approved expectation" if destination_same else
              "destination permissions differ from approved expectation")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        check("permission evidence", False, str(exc))

    failures = [row for row in checks if not row["passed"]]
    return {"passed": not failures, "checks": checks, "failed_checks": len(failures)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a credential-free SharePoint release canary evidence bundle.")
    parser.add_argument("bundle", type=Path, help="JSON evidence bundle")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    args = parser.parse_args()
    bundle_path = args.bundle.resolve()
    report = verify(_json(bundle_path), base=bundle_path.parent)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
