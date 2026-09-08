"""`acpctl support-bundle` — everything a support engineer needs, and nothing a customer owns.

WHAT THIS IS FOR. When an installation misbehaves, the questions are always the same: what image
actually ran, which pods restarted and why, did the migration hook finish, is KEDA reconciling the
ScaledObjects, does the deployment document still describe what is deployed. Answering them by
email takes days of "can you also send me…". This collects all of it in one read-only pass and
writes a directory the operator can INSPECT before sending, which is the point of writing a
directory rather than only a tarball.

THE SAFETY CONSTRAINT IS ABSOLUTE AND IT IS WHY THIS MODULE IS MOSTLY A FILTER. PRD S13: "Secrets
are referenced from the platform secret manager and never appear in generated manifests, logs,
plans or support bundles… Support bundles redact tokens, document names, user identities and file
contents." PRD S20.6 states it as an acceptance criterion. A bundle is an artifact that travels —
into a ticket, an email thread, a vendor's issue tracker — so a leak here is a leak into places
nobody can recall it from. Every byte written passes through `Redactor`, and `verify_bundle()`
re-reads what was written and looks for anything the filter should have caught. A bundle that
fails its own scan is DELETED rather than reported as written: a leaking artifact on disk is worse
than no artifact, because the operator believes the redaction happened.

WHAT IT DELIBERATELY DOES NOT COLLECT: anything from the application's own data. No object-storage
objects, no database rows, no document names, no user identities, no job payloads, no container
LOGS. This bundle is about the INSTALLATION, not about the customer's documents — and `kubectl
logs` is not in `cluster.READ_VERBS` at all, so that boundary is enforced by the same allow-list
that keeps acpctl read-only rather than by this module's good intentions. `test_packaging_support_
bundle.py::test_the_bundle_never_reaches_for_customer_document_data` names the boundary.

READS GO THROUGH cluster.run(), WHICH IS THE WHOLE READ-ONLY GUARANTEE. That function holds the
verb allow-list, and a second subprocess helper here would be a second place the promise does not
apply — which is exactly how the phase-0 `open()` guard came to miss the kubectl path.

THREE OUTCOMES PER COLLECTION, NOT TWO, for the same reason `doctor` has three: SUCCEEDED, FAILED
and SKIPPED, each recorded in `manifest.json` with a reason. A bundle that silently omits what it
could not collect sends a support engineer looking in the wrong place — "there are no Events" and
"we were not allowed to read Events" lead to opposite investigations, and the difference between
them is one field.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import shutil
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import cluster as cluster_mod
# Mirrored rather than re-derived: doctor's `_has_api` knows that `kubectl api-resources -o name`
# prints `<plural>.<group>`, so a group has to be matched as a SUFFIX and a resource as a prefix.
# Re-implementing that here is how the two commands would come to disagree about whether a cluster
# has KEDA — and doctor's own docstring records that getting it wrong produced a check that was
# always wrong in one direction while its test passed.
from .doctor import ENFORCING_CNI_DAEMONSETS, NON_ENFORCING_CNI_DAEMONSETS, _has_api

SUCCEEDED, FAILED, SKIPPED = "SUCCEEDED", "FAILED", "SKIPPED"

# The install-state record `acpctl install` writes. Read OPPORTUNISTICALLY by name and by name
# only: its absence is normal (a chart installed by hand never writes one, and it postdates some
# installations), so a missing one is SKIPPED with a reason rather than an error. Read by name
# instead of found in the ConfigMap listing because the two need different RBAC — an operator may
# be allowed to get one ConfigMap and not to list them all, and in that case this is the single
# most valuable object in the bundle.
INSTALL_STATE_CONFIGMAP = "acp-installation"

# Events are unbounded and mostly repetition; the recent ones are what diagnose an install. Capped
# so a namespace mid-crashloop cannot produce a hundred-megabyte bundle nobody can attach.
MAX_EVENTS = 300


class SupportBundleError(RuntimeError):
    """The bundle could not be produced at all — a refused output path, an unwritable directory.

    Distinct from a collection that failed: that is recorded IN the bundle, which still gets
    written, because a partial bundle is worth having and a partial bundle that says which parts
    are missing is worth having a great deal.
    """


# ══════════════════════════════════════════════════════════════════════════════
# Redaction
# ══════════════════════════════════════════════════════════════════════════════
#
# HOW THE PLACEHOLDER IS CHOSEN, AND WHY NOT A HASH. Two properties are wanted at once: the same
# input must always produce the same output (so two operators generating a bundle from the same
# state can diff them, and so "run it again and compare" is a cheap way to convince yourself the
# filter is not sampling), and the same secret VALUE must map to the same placeholder within one
# bundle (so a reader can still see that the API tier and the worker tier share a password, which
# is frequently the bug, without learning what it is).
#
# A salted hash gives both, and it was rejected for both of its variants:
#
#   * With a FIXED salt the placeholder becomes an ORACLE. Anyone holding the bundle can hash
#     candidate values and check for a match — so for any low-entropy secret (a staging password,
#     a tenant name, a short token) the bundle does not hide the value, it merely makes you guess
#     it once. Redaction whose output confirms a guess is not redaction.
#   * With a PER-BUNDLE RANDOM salt the oracle is gone, and so is reproducibility: the same
#     cluster produces a different bundle every time, and the determinism test degenerates into
#     asserting the structure rather than the bytes.
#
# A per-bundle counter in encounter order has neither problem. It carries no information about the
# value beyond the equality relation, which is precisely the fact we intend to preserve, and it is
# a pure function of the input and the traversal order — so byte-identical input gives
# byte-identical output with no secret state to record, keep or leak.
#
# The placeholder deliberately contains no `:` or `=`, so it can never be re-matched as the value
# half of a `name: value` assignment, and it is protected before every scan so redaction is
# idempotent: redact(redact(x)) == redact(x).

_PLACEHOLDER_RE = re.compile(r"REDACTED\[[a-z0-9.\-]{1,60}#\d+\]")

# Image digests must SURVIVE. "What actually ran" is the single most useful fact in the bundle,
# and a digest is 64 hex characters that every entropy heuristic in the world wants to eat. They
# are protected before any scan rather than exempted afterwards, so no later rule can reach them.
_IMAGE_DIGEST_RE = re.compile(r"\bsha(?:256|512):[0-9a-f]{32,}\b")

# The names that mean "the thing after this is a credential". Used two ways: as a word list for
# structured KEYS (where the structure guarantees the name is a field name), and inside the
# assignment patterns below for free text.
_SECRET_WORDS = (
    "password", "passwd", "passphrase", "secret", "token", "credential", "apikey",
    "accesskey", "privatekey", "connectionstring", "authorization", "signature", "salt",
    "sastoken", "sasurl", "clientsecret", "sessionkey", "accountkey",
)

# The same idea for free text, where the name arrives with its separators intact.
_SECRET_NAME_TEXT = (
    r"[A-Za-z0-9_.\-]*(?:"
    r"passwd|password|passphrase|secret|token|credential|"
    r"api[_.\-]?key|access[_.\-]?key|private[_.\-]?key|account[_.\-]?key|session[_.\-]?key|"
    r"connection[_.\-]?string|authorization|signature|"
    r"[A-Za-z0-9]+[_.\-]key"
    r")[A-Za-z0-9_.\-]*"
)

# The shape rules, in priority order: an earlier rule claims its span and a later one cannot
# reach inside it. Where a pattern names a group `secret`, only that group is replaced — which is
# how `Authorization: Bearer xyz` keeps its header name and loses its credential.
#
# THE ASSIGNMENT RULES NEVER CROSS A NEWLINE (`[ \t]*` rather than `\s*`), and that is not a
# detail. With `\s*` the pattern walks off the end of a YAML key whose value is a nested block —
# `langfuse-secret-key:\n  key: langfuse-secret-key` — and redacts the FOLLOWING line, which in
# the deployment document is the secret REFERENCE the whole document is built out of. The bundle
# would lose exactly the information PRD S9 says a document contains ("secret references only,
# never raw secrets") in order to hide something that was never there.
_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # PEM blocks first: they contain base64 that every other rule would fragment.
    ("pem-private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    # A service-account JSON's private_key, whose PEM arrives with literal \n escapes.
    ("gcp-service-account-key", re.compile(
        r"\"private_key\"\s*:\s*\"(?P<secret>[^\"]{16,})\"")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")),
    # Redacted WHOLE, host included. Partial rewriting of a URL is where redactors leak: the
    # userinfo can be percent-encoded, repeated in a query parameter, or split across a proxy
    # rewrite. The topology the host would have told you is in the Service and Ingress objects
    # and in the deployment document, both of which are in this bundle.
    ("connection-string", re.compile(
        r"\b(?:postgres|postgresql|redis|rediss|amqp|amqps|mongodb\+srv|mongodb|mysql|mssql)"
        r"://[^\s'\"<>,;)\]}]+", re.I)),
    ("azure-storage-connection-string", re.compile(
        r"\bDefaultEndpointsProtocol=[^\s'\"<>]+", re.I)),
    ("azure-sas-url", re.compile(r"\bhttps?://[^\s'\"<>]*[?&]sig=[^\s'\"<>]+", re.I)),
    ("azure-sas-token", re.compile(r"\bsig=(?P<secret>[A-Za-z0-9%+/=_\-]{16,})", re.I)),
    # 88 characters of base64 ending in `==` is the Azure storage account key shape and almost
    # nothing else.
    ("azure-storage-account-key", re.compile(r"\b[A-Za-z0-9+/]{86}==")),
    ("url-userinfo", re.compile(
        r"\b[a-z][a-z0-9+.\-]*://[^\s/@'\"<>]+:[^\s/@'\"<>]+@[^\s'\"<>,;)\]}]+", re.I)),
    ("aws-access-key-id", re.compile(
        r"\b(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA)[0-9A-Z]{16}\b")),
    # An Authorization header is redacted TO THE END OF ITS VALUE rather than to the next space.
    # `Authorization: Basic dXNlcjpwYXNz` is the case that decides it: stopping at whitespace
    # would redact the word "Basic" and publish the credential after it. The quoted form is tried
    # first so a JSON line keeps its structure; the bare form then overlaps it and is dropped.
    ("authorization-header", re.compile(
        r"(?i)\b(?:proxy-)?authorization\"?[ \t]*[:=][ \t]*\"(?P<secret>[^\"\r\n]+)\"")),
    ("authorization-header", re.compile(
        r"(?i)\b(?:proxy-)?authorization[ \t]*[:=][ \t]*(?P<secret>[^\r\n]+)")),
    ("bearer-token", re.compile(
        r"(?i)\bbearer[ \t]+(?P<secret>[A-Za-z0-9\-._~+/]{8,}={0,2})")),
    ("secret-assignment", re.compile(
        r"(?i)\b" + _SECRET_NAME_TEXT + r"\"?[ \t]*[:=][ \t]*\"(?P<secret>[^\"\r\n]+)\"")),
    ("secret-assignment", re.compile(
        r"(?i)\b" + _SECRET_NAME_TEXT + r"[ \t]*[:=][ \t]*(?P<secret>[^\s,;'\"}\)\]]+)")),
)

# What the entropy sweep will even look at. Restricted to the base64 / base64url / hex / bare
# alphanumeric alphabet because that is the shape of essentially every machine-generated
# credential, and because widening it to punctuation turns prose and log lines into candidates.
_ENTROPY_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")


def _character_classes(token: str) -> int:
    """How many of lower / upper / digit / base64-symbol the token uses.

    `-` AND `_` DO NOT COUNT AS A CLASS, and that single decision is what keeps the sweep from
    eating Kubernetes. `acp-worker-remediate-7d9f8b6c5d-x2k4p` is 37 characters of high apparent
    entropy; counting `-` would make it three classes and redact every pod name in the bundle,
    which is both useless and the kind of over-redaction that gets a filter turned off.
    """
    return sum((
        any(c.islower() for c in token),
        any(c.isupper() for c in token),
        any(c.isdigit() for c in token),
        any(c in "+/=" for c in token),
    ))


def _shannon_entropy(token: str) -> float:
    if not token:
        return 0.0
    counts: dict[str, int] = {}
    for char in token:
        counts[char] = counts.get(char, 0) + 1
    n = len(token)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_like_a_credential(token: str) -> bool:
    """The conservative fallback: something we do not recognise but that is shaped like a secret.

    THREE CLASSES, TWENTY CHARACTERS, THREE BITS PER CHARACTER. Tuned against what is actually in
    a bundle rather than in the abstract: pod and node names are lower+digit, resource versions
    are digits, sha digests are lower+digit (and protected before this runs anyway), image
    references and hostnames contain `.` and `:` and so are never candidates. A generated API key
    is mixed case with digits, and that is the gap this closes.

    WHAT IT DOES NOT CATCH, said plainly: an all-lowercase-hex secret, and a secret full of
    punctuation. Both are two character classes or outside the candidate alphabet, and widening
    either rule redacts image digests and log prose respectively. Those values are covered by the
    key-name and shape rules instead — which is the honest statement of this filter's shape: the
    entropy sweep is the LAST line, not the first.
    """
    if len(token) < 20:
        return False
    if _character_classes(token) < 3:
        return False
    return _shannon_entropy(token) >= 3.0


@dataclass(frozen=True)
class Finding:
    """One span of text that must not be published."""

    start: int
    end: int
    category: str
    value: str


def find_secrets(text: str) -> list[Finding]:
    """Every span in `text` that the filter considers a credential.

    ONE IMPLEMENTATION, TWO USES: redaction replaces these spans, and `verify_bundle` reports them
    as leaks. Keeping them the same function is what makes the verification meaningful for the
    case it is actually guarding — not "did the regexes miss something" (they cannot catch what
    they do not match) but "did a collector write a value without passing it through the filter at
    all", which is the mistake a human makes when adding a collector.
    """
    claimed: list[tuple[int, int]] = [
        (m.start(), m.end())
        for rx in (_PLACEHOLDER_RE, _IMAGE_DIGEST_RE)
        for m in rx.finditer(text)
    ]

    def overlaps(start: int, end: int) -> bool:
        return any(start < c_end and c_start < end for c_start, c_end in claimed)

    found: list[Finding] = []

    def take(start: int, end: int, category: str) -> None:
        if end <= start or overlaps(start, end):
            return
        claimed.append((start, end))
        found.append(Finding(start, end, category, text[start:end]))

    for category, pattern in _SHAPES:
        for match in pattern.finditer(text):
            if "secret" in match.groupdict() and match.group("secret") is not None:
                start, end = match.span("secret")
            else:
                start, end = match.span(0)
            take(start, end, category)

    for match in _ENTROPY_CANDIDATE_RE.finditer(text):
        if _looks_like_a_credential(match.group(0)):
            take(match.start(), match.end(), "high-entropy")

    found.sort(key=lambda f: f.start)
    return found


def _normalise_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


class Redactor:
    """The per-bundle filter, and the memory that makes two identical secrets look identical.

    One instance is used for a whole bundle, so `REDACTED[database-password#4]` means the same
    value everywhere it appears — across the document, a ConfigMap and a pod's termination
    message. That is the fact worth preserving: "these two components share a password" is
    frequently the diagnosis, and it costs nothing to keep.
    """

    def __init__(self, secret_key_names: Iterable[str] = ()) -> None:
        self._assigned: dict[str, str] = {}
        self._next = 1
        # Every key name under the deployment document's `secrets.refs`. The document names the
        # keys an installation's secrets are stored under, so anything ELSEWHERE in the bundle
        # carrying one of those names is a value that should have stayed in the vault.
        self.secret_key_names = {_normalise_key(n) for n in secret_key_names if str(n).strip()}

    # ── placeholders ─────────────────────────────────────────────────────────
    def placeholder(self, value: Any, category: str) -> str:
        """The stable stand-in for one value. Same value in, same placeholder out."""
        key = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
        existing = self._assigned.get(key)
        if existing is not None:
            # Deliberately keeps the category from the FIRST sighting. A value that matched
            # `connection-string` in one file and the entropy sweep in another is one value, and
            # renaming it per file would break the "same secret, same placeholder" promise this
            # exists to keep.
            return existing
        slug = re.sub(r"[^a-z0-9.\-]+", "-", str(category).lower()).strip("-")[:60] or "value"
        made = f"REDACTED[{slug}#{self._next}]"
        self._next += 1
        self._assigned[key] = made
        return made

    # ── the two entry points ─────────────────────────────────────────────────
    def text(self, value: str) -> str:
        findings = find_secrets(value)
        if not findings:
            return value
        out: list[str] = []
        cursor = 0
        for finding in findings:
            out.append(value[cursor:finding.start])
            out.append(self.placeholder(finding.value, finding.category))
            cursor = finding.end
        out.append(value[cursor:])
        return "".join(out)

    def is_secret_key(self, name: Any) -> bool:
        """Does this FIELD NAME mean the value beside it is a credential?

        Broader than the free-text rule on purpose. Here the structure guarantees `name` is a
        field name, so `*_KEY` / `*-key` / a bare `apiKey` are strong signals; in free text a bare
        `key:` is not, and treating it as one would redact the deployment document's own secret
        references (`key: database-url`) — the references being, per PRD S9, the thing the
        document is allowed to contain.
        """
        normalised = _normalise_key(name)
        if not normalised:
            return False
        if normalised in self.secret_key_names:
            return True
        if normalised.endswith("key"):
            return True
        return any(word in normalised for word in _SECRET_WORDS)

    def tree(self, value: Any, *, path: tuple[str, ...] = (),
             key_exempt_paths: Sequence[tuple[str, ...]] = ()) -> Any:
        """Redact a decoded JSON/YAML structure, by key name and by value shape.

        `key_exempt_paths` turns OFF the key rule for one subtree while leaving the shape and
        entropy rules on. It exists for exactly one place — the document's `secrets.refs` — where
        every key is named after a credential and every value is a reference to one. Redacting by
        key there would erase the reference names, which is both the most useful part of the
        document and, by construction, not a secret. A raw value pasted into that block is still
        caught, by shape.
        """
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                child = path + (str(key),)
                # Two ways the key rule must stand down. `under_exempt` is the subtree itself.
                # `on_the_way` is its ANCESTORS, and forgetting it is a bug that hides as a
                # success: `secrets` contains the word "secret", so the key rule fires on the
                # whole block before the walk ever reaches `secrets.refs`, and the document in
                # the bundle loses its provider, its refs and every name in them — replaced by
                # one placeholder that looks like the filter working.
                under_exempt = any(child[:len(p)] == p for p in key_exempt_paths)
                on_the_way = any(p[:len(child)] == child for p in key_exempt_paths)
                new_key = self.text(key) if isinstance(key, str) else key
                by_key = not (under_exempt or on_the_way) and self.is_secret_key(key)
                if by_key and isinstance(item, list):
                    out[new_key] = [
                        self.tree(element, path=child, key_exempt_paths=key_exempt_paths)
                        if isinstance(element, (dict, list))
                        else self.placeholder(element, str(key))
                        for element in item]
                elif by_key and not isinstance(item, dict):
                    out[new_key] = self.placeholder(item, str(key))
                else:
                    # A KEY NAME IS A SIGNAL ABOUT A VALUE, AND A MAPPING IS NOT A VALUE. When a
                    # secret-sounding key holds a whole subtree it is a SECTION name, and
                    # replacing the section with one placeholder destroys the structure while
                    # hiding nothing the walk would not reach anyway — every scalar inside is
                    # still judged on its own key name, its shape and its entropy.
                    #
                    # This is not hypothetical tidiness. The shipped standard-production document
                    # declares a `secrets.refs` entry named `object-storage`, which normalises to
                    # exactly `data.objectStorage` — so the naive rule replaced that whole block
                    # (mode, encryption, retentionDays) with a placeholder, in the one file a
                    # support engineer reads first, to hide three settings that are not secret.
                    out[new_key] = self.tree(
                        item, path=child, key_exempt_paths=key_exempt_paths)
            return out
        if isinstance(value, list):
            return [self.tree(item, path=path, key_exempt_paths=key_exempt_paths)
                    for item in value]
        if isinstance(value, str):
            return self.text(value)
        # Numbers, booleans and None are returned unchanged rather than stringified. A diagnostic
        # dump that silently changes an object's types is a dump that lies about the object, and
        # no credential shape this filter recognises survives being a Python number.
        return value


def redact(value: Any, *, redactor: Redactor | None = None) -> Any:
    """Redact one value. With no `redactor`, a fresh one — so this is a pure function.

    The public single-value entry point, kept separate from bundle generation so the filter can be
    tested on a string with no cluster, no files and no manifest in the way.
    """
    active = redactor if redactor is not None else Redactor()
    if isinstance(value, str):
        return active.text(value)
    if isinstance(value, (dict, list)):
        return active.tree(value)
    return value


def redact_tree(value: Any, *, redactor: Redactor | None = None,
                key_exempt_paths: Sequence[tuple[str, ...]] = ()) -> Any:
    active = redactor if redactor is not None else Redactor()
    return active.tree(value, key_exempt_paths=key_exempt_paths)


# ══════════════════════════════════════════════════════════════════════════════
# Verification
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Leak:
    """Something in a written bundle that the filter should have caught.

    NOTE WHAT IS NOT HERE: the value. A leak report printed to a terminal, pasted into a ticket or
    captured in CI logs would otherwise republish the exact secret the bundle was deleted for
    containing. The path, the category and the line number are enough to find it in the collector
    that wrote it, which is the only thing anyone needs to do about it.
    """

    path: str
    category: str
    line: int

    def render(self) -> str:
        return f"  {self.path}:{self.line}: a {self.category} reached the bundle unredacted"


def verify_bundle(directory: str | Path) -> list[Leak]:
    """Re-scan a written bundle for anything the filter should have caught.

    THE FAILURE THIS GUARDS IS A COLLECTOR, NOT A REGEX. A pattern cannot catch what it does not
    match, so re-running the patterns proves nothing about the patterns. What it does prove is
    that every byte on disk went THROUGH them: a collector that json.dumps a raw API object,
    forgets the redactor on one field, or writes a kubectl stderr string verbatim shows up here
    immediately. That mistake is the likely one — it is a line of ordinary-looking code — and it
    is invisible in review.
    """
    root = Path(directory)
    leaks: list[Leak] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A file this scanner cannot read is a file it cannot clear. Treated as a leak rather
            # than skipped, because "we could not check it" must never resolve to "it is fine" —
            # the same rule doctor's `unknown` outcome exists for.
            leaks.append(Leak(relative, "unreadable-file", 0))
            continue
        line_starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                line_starts.append(index + 1)
        for finding in find_secrets(text):
            line = max(i for i, start in enumerate(line_starts, 1) if start <= finding.start)
            leaks.append(Leak(relative, finding.category, line))
        # Defence in depth against the one API object that is a secret by definition. A Secret's
        # `data` is base64, not text, so NO shape rule above would ever fire on it — a leak there
        # would be invisible to every other check in this function. `_reduce_secret` is supposed
        # to have kept names and keys only, and this is what says so on disk: the day somebody
        # "simplifies" that reducer into a pass-through, this fails.
        if path.name == "secrets.json" or '"kind": "Secret"' in text:
            for line_number, line_text in enumerate(text.splitlines(), 1):
                if re.search(r'"(?:data|stringData)"\s*:', line_text):
                    leaks.append(Leak(relative, "secret-data", line_number))
    return leaks


# ══════════════════════════════════════════════════════════════════════════════
# Collection
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Collection:
    """One thing the bundle tried to gather, and how that went."""

    name: str
    outcome: str
    blocking: bool = False
    path: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"collection": self.name, "outcome": self.outcome, "blocking": self.blocking,
                "path": self.path, "bytes": self.bytes, "sha256": self.sha256,
                "reason": self.reason}


class _Writer:
    """Writes files under the bundle root and records what it wrote.

    Every path in the manifest is relative to the root, and every file's sha256 is computed from
    the bytes actually written rather than from the object before serialisation — so the manifest
    describes the artifact, not the intention.
    """

    def __init__(self, root: Path, redactor: Redactor) -> None:
        self.root = root
        self.redactor = redactor
        self.collections: list[Collection] = []

    def write(self, name: str, relative: str, text: str, *, blocking: bool = False) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = text.encode("utf-8")
        target.write_bytes(payload)
        self.collections.append(Collection(
            name=name, outcome=SUCCEEDED, blocking=blocking, path=relative,
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))

    def write_json(self, name: str, relative: str, payload: Any, *,
                   blocking: bool = False) -> None:
        self.write(name, relative, json.dumps(payload, indent=2, sort_keys=False) + "\n",
                   blocking=blocking)

    def failed(self, name: str, reason: str, *, blocking: bool = False) -> None:
        # The reason comes from kubectl's stderr, which is text from a cluster and therefore text
        # that can contain a URL with credentials in it. It goes through the filter like
        # everything else.
        self.collections.append(Collection(name=name, outcome=FAILED, blocking=blocking,
                                           reason=self.redactor.text(reason)))

    def skipped(self, name: str, reason: str, *, blocking: bool = False) -> None:
        self.collections.append(Collection(name=name, outcome=SKIPPED, blocking=blocking,
                                           reason=self.redactor.text(reason)))


def _kubectl_json(args: list[str], *, context: str | None) -> tuple[Any | None, str]:
    """A read whose failure is returned rather than raised, like cluster._json.

    One unreadable resource must not abort the bundle: an operator with permission to read pods
    and not Events should still get everything else, and be told which read did not happen.
    """
    try:
        proc = cluster_mod.run(args, context=context)
    except cluster_mod.ClusterUnavailable as exc:
        return None, str(exc)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, (message[0] if message else f"kubectl exit {proc.returncode}")
    try:
        return json.loads(proc.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"unparseable JSON from kubectl: {exc}"


def _meta(obj: dict) -> dict:
    return obj.get("metadata") or {}


def _labels(obj: dict) -> dict:
    return _meta(obj).get("labels") or {}


def _containers(pod_spec: dict) -> list[dict]:
    return (pod_spec.get("containers") or []) + (pod_spec.get("initContainers") or [])


def _env_summary(container: dict) -> list[str]:
    """Environment as NAMES and SOURCES, never as a name/value pair we pass through untouched.

    A literal env value in a pod spec is the classic place a credential ends up — someone sets
    `DATABASE_URL=postgres://…` "just for a minute" and it is still there a year later. So a
    literal is redacted through the ordinary filter with its own name as the key, which means
    `LOG_LEVEL=debug` survives and `API_TOKEN=…` does not; a `valueFrom` is rendered as the
    REFERENCE it is, because "this container reads db-password out of Secret acp-secrets" is
    exactly what a support engineer needs and contains nothing secret.
    """
    out: list[str] = []
    for entry in container.get("env") or []:
        name = entry.get("name", "?")
        source = entry.get("valueFrom") or {}
        if "secretKeyRef" in source:
            ref = source["secretKeyRef"] or {}
            out.append(f"{name} <- secretKeyRef {ref.get('name', '?')}/{ref.get('key', '?')}")
        elif "configMapKeyRef" in source:
            ref = source["configMapKeyRef"] or {}
            out.append(f"{name} <- configMapKeyRef {ref.get('name', '?')}/{ref.get('key', '?')}")
        elif "fieldRef" in source:
            out.append(f"{name} <- fieldRef {(source['fieldRef'] or {}).get('fieldPath', '?')}")
        elif "value" in entry:
            out.append(f"{name} = {entry['value']}")
        else:
            out.append(name)
    return out


def _reduce_deployment(item: dict) -> dict:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    template_spec = ((spec.get("template") or {}).get("spec") or {})
    return {
        "name": _meta(item).get("name"),
        "labels": _labels(item),
        "annotations": _meta(item).get("annotations") or {},
        # ABSENT, not zero, when an autoscaler owns the count — the chart omits spec.replicas for
        # an autoscaled tier, and the distinction is what tells a reader whether a replica count
        # was chosen or arrived at.
        "specReplicas": spec.get("replicas"),
        "readyReplicas": status.get("readyReplicas"),
        "availableReplicas": status.get("availableReplicas"),
        "updatedReplicas": status.get("updatedReplicas"),
        "conditions": [{"type": c.get("type"), "status": c.get("status"),
                        "reason": c.get("reason"), "message": c.get("message")}
                       for c in (status.get("conditions") or [])],
        "containers": [{
            "name": c.get("name"),
            "image": c.get("image"),
            "resources": c.get("resources") or {},
            "env": _env_summary(c),
        } for c in _containers(template_spec)],
        "serviceAccountName": template_spec.get("serviceAccountName"),
    }


def _reduce_pod(item: dict) -> dict:
    """A pod, reduced to what a reader needs — and the image is the point.

    `image` is what the spec ASKED for and `imageID` is what the kubelet actually pulled, and they
    disagree exactly when the interesting bugs happen: a floating tag that resolved to something
    older on one node, a registry mirror serving a stale digest, a rollout half-applied. A bundle
    that carries only one of them cannot tell that story.
    """
    status = item.get("status") or {}
    spec = item.get("spec") or {}
    statuses = (status.get("containerStatuses") or []) + \
        (status.get("initContainerStatuses") or [])
    return {
        "name": _meta(item).get("name"),
        "labels": _labels(item),
        "phase": status.get("phase"),
        "node": spec.get("nodeName"),
        "startTime": status.get("startTime"),
        "specImages": [c.get("image") for c in _containers(spec)],
        "containers": [{
            "name": c.get("name"),
            "image": c.get("image"),
            "imageID": c.get("imageID"),
            "ready": c.get("ready"),
            "restarts": c.get("restartCount"),
            "state": c.get("state") or {},
            "lastState": c.get("lastState") or {},
        } for c in statuses],
        "conditions": [{"type": c.get("type"), "status": c.get("status"),
                        "reason": c.get("reason"), "message": c.get("message")}
                       for c in (status.get("conditions") or [])],
    }


def _reduce_service(item: dict) -> dict:
    spec = item.get("spec") or {}
    return {"name": _meta(item).get("name"), "type": spec.get("type"),
            "clusterIP": spec.get("clusterIP"), "selector": spec.get("selector") or {},
            "ports": spec.get("ports") or []}


def _reduce_ingress(item: dict) -> dict:
    spec = item.get("spec") or {}
    return {
        "name": _meta(item).get("name"),
        "ingressClassName": spec.get("ingressClassName"),
        "hosts": [rule.get("host") for rule in (spec.get("rules") or [])],
        "tlsSecretNames": [tls.get("secretName") for tls in (spec.get("tls") or [])],
        "loadBalancer": ((item.get("status") or {}).get("loadBalancer") or {}),
    }


def _reduce_pdb(item: dict) -> dict:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    return {"name": _meta(item).get("name"), "minAvailable": spec.get("minAvailable"),
            "maxUnavailable": spec.get("maxUnavailable"),
            "currentHealthy": status.get("currentHealthy"),
            "desiredHealthy": status.get("desiredHealthy"),
            "disruptionsAllowed": status.get("disruptionsAllowed")}


def _reduce_job(item: dict) -> dict:
    status = item.get("status") or {}
    template_spec = (((item.get("spec") or {}).get("template") or {}).get("spec") or {})
    return {"name": _meta(item).get("name"), "labels": _labels(item),
            "succeeded": status.get("succeeded"), "failed": status.get("failed"),
            "active": status.get("active"), "startTime": status.get("startTime"),
            "completionTime": status.get("completionTime"),
            "images": [c.get("image") for c in _containers(template_spec)]}


def _reduce_scaledobject(item: dict) -> dict:
    spec = item.get("spec") or {}
    return {"name": _meta(item).get("name"),
            "scaleTargetRef": spec.get("scaleTargetRef") or {},
            "minReplicaCount": spec.get("minReplicaCount"),
            "maxReplicaCount": spec.get("maxReplicaCount"),
            # Trigger metadata routinely holds a queue connection string; it is redacted with
            # everything else on the way out.
            "triggers": spec.get("triggers") or [],
            "conditions": ((item.get("status") or {}).get("conditions") or [])}


def _reduce_externalsecret(item: dict) -> dict:
    spec = item.get("spec") or {}
    return {"name": _meta(item).get("name"),
            "secretStoreRef": spec.get("secretStoreRef") or {},
            "target": (spec.get("target") or {}).get("name"),
            "dataKeys": [d.get("secretKey") for d in (spec.get("data") or [])],
            "conditions": ((item.get("status") or {}).get("conditions") or [])}


def _reduce_networkpolicy(item: dict) -> dict:
    spec = item.get("spec") or {}
    return {"name": _meta(item).get("name"), "podSelector": spec.get("podSelector") or {},
            "policyTypes": spec.get("policyTypes") or [],
            "ingressRuleCount": len(spec.get("ingress") or []),
            "egressRuleCount": len(spec.get("egress") or [])}


def _reduce_secret(item: dict) -> dict:
    """NAMES AND KEYS ONLY. This function is the boundary, and it is written as a whitelist.

    Note what is not here: no `data`, no `stringData`, and no pass-through of the object. The
    reducer constructs a NEW dict from three fields rather than copying and deleting, because
    copy-and-delete is one forgotten key away from publishing a vault. Even the key names are
    worth having — "the Secret exists but has no `database-url` key" explains a pod stuck in
    CreateContainerConfigError, and it explains it without anybody sending a password.
    """
    return {
        "name": _meta(item).get("name"),
        "type": item.get("type"),
        "keys": sorted((item.get("data") or {}).keys()),
        "annotations": sorted((_meta(item).get("annotations") or {}).keys()),
    }


def _reduce_configmap(item: dict) -> dict:
    return {"name": _meta(item).get("name"), "labels": _labels(item),
            "data": item.get("data") or {}}


def _reduce_event(item: dict) -> dict:
    involved = item.get("involvedObject") or item.get("regarding") or {}
    return {
        "time": (item.get("lastTimestamp") or item.get("eventTime")
                 or _meta(item).get("creationTimestamp") or ""),
        "type": item.get("type"),
        "reason": item.get("reason"),
        "object": f"{involved.get('kind', '?')}/{involved.get('name', '?')}",
        "count": item.get("count"),
        "message": item.get("message") or "",
    }


# name, kubectl resource, reducer, blocking, and the API resource that must exist for the read to
# make sense at all. Declaring the gate here rather than inside each collector is what makes a
# SKIPPED outcome a stated fact — "KEDA is not served by this cluster" — instead of a failed read
# with a confusing "the server doesn't have a resource type" that every operator reads as RBAC.
_NAMESPACED: tuple[tuple[str, str, Callable[[dict], dict], bool, str | None], ...] = (
    ("deployments", "deployments", _reduce_deployment, True, None),
    ("pods", "pods", _reduce_pod, True, None),
    ("services", "services", _reduce_service, False, None),
    ("ingresses", "ingresses", _reduce_ingress, False, None),
    ("jobs", "jobs", _reduce_job, False, None),
    ("poddisruptionbudgets", "poddisruptionbudgets", _reduce_pdb, False, None),
    ("networkpolicies", "networkpolicies", _reduce_networkpolicy, False, None),
    ("scaledobjects", "scaledobjects", _reduce_scaledobject, False, "scaledobjects.keda.sh"),
    ("externalsecrets", "externalsecrets", _reduce_externalsecret, False,
     "externalsecrets.external-secrets.io"),
    ("secrets", "secrets", _reduce_secret, False, None),
    ("configmaps", "configmaps", _reduce_configmap, False, None),
)


def _capabilities(facts: cluster_mod.ClusterFacts) -> dict[str, Any]:
    """The cluster's own description of itself, as the install cares about it.

    Taken from `cluster.gather()` rather than re-read: doctor and status already reason about
    these exact facts, and a bundle that gathered them a second way could disagree with the
    `doctor` output in the same ticket.
    """
    daemonsets = facts.kube_system_daemonsets
    enforcing = [ENFORCING_CNI_DAEMONSETS[d] for d in (daemonsets or [])
                 if d in ENFORCING_CNI_DAEMONSETS]
    non_enforcing = [NON_ENFORCING_CNI_DAEMONSETS[d] for d in (daemonsets or [])
                     if d in NON_ENFORCING_CNI_DAEMONSETS]
    if daemonsets is None:
        enforcement: bool | None = None
        basis = "the kube-system DaemonSets could not be listed"
    elif enforcing:
        enforcement = True
        basis = f"inferred from {', '.join(sorted(enforcing))}"
    elif non_enforcing:
        enforcement = False
        basis = (f"{', '.join(sorted(non_enforcing))} does not implement NetworkPolicy; the "
                 "chart's policies would apply cleanly and enforce nothing")
    else:
        enforcement = None
        basis = ("no CNI this tool recognises is running in kube-system; NetworkPolicy "
                 "enforcement cannot be inferred and no API reports it")
    return {
        "kubernetes": facts.version_text,
        "serverVersion": list(facts.server_version) if facts.server_version else None,
        "namespaceExists": facts.namespace_exists,
        "apiResourceCount": len(facts.api_resources) if facts.api_resources is not None else None,
        "keda": _has_api(facts, "keda.sh", "scaledobjects.keda.sh"),
        "externalSecrets": _has_api(facts, "external-secrets.io"),
        "networkPolicyApi": _has_api(facts, "networkpolicies"),
        "metricsApi": _has_api(facts, "metrics.k8s.io"),
        "podDisruptionBudgetApi": _has_api(facts, "poddisruptionbudgets"),
        "cniDaemonSets": sorted(daemonsets) if daemonsets is not None else None,
        "networkPolicyEnforcement": {"enforces": enforcement, "basis": basis},
        "ingressClasses": facts.ingress_classes,
        "storageClasses": facts.storage_classes,
        "secretStores": facts.secret_stores,
    }


def generate(*, out_dir: str | Path, namespace: str, document: Any = None,
             document_error: str = "", document_path: str = "", context: str | None = None,
             archive: bool = False) -> dict[str, Any]:
    """Collect a bundle into `out_dir`. Returns the report `cmd_support_bundle` prints.

    THE OUTPUT DIRECTORY MUST BE EMPTY OR ABSENT, and that is a safety rule rather than tidiness.
    A bundle that fails verification is DELETED, so this function must never be in a position to
    delete a directory it did not create — pointing `--out` at a home directory and having the
    filter fire would otherwise be catastrophic. Refusing a non-empty path makes "we created every
    file under here" true, and the deletion safe.
    """
    root = Path(out_dir)
    if root.exists() and any(root.iterdir()):
        raise SupportBundleError(
            f"{root} already exists and is not empty — refusing to write a bundle into it. A "
            "support bundle is deleted wholesale if it fails its own redaction scan, so it only "
            "ever writes into a directory it created. Choose an empty path.")

    # Reachability first, and NOTHING is written if the cluster is not there. An empty bundle for
    # an unreachable cluster is an artifact that looks like evidence and contains none.
    facts = cluster_mod.gather(namespace=namespace, context=context)
    if not facts.reachable:
        return {"reachable": False, "root": str(root), "unreachableReason": facts.unreachable_reason,
                "collections": [], "leaks": [], "ok": False, "archive": None}

    secrets_block = ((document or {}).get("secrets") or {}) if isinstance(document, dict) else {}
    refs = secrets_block.get("refs") or {}
    ref_names: list[str] = []
    if isinstance(refs, dict):
        for ref_name, ref in refs.items():
            ref_names.append(str(ref_name))
            if isinstance(ref, dict) and ref.get("key"):
                ref_names.append(str(ref["key"]))
    redactor = Redactor(secret_key_names=ref_names)

    root.mkdir(parents=True, exist_ok=True)
    writer = _Writer(root, redactor)

    _collect_document(writer, document, document_error, document_path, redactor)
    _collect_cluster(writer, facts, redactor)
    _collect_namespace(writer, facts, namespace=namespace, context=context, redactor=redactor)

    manifest = {
        "bundleVersion": 1,
        "tool": "acpctl support-bundle",
        "namespace": namespace,
        "context": context or "",
        # THE ONE NON-DETERMINISTIC FIELD IN THE BUNDLE, and it is here because a bundle whose
        # collection time is unknown cannot be lined up against an incident. Everything else —
        # every collected file, every hash — is a pure function of the cluster state and the
        # document, so "generate it twice and diff" ignores this line and compares the rest.
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "redaction": {
            "scheme": "stable per-bundle counter",
            "placeholders": redactor._next - 1,
            "note": ("Each distinct redacted value has one placeholder for the whole bundle, so "
                     "two components sharing a credential are visible as the same placeholder. "
                     "The mapping is not recorded anywhere and cannot be reversed."),
        },
        "collections": [c.as_dict() for c in writer.collections],
        "summary": {
            outcome: sum(1 for c in writer.collections if c.outcome == outcome)
            for outcome in (SUCCEEDED, FAILED, SKIPPED)
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    # The manifest is written BEFORE verification so that it is scanned too — its `reason` fields
    # carry kubectl's stderr, which is the least-examined text in the whole bundle and comes
    # straight off a cluster.
    leaks = verify_bundle(root)
    if leaks:
        shutil.rmtree(root, ignore_errors=True)
        return {"reachable": True, "root": str(root), "collections": manifest["collections"],
                "leaks": [{"path": leak.path, "category": leak.category, "line": leak.line}
                          for leak in leaks],
                "ok": False, "deleted": True, "archive": None}

    archive_path = _archive(root) if archive else None
    blocking_failures = [c.name for c in writer.collections
                         if c.blocking and c.outcome != SUCCEEDED]
    return {
        "reachable": True,
        "root": str(root),
        "collections": manifest["collections"],
        "summary": manifest["summary"],
        "blockingFailures": blocking_failures,
        "leaks": [],
        "ok": not blocking_failures,
        "archive": str(archive_path) if archive_path else None,
    }


def _collect_document(writer: _Writer, document: Any, document_error: str,
                      document_path: str, redactor: Redactor) -> None:
    if document is None:
        writer.failed("document", document_error or "the deployment document could not be read",
                      blocking=True)
        return
    import yaml  # imported here so a JSON-only install still runs the rest of the bundle

    redacted = redactor.tree(document, key_exempt_paths=(("secrets", "refs"),))
    writer.write("document", "document.yaml",
                 yaml.safe_dump(redacted, sort_keys=False, default_flow_style=False),
                 blocking=True)

    # The document's own validation result, in the bundle rather than in a refusal. `doctor` and
    # `status` refuse to run on an invalid document because their output would be a list of
    # confident falsehoods; a support bundle is the opposite case — the document being invalid is
    # frequently THE finding, and refusing to collect at the moment an operator most needs help
    # would be the wrong trade.
    from . import spec as spec_mod
    try:
        result = spec_mod.validate(document)
    except Exception as exc:  # noqa: BLE001 - a validator crash must not cost the whole bundle
        writer.failed("document-validation", f"{type(exc).__name__}: {exc}")
        return
    writer.write_json("document-validation", "document-validation.json", redactor.tree({
        "spec": document_path,
        "valid": result.ok,
        "errors": [{"rule": f.rule, "path": f.path, "message": f.message} for f in result.errors],
        "warnings": [{"rule": f.rule, "path": f.path, "message": f.message}
                     for f in result.warnings],
    }))


def _collect_cluster(writer: _Writer, facts: cluster_mod.ClusterFacts,
                     redactor: Redactor) -> None:
    writer.write_json("cluster-version", "cluster/version.json", redactor.tree({
        "gitVersion": facts.version_text,
        "serverVersion": list(facts.server_version) if facts.server_version else None,
    }), blocking=True)

    if facts.api_resources is None:
        writer.failed("api-resources",
                      facts.read_failures.get("api-resources", "the API resource list "
                                              "could not be read"))
    else:
        writer.write("api-resources", "cluster/api-resources.txt",
                     "\n".join(sorted(facts.api_resources)) + "\n")

    writer.write_json("cluster-capabilities", "cluster/capabilities.json",
                      redactor.tree(_capabilities(facts)))

    # Every cluster-wide read that did not happen, restated as its own SKIPPED entry. They are
    # already inside capabilities.json as nulls, and a null is not a reason.
    for label, reason in sorted(facts.read_failures.items()):
        if label == "api-resources":
            continue                       # already recorded above, with its own path
        writer.skipped(f"cluster-{label}", reason)


def _collect_namespace(writer: _Writer, facts: cluster_mod.ClusterFacts, *, namespace: str,
                       context: str | None, redactor: Redactor) -> None:
    """Everything in the release namespace.

    COLLECTED NAMESPACE-WIDE, not by `app.kubernetes.io/part-of=acp`. `status` selects on that
    label because it is asking about the ACP release; a support bundle is asking why the release
    is unhappy, and the answer is regularly something adjacent that the selector hides — another
    release's Ingress claiming the same host, a leftover Secret with the wrong keys, a
    ResourceQuota. The label is still in the output on every object that carries one, so nothing
    is lost by not filtering on it.
    """
    base = f"namespace/{namespace}"
    for name, resource, reduce, blocking, needs_api in _NAMESPACED:
        if needs_api is not None and _has_api(facts, needs_api) is not True:
            if facts.api_resources is None:
                writer.skipped(name, "the cluster's API resource list could not be read, so "
                                     f"whether {needs_api} is served is unknown", blocking=blocking)
            else:
                writer.skipped(name, f"{needs_api} is not served by this cluster, so there are no "
                                     "objects of this kind to collect", blocking=blocking)
            continue
        payload, error = _kubectl_json(
            ["get", resource, "-n", namespace, "-o", "json"], context=context)
        if payload is None:
            writer.failed(name, error, blocking=blocking)
            continue
        items = [reduce(item) for item in (payload.get("items") or [])]
        writer.write_json(name, f"{base}/{name}.json", redactor.tree(items), blocking=blocking)

    payload, error = _kubectl_json(["get", "events", "-n", namespace, "-o", "json"],
                                   context=context)
    if payload is None:
        writer.failed("events", error)
    else:
        events = sorted((_reduce_event(item) for item in (payload.get("items") or [])),
                        key=lambda e: (str(e.get("time") or ""), str(e.get("object") or "")))
        trimmed = events[-MAX_EVENTS:]
        writer.write_json("events", f"{base}/events.json", redactor.tree({
            "total": len(events),
            "kept": len(trimmed),
            "note": (f"the {MAX_EVENTS} most recent events; the namespace held {len(events)}"
                     if len(events) > len(trimmed) else "every event in the namespace"),
            "events": trimmed,
        }))

    payload, error = _kubectl_json(
        ["get", "configmap", INSTALL_STATE_CONFIGMAP, "-n", namespace, "-o", "json"],
        context=context)
    if payload is None:
        writer.skipped("install-state",
                       f"no {INSTALL_STATE_CONFIGMAP} ConfigMap in {namespace!r} ({error}). It is "
                       "written by `acpctl install`; a release installed with helm directly, or "
                       "by an older acpctl, does not have one.")
    else:
        writer.write_json("install-state", f"{base}/install-state.json", redactor.tree({
            "name": _meta(payload).get("name"),
            "labels": _labels(payload),
            "annotations": _meta(payload).get("annotations") or {},
            "data": payload.get("data") or {},
        }))


def _archive(root: Path) -> Path:
    """tar.gz the bundle, normalised so two bundles of the same state hash the same.

    Every TarInfo's mtime, uid, gid and user/group names are zeroed, and gzip's own mtime with
    them. Partly so the archive inherits the determinism the directory has; partly because a
    support bundle travels to a vendor, and the operator's uid and username are not information
    anybody asked to send.

    The directory is left in place: an operator should be able to read what they are about to
    attach to a ticket, and deleting it to leave only a tarball takes that away.
    """
    target = root.with_suffix(root.suffix + ".tar.gz")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    with open(target, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:  # type: ignore[arg-type]
                for path in files:
                    info = tar.gettarinfo(str(path), arcname=str(
                        Path(root.name) / path.relative_to(root)))
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with open(path, "rb") as handle:
                        tar.addfile(info, handle)
    return target


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def add_parser(subparsers) -> Any:
    """Register `support-bundle`. Defined here rather than in cli.py so the command's arguments
    live beside the code that reads them."""
    parser = subparsers.add_parser(
        "support-bundle",
        help="collect a redacted diagnostic bundle (reads only, changes nothing)")
    parser.add_argument("spec")
    parser.add_argument("--out", "-o", required=True,
                        help="directory to write the bundle into; must be empty or absent")
    parser.add_argument("--namespace", "-n", default=None,
                        help="namespace to read (default: the document's metadata.name)")
    parser.add_argument("--context", default=None, help="kubeconfig context to use")
    parser.add_argument("--archive", action="store_true",
                        help="also write <out>.tar.gz, leaving the directory in place")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=cmd_support_bundle)
    return parser


def cmd_support_bundle(args) -> int:
    """Collect a redacted support bundle.

    EXIT CODES, chosen for what a pipeline and a human should each do:

        0  the bundle was written and it passed its own redaction scan
        1  it was written but a BLOCKING collection failed — the bundle exists and is worth
           sending, and something a support engineer will ask for is missing from it — or the
           scan found a leak, in which case the bundle has been DELETED and there is nothing on
           disk to send. Both are "look at this before sending", which is why they share a code.
        2  the cluster could not be reached, so nothing was collected. Retryable, and deliberately
           not 1: there is no partial artifact and no leak, only an absent cluster.

    IT DOES NOT REFUSE AN INVALID DOCUMENT, unlike `plan`, `doctor` and `status`. Those refuse
    because their output would be derived from a bad document and would be confidently wrong. A
    support bundle derives nothing — it collects — and the moment an operator most needs to send
    one is the moment their document does not validate. The validation result goes IN the bundle.
    """
    from . import spec as spec_mod

    document: Any = None
    document_error = ""
    try:
        document = spec_mod.load_document(args.spec)
    except Exception as exc:  # noqa: BLE001 - a YAML error, a missing file, a permissions error
        # Recorded as a failed collection instead of aborting: the cluster half of the bundle is
        # still worth having, and "the document could not be parsed" is itself a finding.
        document_error = f"{type(exc).__name__}: {exc}"
        print(f"acpctl support-bundle: could not read {args.spec}: {exc}\n"
              "Collecting the cluster half of the bundle anyway.", file=sys.stderr)

    namespace = args.namespace or (document or {}).get("metadata", {}).get("name") or "acp"

    try:
        report = generate(out_dir=args.out, namespace=namespace, document=document,
                          document_error=document_error, document_path=args.spec,
                          context=args.context, archive=args.archive)
    except SupportBundleError as exc:
        print(f"acpctl support-bundle: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_bundle(report, spec=args.spec, namespace=namespace)

    if not report["reachable"]:
        return 2
    return 0 if report["ok"] else 1


def _print_bundle(report: dict, *, spec: str, namespace: str) -> None:
    print(f"acpctl support-bundle — {spec}")
    print(f"namespace: {namespace}")
    print()
    if not report["reachable"]:
        print("NOTHING WAS COLLECTED — the cluster could not be reached:")
        print(f"  {report['unreachableReason']}")
        return
    for collection in report["collections"]:
        mark = {SUCCEEDED: "OK  ", FAILED: "FAIL", SKIPPED: "SKIP"}[collection["outcome"]]
        line = f"  [{mark}] {collection['collection']}"
        if collection["path"]:
            line += f" -> {collection['path']} ({collection['bytes']} bytes)"
        print(line)
        if collection["reason"]:
            print(f"         -> {collection['reason']}")
    print()
    if report["leaks"]:
        print(f"REDACTION FAILED — {len(report['leaks'])} value(s) reached the bundle that the "
              "filter should have caught:")
        for leak in report["leaks"]:
            print(f"  {leak['path']}:{leak['line']}: {leak['category']}")
        print(f"\nThe bundle at {report['root']} has been DELETED. Nothing was left on disk, "
              "because an artifact that looks redacted and is not will be sent to someone. This "
              "is a bug in acpctl's collectors — please report the categories above; they name "
              "the shape, never the value.")
        return
    written = report["summary"][SUCCEEDED]
    print(f"{written} collection(s) written to {report['root']}, "
          f"{report['summary'][FAILED]} failed, {report['summary'][SKIPPED]} skipped")
    if report.get("archive"):
        print(f"archive: {report['archive']}")
    if report["blockingFailures"]:
        print("\nSomething a support engineer will ask for is MISSING: "
              f"{', '.join(report['blockingFailures'])}. The bundle is still worth sending; "
              "manifest.json records why each is absent.")
    else:
        print("\nEvery value was redacted, and the written bundle was re-scanned to confirm it. "
              "Read manifest.json before sending — it lists every file and what could not be "
              "collected.")
