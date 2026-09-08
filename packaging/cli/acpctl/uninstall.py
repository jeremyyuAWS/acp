"""`acpctl uninstall` — remove the release, say what that will destroy, and say what it will not.

IT PREVIEWS BY DEFAULT, AND THAT IS THE FEATURE. `helm uninstall` is one line and removes the
release immediately; nobody needs a wrapper for that. What an operator does not have is an answer
to "what am I about to lose, and what survives this?" before they find out — so running this
command with no flags changes NOTHING and prints both lists. Acting requires `--yes`.

THE RETAINED LIST IS AS IMPORTANT AS THE REMOVED ONE, and it is the half tools normally omit.
ACP's Postgres, Redis and object storage are supplied by the infrastructure adapter, not by the
chart (ADR 0048, Decision 1) — they are frequently managed cloud services holding every document
and every assessment the installation ever produced. `helm uninstall` cannot touch them and this
command will not either, whatever `--data-policy` says. An operator who reads "uninstalled" and
assumes their data went with it will go looking for a database that is still running and still
being billed; one who assumes it was kept when it was not has lost it. Both are avoidable by
printing the list.

--data-policy HAS NO DEFAULT, ON PURPOSE. `retain` and `delete` are opposite answers to a question
only the operator can answer, and a default would be this tool answering it for them — silently,
in the direction whoever wrote the default happened to prefer. `delete` additionally requires
typing the release name into `--confirm-name`, which is the pattern every tool that deletes
storage converged on because reading a prompt and meaning it are different acts.

WHAT `delete` CAN ACTUALLY DELETE: in-cluster PersistentVolumeClaims carrying this release's
`app.kubernetes.io/instance` label, and nothing else (see helm.check_kubectl). If there are none,
it says so rather than printing a reassuring "data deleted" that describes no event — a message
that would send somebody away believing customer documents were destroyed when they are sitting
in a storage account.
"""
from __future__ import annotations

from typing import Callable

from . import __version__
from . import spec as spec_mod
from . import state as state_mod
from .helm import STATE_CONFIGMAP, CommandFailed, Helm, ToolUnavailable
from .install import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, Outcome

RETAIN = "retain"
DELETE = "delete"
DATA_POLICIES = (RETAIN, DELETE)


def _data_service_lines(document: dict) -> list[str]:
    """The adapter-supplied services, and their mode, for the retained list.

    Read from the document rather than from the cluster because that is the only place they are
    described at all — the chart renders no Postgres, no Redis and no object storage, so there is
    nothing in the namespace to enumerate. Their absence from a `kubectl get` is exactly why an
    operator can believe an uninstall took them with it.
    """
    data = document.get("data") or {}
    labels = {"postgres": "Postgres", "redis": "Redis", "objectStorage": "Object storage"}
    lines = []
    for key, label in labels.items():
        mode = (data.get(key) or {}).get("mode", "(not stated)")
        lines.append(f"{label} ({mode}) — supplied by the infrastructure adapter, not by this "
                     f"release. Not touched, whatever --data-policy says.")
    return lines


