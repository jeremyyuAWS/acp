"""The install-state document — what was installed here, recorded where the next operator looks.

PRD S20.12 requires every deployment to produce a redacted, immutable installation manifest, and
this is it. It answers, without a git history or a memory of the afternoon: which document
installed this, at which sha; which images by DIGEST; which chart at which version; whether the
release was pinned at all; which safety flags were passed; and what has happened to this
installation since.

WHERE IT LIVES, AND WHY BOTH PLACES. It is written as a ConfigMap in the release namespace, so it
travels with the cluster rather than with whoever ran the install — a laptop-local record is
worthless to the person debugging at 3am six months later. It is also printed on stdout with
`--json`, because the in-cluster copy is deleted by `acpctl uninstall` and the printed copy is
then the only surviving record of what was removed.

IT CONTAINS NO SECRETS, AND THAT IS CHECKED RATHER THAN INTENDED. The deployment document holds
secret REFERENCES (a vault entry's name and key), never values — but a reference name can be
sensitive on its own, and a connection string reaching this file would be a credential committed
to a ConfigMap that every reader of the namespace can list. `secret_leaks()` below is run before
the state is ever written, so a future field that starts carrying one fails the install instead of
publishing it.

WHY THE HISTORY IS A LIST AND NOT A COUNTER. "Installed at 14:02, uninstalled at 14:40, installed
again at 15:10" is the shape of an incident, and the shape is the information. A single
`lastAction` would answer "what is the state now", which the rest of the document already answers.

WHY A RE-RUN DOES NOT APPEND. `install` is `helm upgrade --install`, so running it twice with the
same document is a legitimate and common thing to do — in a CI job, after a network blip, out of
uncertainty about whether the first run finished. If each of those appended an entry, the history
would fill with events that did not happen, and the one time it mattered the real sequence would
be buried. `same_installation()` is what makes the second run a no-op.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

API_VERSION = "packaging.acp.mova.io/v1alpha1"
KIND = "ACPInstallation"

ACTION_INSTALL = "install"
ACTION_UNINSTALL = "uninstall"
RESULT_OK = "ok"
RESULT_FAILED = "failed"

# A ConfigMap's total size is capped at 1MiB by the API server, and an installation that
# reinstalls nightly would reach that in a few years of history. Keeping the most recent entries
# means the record degrades by losing the oldest events rather than by failing to write at all —
# a write that starts failing is a record that silently stops being updated.
MAX_HISTORY = 50


def now_rfc3339() -> str:
    """UTC, second precision, Z-suffixed. Local time in a record that outlives the operator who
    made it is an ambiguity nobody can resolve later."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chart_metadata(chart_dir: str | Path) -> dict[str, str]:
    """name/version/appVersion out of Chart.yaml.

    Parsed with PyYAML when it is there and with a flat key scan when it is not. acpctl ships in
    the air-gapped bundle with almost no dependencies (see cluster.py), and the three fields this
    needs are all unindented scalars — so the fallback is exact for this file rather than a
    general YAML parser written badly.
    """
    path = Path(chart_dir) / "Chart.yaml"
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        data: dict[str, Any] = {}
        for line in text.splitlines():
            if line.startswith(("name:", "version:", "appVersion:")):
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip('"').strip("'")
    else:
        data = yaml.safe_load(text) or {}
    return {
        "name": str(data.get("name", "")),
        "version": str(data.get("version", "")),
        "appVersion": str(data.get("appVersion", "")),
    }


def build(document: dict, *, namespace: str, release_name: str, document_path: str,
          document_sha256: str, values_sha256: str, chart: dict[str, str],
          components: dict[str, dict[str, str]], pinned: bool, manifest_sha256: str | None,
          helm_revision: int | None, flags: dict[str, bool],
          history: list[dict] | None = None, recorded_at: str | None = None) -> dict:
    """The state document for one installation. A pure function of its arguments."""
    meta = document.get("metadata") or {}
    runtime = document.get("runtime") or {}
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "installation": {
            "name": meta.get("name", ""),
            "namespace": namespace,
            "releaseName": release_name,
            "profile": runtime.get("profile", ""),
            "platform": runtime.get("platform", ""),
            "environment": meta.get("environment", ""),
            "version": runtime.get("version", ""),
        },
        "document": {"path": document_path, "sha256": document_sha256},
        "release": {
            "revision": helm_revision,
            "version": runtime.get("version", ""),
            # FALSE IS A REAL VALUE HERE, not an absence. An operator who passed --allow-unpinned
            # gets it written down, so the next person can tell an audited release from one whose
            # images were tags at install time and may since have moved.
            "pinned": bool(pinned),
            "components": components,
            "manifestSha256": manifest_sha256,
        },
        "chart": {
            "name": chart.get("name", ""),
            "version": chart.get("version", ""),
            "appVersion": chart.get("appVersion", ""),
            "valuesSha256": values_sha256,
        },
        "recordedAt": recorded_at or now_rfc3339(),
        "acpctlVersion": __version__,
        "flags": {
            "skipPreflight": bool(flags.get("skipPreflight")),
            "adopted": bool(flags.get("adopted")),
            "allowUnpinned": bool(flags.get("allowUnpinned")),
        },
        "history": list(history or []),
    }


def history_entry(action: str, *, helm_revision: int | None, result: str,
                  at: str | None = None) -> dict:
    return {"action": action, "at": at or now_rfc3339(), "helmRevision": helm_revision,
            "result": result}


def with_history(state: dict, entry: dict) -> dict:
    """`state` with one entry appended, oldest entries dropped past MAX_HISTORY."""
    out = json.loads(json.dumps(state))
    out["history"] = (list(out.get("history") or []) + [entry])[-MAX_HISTORY:]
    return out


def same_installation(prior: dict | None, candidate: dict) -> bool:
    """Would installing `candidate` change anything `prior` recorded?

    THE THREE HASHES ARE THE WHOLE COMPARISON, and each covers something the others do not:

      document.sha256    the reviewed input, byte for byte
      chart.valuesSha256 the rendered values INCLUDING the resolved digests, so a release
                         manifest that moved one image changes this even when the document did not
      release.manifestSha256  the manifest file itself, so a manifest edit that does not reach the
                         values (a revision bump, say) is still a difference

    Timestamps, history and the helm revision are deliberately excluded: they change on every
    run by construction, and comparing them would make "identical" impossible and the no-op path
    dead code.

    A prior run that ended in `failed` is NOT the same installation however well the hashes
    match — the point of re-running it is that the last attempt did not land.
    """
    if not prior:
        return False
    history = prior.get("history") or []
    if history and history[-1].get("result") != RESULT_OK:
        return False
    if (history and history[-1].get("action") == ACTION_UNINSTALL):
        return False
    for section, key in (("document", "sha256"), ("chart", "valuesSha256"),
                         ("release", "manifestSha256")):
        if (prior.get(section) or {}).get(key) != (candidate.get(section) or {}).get(key):
            return False
    installed = prior.get("installation") or {}
    wanted = candidate.get("installation") or {}
    return all(installed.get(k) == wanted.get(k)
               for k in ("name", "namespace", "releaseName", "version"))


def occupant_conflict(prior: dict | None, *, release_name: str, document_name: str
                      ) -> str | None:
    """Is this namespace already somebody else's ACP installation? The reason, or None.

    NAMESPACE ISOLATION IS THE ONE THING A HELM RELEASE NAME DOES NOT GIVE YOU. Two releases with
    different names install cleanly side by side in one namespace, and the result is two ACP
    installations sharing a NetworkPolicy, a set of PVC names and a database whose connection
    budget was computed for one of them. Neither helm nor Kubernetes objects to it. The
    install-state ConfigMap is what makes the collision visible, because there is only one of it
    per namespace.
    """
    if not prior:
        return None
    installed = prior.get("installation") or {}
    if installed.get("releaseName") and installed["releaseName"] != release_name:
        return (f"namespace already holds helm release {installed['releaseName']!r}, and this "
                f"install would create {release_name!r} alongside it")
    if installed.get("name") and installed["name"] != document_name:
        return (f"namespace already holds the installation described by document "
                f"{installed['name']!r}, and this document describes {document_name!r}")
    return None


def secret_leaks(state: dict, document: dict) -> list[str]:
    """Anything from the document's secret configuration that reached the state. Empty is correct.

    RUN BEFORE THE STATE IS WRITTEN, not only in a test. A ConfigMap is readable by anything with
    `get configmaps` in the namespace and is not a secret store; a connection string arriving here
    would be a credential published to a wider audience than the Secret it came from, by a tool
    whose whole job is to be the auditable record. Checking at write time means a future field
    that starts carrying one fails the install rather than shipping.

    Checks the REFERENCE names and keys as well as anything that looks like a connection string,
    because a vault path can name a customer or an environment that PRD S13 keeps out of
    generated output.

    SEARCHES THE VALUES, NOT THE SERIALISED DOCUMENT. A naive `json.dumps(state)` scan matches the
    state's own FIELD NAMES too, so a deployment whose secret ref happens to be keyed `version`
    or `name` would be reported as leaking and the install would be refused over a coincidence.
    A refusal that fires on correct input is one that gets removed, taking the real check with it.

    Short reference values are skipped for the same reason: a three-character vault key matches
    something by accident in almost any document, and this must not cry wolf.
    """
    haystack = "\n".join(_string_values(state))
    found: list[str] = []
    refs = ((document.get("secrets") or {}).get("refs") or {})
    for name, ref in refs.items():
        for field in ("name", "key", "version"):
            value = str((ref or {}).get(field) or "")
            if len(value) >= 4 and value in haystack:
                found.append(f"secrets.refs.{name}.{field}")
    for scheme in ("postgres://", "postgresql://", "redis://", "rediss://", "amqp://",
                   "mongodb://", "mysql://", "AccountKey=", "-----BEGIN"):
        if scheme in haystack:
            found.append(f"a {scheme} credential")
    return sorted(set(found))


def _string_values(node: Any) -> list[str]:
    """Every string VALUE in a nested structure, ignoring the keys that name them."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _string_values(value)]
    if isinstance(node, (list, tuple)):
        return [s for item in node for s in _string_values(item)]
    return []