def uninstall(document_path: str, *, namespace: str, release_name: str | None = None,
              data_policy: str | None = None, assume_yes: bool = False,
              confirm_name: str | None = None, context: str | None = None,
              helm: Helm | None = None, echo: Callable[[str], None] = print) -> Outcome:
    """Preview, or perform, the removal of one ACP installation."""
    helm = helm if helm is not None else Helm(context=context)

    if not namespace:
        return Outcome(EXIT_USAGE, reason="a namespace is required (-n/--namespace)")
    if data_policy is not None and data_policy not in DATA_POLICIES:
        return Outcome(EXIT_USAGE,
                       reason=f"--data-policy must be one of {', '.join(DATA_POLICIES)}")

    try:
        document = spec_mod.load_document(document_path)
    except (OSError, ValueError) as exc:
        return Outcome(EXIT_USAGE, reason=f"could not read {document_path}: {exc}")

    # DELIBERATELY NOT REFUSED FOR AN INVALID DOCUMENT. `install` refuses, because installing
    # something that does not satisfy the contract creates a system nobody described. Removal is
    # the opposite: a document that has stopped validating (a rule was added, a field was
    # hand-edited) describes an installation that is running RIGHT NOW, and refusing to uninstall
    # it would strand the exact installation most likely to need removing.
    result = spec_mod.validate(document)
    if not result.ok:
        echo(f"  note: {document_path} no longer satisfies the contract "
             f"({len(result.errors)} error(s)). Proceeding — an invalid document still describes "
             f"a running installation, and refusing here would strand it.")

    release = release_name or (document.get("metadata") or {}).get("name") or "acp"

    try:
        live = helm.release_state(release, namespace)
        prior, unreadable = helm.read_state(namespace)
        objects, objects_error = helm.manifest_objects(release, namespace) if live.exists else ([], "")
        pvcs, pvc_error = helm.owned_pvcs(release, namespace)
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))

    # ── the preview, printed whether or not we go on to act ───────────────────
    echo(f"acpctl uninstall — {document_path}")
    echo(f"release {release} in namespace {namespace}")
    echo("")
    echo("WOULD REMOVE" if not assume_yes else "REMOVING")
    if live.exists is None:
        echo(f"  ????  could not establish whether release {release!r} exists: {live.reason}")
    elif not live.exists:
        echo(f"  (nothing) helm reports no release {release!r} in {namespace}")
    else:
        echo(f"  helm release {release} (revision {live.revision}, status {live.status})")
        for obj in objects or []:
            echo(f"    - {obj}")
        if objects_error:
            echo(f"    ????  could not list the release's objects: {objects_error}")
    if prior:
        echo(f"  configmap/{STATE_CONFIGMAP} — the installation record for "
             f"{(prior.get('installation') or {}).get('name', '?')}")
    elif unreadable:
        echo(f"  ????  could not read configmap/{STATE_CONFIGMAP}: {unreadable}")

    if pvcs is None:
        echo(f"  ????  could not list this release's PersistentVolumeClaims: {pvc_error}")
    elif pvcs and data_policy == DELETE:
        for name in pvcs:
            echo(f"  persistentvolumeclaim/{name} — DELETED, and its contents with it "
                 f"(--data-policy delete)")
    elif pvcs:
        echo(f"  (retained) {len(pvcs)} PersistentVolumeClaim(s): {', '.join(pvcs)}"
             + ("" if data_policy else " — pass --data-policy to decide"))

    echo("")
    echo("RETAINED — NOT OWNED BY THIS RELEASE, AND NOT TOUCHED BY ANY --data-policy")
    for line in _data_service_lines(document):
        echo(f"  {line}")
    echo(f"  Secrets in {(document.get('secrets') or {}).get('provider', 'the platform vault')} "
         f"— referenced by the release, owned by you.")
    echo(f"  Namespace {namespace} itself, and anything else in it.")
    if pvcs is not None and not pvcs:
        echo("  This release owns NO in-cluster PersistentVolumeClaims, so there is no "
             "in-cluster data for --data-policy to act on either way.")
    echo("")

    if not assume_yes:
        echo("PREVIEW ONLY — nothing was changed, and no command that could change anything was "
             "run.")
        echo(f"To act: acpctl uninstall {document_path} -n {namespace} --yes "
             f"--data-policy {{retain|delete}}")
        return Outcome(EXIT_OK, state=prior, changed=False, reason="preview only")

    # ── from here on it is real ───────────────────────────────────────────────
    if data_policy is None:
        return Outcome(EXIT_USAGE, reason=(
            "refusing to uninstall: --data-policy is required and has no default. `retain` and "
            "`delete` are opposite answers about the installation's data, and a default would be "
            "acpctl answering that for you."))
    if data_policy == DELETE:
        if confirm_name is None:
            return Outcome(EXIT_USAGE, reason=(
                f"--data-policy delete requires --confirm-name {release}. Deleting a "
                f"PersistentVolumeClaim destroys its contents with no undo, so the release name "
                f"has to be typed rather than agreed to."))
        if confirm_name != release:
            return Outcome(EXIT_REFUSED, reason=(
                f"--confirm-name {confirm_name!r} does not match the release being removed "
                f"({release!r}). Refusing — the mismatch is more likely to mean the wrong "
                f"namespace than a typo."))

    if live.exists is None:
        return Outcome(EXIT_REFUSED, reason=(
            f"could not establish whether release {release!r} exists in {namespace}: "
            f"{live.reason}. Refusing to run destructive commands against an unknown."))
    if not live.exists and not prior:
        return Outcome(EXIT_REFUSED, reason=(
            f"nothing to uninstall: no helm release {release!r} and no installation record in "
            f"{namespace}. Reported as a failure rather than a success, because 'we removed "
            f"nothing' is not the same answer as 'we removed it'."))

    removed_pvcs: list[str] = []
    try:
        if live.exists:
            echo(f"  helm uninstall {release}")
            helm.uninstall(release, namespace)
        if data_policy == DELETE and pvcs:
            echo(f"  deleting {len(pvcs)} PersistentVolumeClaim(s) owned by {release}")
            helm.delete_owned_pvcs(release, namespace)
            removed_pvcs = list(pvcs)
    except (CommandFailed, ToolUnavailable) as exc:
        return Outcome(EXIT_REFUSED, state=prior, changed=True, reason=(
            f"the uninstall did not complete: {exc}\n"
            f"Some of the release may be gone. The installation record was left in place — run "
            f"`acpctl status {document_path} -n {namespace}` to see what remains."))

    # ── record, then remove the record ────────────────────────────────────────
    #
    # The history entry is written into the in-cluster state BEFORE that state is deleted, so the
    # ConfigMap is never in a position of describing an installation that has already been
    # removed without saying so. It is then deleted along with the release, and the copy printed
    # here is the surviving record — which is why the command prints where it went.
    final = state_mod.with_history(
        prior or _stub_state(document, namespace, release),
        state_mod.history_entry(state_mod.ACTION_UNINSTALL, helm_revision=live.revision,
                                result=state_mod.RESULT_OK))
    recorded_in_cluster = False
    try:
        helm.write_state(namespace, final)
        recorded_in_cluster = True
    except (CommandFailed, ToolUnavailable) as exc:
        echo(f"  (the uninstall could not be recorded in the cluster before removal: {exc})")

    try:
        helm.delete_state(namespace)
    except (CommandFailed, ToolUnavailable) as exc:
        echo(f"  (configmap/{STATE_CONFIGMAP} could not be removed: {exc})")

    echo("")
    if recorded_in_cluster:
        echo(f"  the uninstall was recorded in configmap/{STATE_CONFIGMAP} in {namespace}, and "
             f"that ConfigMap was then removed with the release.")
    echo("  THE RECORD PRINTED HERE (and by --json) IS THE SURVIVING COPY — keep it. Nothing in "
         "the cluster now describes what was installed.")
    if data_policy == DELETE:
        if removed_pvcs:
            echo(f"  deleted PersistentVolumeClaims: {', '.join(removed_pvcs)}")
        else:
            echo("  --data-policy delete removed NO data: this release owns no in-cluster "
                 "PersistentVolumeClaims. The adapter-supplied Postgres, Redis and object "
                 "storage listed above are untouched and still hold everything they held.")
    else:
        echo("  --data-policy retain: no volume was deleted.")

    return Outcome(EXIT_OK, state=final, changed=True,
                   reason=f"{release} removed from {namespace}")


def _stub_state(document: dict, namespace: str, release: str) -> dict:
    """A minimal state for an installation that has no record of its own.

    An installation put there by `helm install` directly, or by an acpctl too old to write one,
    still deserves an uninstall record — and printing "no record found" instead would leave the
    removal itself undocumented, which is the gap this whole file exists to close.
    """
    meta = document.get("metadata") or {}
    runtime = document.get("runtime") or {}
    return {
        "apiVersion": state_mod.API_VERSION,
        "kind": state_mod.KIND,
        "installation": {
            "name": meta.get("name", ""), "namespace": namespace, "releaseName": release,
            "profile": runtime.get("profile", ""), "platform": runtime.get("platform", ""),
            "environment": meta.get("environment", ""), "version": runtime.get("version", ""),
        },
        "document": {"path": "", "sha256": ""},
        "release": {"revision": None, "version": runtime.get("version", ""), "pinned": False,
                    "components": {}, "manifestSha256": None},
        "chart": {"name": "", "version": "", "appVersion": "", "valuesSha256": ""},
        "recordedAt": state_mod.now_rfc3339(),
        "acpctlVersion": __version__,
        "flags": {"skipPreflight": False, "adopted": False, "allowUnpinned": False},
        # SAID PLAINLY IN THE RECORD ITSELF. A stub that looked like a real installation state
        # would be a file asserting facts (unpinned, no chart version) that were never observed.
        "note": "no installation record existed in this namespace; this stub was built from the "
                "deployment document at uninstall time, and its release/chart fields were never "
                "observed.",
        "history": [],
    }
