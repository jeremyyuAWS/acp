"""`acpctl support-bundle` — the redaction, which is the deliverable, and the bundle around it.

WHY THE REDACTION TESTS ARE THE POINT. A support bundle is an artifact that TRAVELS: into a
ticket, an email thread, a vendor's issue tracker, a shared drive. PRD S13 and acceptance
criterion S20.6 both say the same thing — secrets never appear in one — and a leak here cannot be
recalled from the places the bundle has already reached. So the assertions that matter here are
not "the parsed structure looks right" but `test_no_planted_secret_appears_in_the_written_bytes`,
which reads every byte of the written bundle and looks for the literal values. A test that checks
the parsed JSON checks the fields somebody remembered to check; the bytes are what gets sent.

The second load-bearing test is `test_a_leak_that_gets_past_the_filter_deletes_the_bundle`. The
regexes cannot catch what they do not match, so re-running them proves nothing about them — what
`verify_bundle` actually guards is a COLLECTOR that writes a value without passing it through the
filter at all, which is one line of ordinary-looking code and invisible in review. That test
neuters the filter to produce exactly that mistake, and asserts the bundle is deleted rather than
reported as written.

NO CLUSTER, NO KUBECTL, NO NETWORK. Everything here runs against `tests/packaging_kubectl_fake.py`
— the same fake `doctor` and `status` use — with a thin wrapper that serves the resource kinds
those two commands never asked for and delegates everything else to it, so the fake's refusal of
non-read verbs still applies.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest

import packaging_kubectl_fake as fake
from packaging_helpers import PACKAGING, load_example

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = PACKAGING / "examples" / "standard-production.acp-deployment.yaml"
NAMESPACE = "acp-production"


# ══════════════════════════════════════════════════════════════════════════════
# The harness
# ══════════════════════════════════════════════════════════════════════════════

# A kubectl that answers from `fixture["objects"]` for the resource kinds the shared fake does not
# model — Services, Ingresses, Events, Secrets, ConfigMaps — and DELEGATES everything else to it.
# Written as a wrapper rather than as a second fake so that `version`, `api-resources`, the
# healthy-cluster shapes and, most importantly, the refusal of every non-read verb all keep
# coming from the one place the other packaging tests share.
_WRAPPER = '''#!/usr/bin/env python3
"""Fake kubectl for the support bundle: extra resources from the fixture, the rest delegated."""
import json, os, subprocess, sys

args = sys.argv[1:]
log = os.environ.get("ACP_FAKE_KUBECTL_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\\n")

fixture = json.load(open(os.environ["ACP_FAKE_KUBECTL_FIXTURE"]))
objects = fixture.get("objects") or {}

trimmed = list(args)
while trimmed and trimmed[0] == "--context":
    trimmed = trimmed[2:]

if trimmed and trimmed[0] == "get":
    what = trimmed[1] if len(trimmed) > 1 else ""
    named = None
    if len(trimmed) > 2 and not trimmed[2].startswith("-"):
        named = what + "/" + trimmed[2]
    for key in (named, what):
        if key is not None and key in objects:
            payload = objects[key]
            # A STRING means "fail with this on stderr" — that is how the tests produce a read
            # that is refused rather than empty, which are different manifest outcomes.
            if isinstance(payload, str):
                print(payload, file=sys.stderr)
                sys.exit(1)
            print(json.dumps(payload))
            sys.exit(0)

env = dict(os.environ)
env.pop("ACP_FAKE_KUBECTL_LOG", None)   # the delegate logs too; one line per invocation
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kubectl-base")
sys.exit(subprocess.run([base] + args, env=env).returncode)
'''


def install_fake(tmp_path: Path, fixture: dict) -> dict[str, str]:
    env = fake.install(tmp_path, fixture)
    bindir = tmp_path / "bin"
    (bindir / "kubectl").rename(bindir / "kubectl-base")
    wrapper = bindir / "kubectl"
    wrapper.write_text(_WRAPPER, encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return env


@contextmanager
def using(env: dict[str, str]):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ── the secrets the fixture plants, and where each one ends up ────────────────
#
# Every value here is fake. They are kept in one dict so `test_no_planted_secret_appears_in_the_
# written_bytes` can sweep the whole bundle for all of them at once — adding a secret to the
# fixture without adding it here would be the way to make that test pass vacuously, so the fixture
# builder below uses these constants and nothing else.
POSTGRES_URL = "postgres://acp:Tr0ub4dor-3-Xample@acp-db.internal:5432/acp"
REDIS_URL = "redis://:R3dis-P4ssw0rd-Xample@acp-redis.internal:6379/0"
AMQP_URL = "amqp://acpuser:Rabb1t-P4ss@rabbit.internal:5672/%2facp"
MONGO_URL = "mongodb+srv://acp:M0ngo-P4ss@cluster0.example.net/acp"
PLAIN_PASSWORD = "n0t-a-real-passw0rd"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
       ".eyJzdWIiOiJhY3AiLCJpYXQiOjE3MDAwMDAwMDB9"
       ".Qk1sT2xhTm90QVJlYWxTaWduYXR1cmVYWVo")
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
# 88 characters of base64 ending `==` — the Azure storage account key shape.
AZURE_STORAGE_KEY = ("YWNwLXN1cHBvcnQtYnVuZGxlLWZpeHR1cmUtbm90LWEtcmVhbC1rZXktMDEyMzQ1Njc4"
                     "OWFiY2RlZi14eXp3IQ==")
AZURE_SAS = "sv=2021-06-08&ss=b&srt=sco&sp=rl&sig=Xk3Not3AReal3Signature3Value3Xyz%3D"
PEM_KEY = ("-----BEGIN RSA PRIVATE KEY-----\n"
           "MIIEowIBAAKCAQEAnotarealkeyatallbutitlookslikeoneenough\n"
           "-----END RSA PRIVATE KEY-----")
GCP_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BA\\n-----END PRIVATE KEY-----\\n"
BEARER_TOKEN = "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv"
BASIC_CREDENTIAL = "YWNwOm5vdC1hLXJlYWwtcGFzc3dvcmQ="
# Recognised by nothing in particular: mixed case, digits, thirty-two characters. The value the
# entropy sweep is the last line of defence for.
UNRECOGNISED_HIGH_ENTROPY = "Zk8Qw1Rt7Yu2Io4Pa6Sd9Fg3Hj5Kl0Xc"
# What a Secret's `data` actually looks like on the wire. Never decoded, never published.
SECRET_DATA_BASE64 = "cG9zdGdyZXM6Ly9hY3A6VHIwdWI0ZG9yLTMtWGFtcGxlQGRi"

PLANTED = {
    "postgres-url": POSTGRES_URL,
    "redis-url": REDIS_URL,
    "amqp-url": AMQP_URL,
    "mongodb-url": MONGO_URL,
    "password": PLAIN_PASSWORD,
    "jwt": JWT,
    "aws-access-key-id": AWS_ACCESS_KEY_ID,
    "aws-secret-access-key": AWS_SECRET_ACCESS_KEY,
    "azure-storage-key": AZURE_STORAGE_KEY,
    "azure-sas": AZURE_SAS,
    "pem": PEM_KEY,
    "gcp-private-key": GCP_PRIVATE_KEY,
    "bearer": BEARER_TOKEN,
    "basic": BASIC_CREDENTIAL,
    "high-entropy": UNRECOGNISED_HIGH_ENTROPY,
    "secret-data": SECRET_DATA_BASE64,
}

# Facts that must SURVIVE. A filter that redacts these is useless in a different direction: the
# image is how a reader learns what actually ran, and the pod name is how they find it again.
IMAGE = "reg.example.org/acp:2026.9"
IMAGE_ID = "docker-pullable://reg.example.org/acp@sha256:" + "3f" * 32
POD_NAME = "acp-worker-remediate-7d9f8b6c5d-x2k4p"


def _list(*items):
    return {"items": list(items)}


def bundle_objects() -> dict:
    """The namespace the fake serves, with a planted secret in every kind of hiding place."""
    return {
        "pods": _list({
            "metadata": {"name": POD_NAME, "labels": {"app.kubernetes.io/part-of": "acp"}},
            "spec": {"nodeName": "aks-workers-41231234-vmss000002",
                     "containers": [{"name": "worker", "image": IMAGE}]},
            "status": {
                "phase": "Running",
                "startTime": "2026-09-08T09:00:00Z",
                "containerStatuses": [{
                    "name": "worker", "image": IMAGE, "imageID": IMAGE_ID,
                    "ready": False, "restartCount": 7,
                    "state": {"waiting": {
                        "reason": "CrashLoopBackOff",
                        # A log line, with a connection string inside it.
                        "message": f"back-off restarting; last error: could not connect to "
                                   f"{POSTGRES_URL}"}},
                    "lastState": {"terminated": {
                        "reason": "Error", "exitCode": 1,
                        # A PEM block inside a termination message.
                        "message": f"boto3 refused the credentials\n{PEM_KEY}\n"}},
                }],
                "conditions": [{"type": "Ready", "status": "False", "reason": "ContainersNotReady",
                                "message": "containers with unready status: [worker]"}],
            },
        }),
        "deployments": _list({
            "metadata": {"name": "acp-worker-remediate",
                         "labels": {"app.kubernetes.io/part-of": "acp",
                                    "app.kubernetes.io/component": "worker",
                                    "app.kubernetes.io/version": "2026.9"},
                         "annotations": {"checksum/config": "9c" * 32}},
            "spec": {"replicas": None, "template": {"spec": {
                "serviceAccountName": "acp",
                "containers": [{
                    "name": "worker", "image": IMAGE,
                    "resources": {"requests": {"cpu": "2", "memory": "4Gi"}},
                    "env": [
                        {"name": "LOG_LEVEL", "value": "debug"},
                        # The classic: a literal where a reference belongs.
                        {"name": "SERVICE_JWT", "value": JWT},
                        {"name": "AWS_ACCESS_KEY_ID", "value": AWS_ACCESS_KEY_ID},
                        {"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {
                            "name": "acp-secrets", "key": "database-url"}}},
                    ],
                }]}}},
            "status": {"readyReplicas": 4, "availableReplicas": 4, "updatedReplicas": 4,
                       "conditions": [{"type": "Available", "status": "True",
                                       "reason": "MinimumReplicasAvailable", "message": ""}]},
        }),
        "services": _list({
            "metadata": {"name": "acp-api"},
            "spec": {"type": "ClusterIP", "clusterIP": "10.0.14.22",
                     "selector": {"app.kubernetes.io/component": "api"},
                     "ports": [{"name": "http", "port": 80, "targetPort": 8000}]},
        }),
        "ingresses": _list({
            "metadata": {"name": "acp"},
            "spec": {"ingressClassName": "nginx",
                     "rules": [{"host": "acp.example.org"}],
                     "tls": [{"secretName": "acp-tls", "hosts": ["acp.example.org"]}]},
            "status": {"loadBalancer": {"ingress": [{"ip": "20.31.4.9"}]}},
        }),
        "poddisruptionbudgets": _list({
            "metadata": {"name": "acp-api"},
            "spec": {"minAvailable": 1},
            "status": {"currentHealthy": 2, "desiredHealthy": 1, "disruptionsAllowed": 1},
        }),
        "networkpolicies": _list({
            "metadata": {"name": "acp-default-deny"},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"],
                     "ingress": [{}], "egress": [{}, {}]},
        }),
        "externalsecrets": _list({
            "metadata": {"name": "acp-secrets"},
            "spec": {"secretStoreRef": {"name": "acp-production-acp-store", "kind": "SecretStore"},
                     "target": {"name": "acp-secrets"},
                     "data": [{"secretKey": "database-url"}, {"secretKey": "redis-url"}]},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }),
        # THE OBJECT THIS BUNDLE MUST HANDLE CORRECTLY. Full `data`, exactly as the API serves it.
        "secrets": _list({
            "metadata": {"name": "acp-secrets"},
            "type": "Opaque",
            "data": {"database-url": SECRET_DATA_BASE64,
                     "redis-url": SECRET_DATA_BASE64,
                     "langfuse-secret-key": SECRET_DATA_BASE64},
        }),
        "configmaps": _list({
            "metadata": {"name": "acp-config",
                         "labels": {"app.kubernetes.io/part-of": "acp"}},
            "data": {
                "LOG_LEVEL": "info",
                "WORKER_CONCURRENCY": "4",
                # By key name, by the document's own ref names, and by shape.
                "DATABASE_URL": POSTGRES_URL,
                "REDIS_URL": REDIS_URL,
                "BROKER_URL": AMQP_URL,
                "MONGO_URL": MONGO_URL,
                "SERVICE_TOKEN": UNRECOGNISED_HIGH_ENTROPY,
                "AWS_SECRET_ACCESS_KEY": AWS_SECRET_ACCESS_KEY,
                "signing-key": UNRECOGNISED_HIGH_ENTROPY,
                "azure-storage": f"AccountKey={AZURE_STORAGE_KEY}",
                "azure-sas-url": f"https://acp.blob.core.windows.net/c/b?{AZURE_SAS}",
                # JSON inside a string.
                "extra.json": json.dumps({"api_key": UNRECOGNISED_HIGH_ENTROPY,
                                          "password": PLAIN_PASSWORD, "region": "eastus2"}),
                # A YAML block scalar inside a string.
                "app.yaml": ("logging:\n  level: info\n"
                             f"database:\n  password: {PLAIN_PASSWORD}\n  poolSize: 20\n"),
                # A service-account JSON, whose private_key arrives with escaped newlines.
                "gcp.json": ('{"type": "service_account", "project_id": "acp-prod", '
                             f'"private_key": "{GCP_PRIVATE_KEY}"}}'),
                # A log line with an Authorization header in it.
                "startup.log": (f"2026-09-08T09:00:01Z INFO calling langfuse "
                                f"Authorization: Bearer {BEARER_TOKEN}\n"
                                f"2026-09-08T09:00:02Z INFO calling registry "
                                f"Authorization: Basic {BASIC_CREDENTIAL}\n"),
            },
        }),
        "configmap/acp-installation": {
            "metadata": {"name": "acp-installation",
                         "labels": {"app.kubernetes.io/part-of": "acp"},
                         "annotations": {"acp.mova.io/installed-by": "acpctl 0.1.0-alpha"}},
            "data": {"release": "2026.9", "profile": "standard", "platform": "azure",
                     "image": IMAGE, "installedAt": "2026-09-01T10:00:00Z",
                     "valuesChecksum": "9c" * 32},
        },
        "events": _list(
            {"metadata": {"name": "acp-worker-remediate.17f"},
             "involvedObject": {"kind": "Pod", "name": POD_NAME},
             "type": "Warning", "reason": "BackOff", "count": 12,
             "lastTimestamp": "2026-09-08T09:05:00Z",
             "message": f"Back-off restarting failed container; DSN was {POSTGRES_URL}"},
            {"metadata": {"name": "acp-api.17e"},
             "involvedObject": {"kind": "Pod", "name": "acp-api-58c9f6d7b4-hh2wq"},
             "type": "Normal", "reason": "Pulled", "count": 1,
             "lastTimestamp": "2026-09-08T08:59:00Z",
             "message": f"Successfully pulled image \"{IMAGE}\""},
        ),
    }


def bundle_fixture(**overrides) -> dict:
    fixture = fake.shape(objects=bundle_objects(),
                         jobs=[{"name": "acp-migrate-2026-9", "component": "migrations",
                                "succeeded": 1}])
    fixture.update(overrides)
    return fixture


def generate_bundle(tmp_path: Path, fixture: dict | None = None, *, out: str = "bundle",
                    document=..., archive: bool = False):
    """The real `generate()` against the fake kubectl. Returns (report, root)."""
    from acpctl import support_bundle as sb

    if document is ...:
        document = load_example("standard-production")
    root = tmp_path / out
    env = install_fake(tmp_path, fixture if fixture is not None else bundle_fixture())
    with using(env):
        report = sb.generate(out_dir=root, namespace=NAMESPACE, document=document,
                             document_path=str(EXAMPLE), archive=archive)
    return report, root


def collection(report, name) -> dict:
    for entry in report["collections"]:
        if entry["collection"] == name:
            return entry
    raise AssertionError(
        f"no collection {name!r}; have {[c['collection'] for c in report['collections']]}")


def bundle_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def kubectl_log(tmp_path: Path) -> list[str]:
    path = tmp_path / "kubectl.log"
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# The harness's own bite checks
# ══════════════════════════════════════════════════════════════════════════════

def test_the_fake_kubectl_is_actually_being_used(tmp_path):
    """If the fake were not on PATH, `gather` would report the cluster unreachable and every
    assertion below would collapse into one uninformative failure — or worse, a test asserting a
    FAILED collection would pass because the unreachable path produces one too."""
    report, root = generate_bundle(tmp_path)
    assert report["reachable"] is True, report
    log = kubectl_log(tmp_path)
    assert any(line.startswith("version") for line in log), log
    assert any("get pods" in line for line in log), log
    assert (root / "manifest.json").exists()


def test_the_wrapper_still_refuses_a_non_read_verb(tmp_path):
    """A guard on the guard: the delegating wrapper must not have opened a hole in the shared
    fake's refusal of mutating verbs, since that refusal is what makes every read-only claim in
    these tests checkable rather than asserted."""
    import subprocess

    env = install_fake(tmp_path, bundle_fixture())
    proc = subprocess.run([str(tmp_path / "bin" / "kubectl"), "delete", "pod", "acp-api"],
                          capture_output=True, text=True, env={**os.environ, **env})
    assert proc.returncode != 0
    assert "must not mutate" in proc.stderr


def test_the_fixture_plants_a_credential_of_every_shape():
    """The fixture is the test. A planted value that is not actually secret-shaped would make the
    sweep below pass without the filter doing anything, so each one is checked against the filter
    in isolation first."""
    from acpctl.support_bundle import redact

    assert len(AZURE_STORAGE_KEY) == 88 and AZURE_STORAGE_KEY.endswith("==")
    # Two of them are deliberately NOT recognisable on their own, and saying which is the honest
    # description of the filter: a short password has no shape at all and is caught by the key
    # beside it, and a Secret's base64 `data` is caught by never being collected in the first
    # place. Everything else has to stand up with no context to help it.
    by_context = {"password", "secret-data"}
    for name, value in PLANTED.items():
        if name in by_context:
            continue
        assert redact(value) != value, f"the planted {name} is not recognised by the filter"
    assert PLAIN_PASSWORD not in redact(f"password: {PLAIN_PASSWORD}")


# ══════════════════════════════════════════════════════════════════════════════
# Redaction — determinism and stable placeholders
# ══════════════════════════════════════════════════════════════════════════════

def test_redaction_is_deterministic():
    """Same input, byte-identical output — the property that lets an operator run the tool twice
    and diff, which is the cheapest way to convince yourself nothing is being sampled."""
    from acpctl.support_bundle import redact

    text = f"dsn={POSTGRES_URL} token={JWT} key={AWS_SECRET_ACCESS_KEY}"
    assert redact(text) == redact(text)
    assert redact(text).encode("utf-8") == redact(text).encode("utf-8")


def test_redaction_is_idempotent():
    """Redacting an already-redacted string must be a no-op. Without it the placeholders
    themselves become candidates — `password=REDACTED[...]` is an assignment whose value looks
    unredacted — and a bundle re-scanned by `verify_bundle` would report every placeholder as a
    leak and delete itself."""
    from acpctl.support_bundle import redact

    once = redact(f"password={PLAIN_PASSWORD} and dsn={POSTGRES_URL}")
    assert redact(once) == once


def test_the_same_secret_gets_the_same_placeholder():
    """The fact worth preserving: two components sharing a credential is frequently the bug, and
    a reader can see that without learning the credential."""
    from acpctl.support_bundle import Redactor

    redactor = Redactor()
    tree = redactor.tree({"api": {"password": PLAIN_PASSWORD},
                          "worker": {"password": PLAIN_PASSWORD}})
    assert tree["api"]["password"] == tree["worker"]["password"]
    assert PLAIN_PASSWORD not in json.dumps(tree)


def test_two_different_secrets_get_different_placeholders():
    from acpctl.support_bundle import Redactor

    redactor = Redactor()
    tree = redactor.tree({"api": {"password": PLAIN_PASSWORD},
                          "worker": {"password": PLAIN_PASSWORD + "-other"}})
    assert tree["api"]["password"] != tree["worker"]["password"]


def test_the_placeholder_carries_no_recoverable_information():
    """The reason the scheme is a counter and not a hash: a hashed placeholder is an ORACLE — hash
    a guess, compare, and a low-entropy secret is recovered from a bundle that looks redacted.
    A counter cannot be checked against a guess, which this asserts by construction: the
    placeholder for a value must not depend on the value at all beyond its identity."""
    from acpctl.support_bundle import Redactor

    first = Redactor().tree({"password": PLAIN_PASSWORD})["password"]
    second = Redactor().tree({"password": "something-completely-different"})["password"]
    assert first == second, ("two different values in the same position produced different "
                             "placeholders, so the placeholder encodes the value")


# ══════════════════════════════════════════════════════════════════════════════
# Redaction — one case per category
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value", [POSTGRES_URL, REDIS_URL, AMQP_URL, MONGO_URL,
                                   "mongodb://acp:p@mongo.internal:27017/acp",
                                   "rediss://:p@redis.internal:6380/0"])
def test_connection_strings_are_redacted(value):
    from acpctl.support_bundle import redact

    out = redact(f"connecting to {value} now")
    assert value not in out
    assert "REDACTED[" in out


def test_a_url_carrying_userinfo_is_redacted_whole():
    """Host included. Partial rewriting of a URL is where redactors leak — the userinfo reappears
    percent-encoded, in a query parameter, or after a proxy rewrite — and the topology the host
    would have told you is in the Service, the Ingress and the document, all of which are in the
    bundle already."""
    from acpctl.support_bundle import redact

    out = redact("callback https://svc-account:hunter2@langfuse.example.org/api/public")
    assert "hunter2" not in out and "svc-account" not in out


def test_bearer_and_authorization_headers_are_redacted():
    from acpctl.support_bundle import redact

    assert BEARER_TOKEN not in redact(f"Authorization: Bearer {BEARER_TOKEN}")
    assert BASIC_CREDENTIAL not in redact(f"Authorization: Basic {BASIC_CREDENTIAL}")
    # Stopping at the next space would redact the word "Basic" and publish the credential.
    assert BASIC_CREDENTIAL not in redact(f"authorization={BASIC_CREDENTIAL}")


def test_aws_credentials_are_redacted():
    from acpctl.support_bundle import redact

    assert AWS_ACCESS_KEY_ID not in redact(f"AWS_ACCESS_KEY_ID={AWS_ACCESS_KEY_ID}")
    # The access key id is recognised on its own, with no key name to help.
    assert AWS_ACCESS_KEY_ID not in redact(f"the caller was {AWS_ACCESS_KEY_ID}")
    assert AWS_SECRET_ACCESS_KEY not in redact(
        f"aws_secret_access_key = {AWS_SECRET_ACCESS_KEY}")


def test_azure_storage_keys_and_sas_tokens_are_redacted():
    from acpctl.support_bundle import redact

    assert AZURE_STORAGE_KEY not in redact(f"the key is {AZURE_STORAGE_KEY}")
    assert AZURE_STORAGE_KEY not in redact(
        f"DefaultEndpointsProtocol=https;AccountName=acp;AccountKey={AZURE_STORAGE_KEY};"
        "EndpointSuffix=core.windows.net")
    assert "Xk3Not3AReal3Signature3Value3Xyz" not in redact(
        f"https://acp.blob.core.windows.net/container/blob?{AZURE_SAS}")


def test_pem_blocks_and_gcp_service_account_keys_are_redacted():
    from acpctl.support_bundle import redact

    assert "MIIEowIBAAKCAQEA" not in redact(f"key material follows\n{PEM_KEY}\ndone")
    service_account = ('{"type": "service_account", "project_id": "acp", '
                       f'"private_key": "{GCP_PRIVATE_KEY}"}}')
    out = redact(service_account)
    assert "MIIEvQIBADANBgkqhkiG9w0BA" not in out
    assert "service_account" in out, "the surrounding JSON is diagnostic and should survive"


def test_jwts_are_redacted():
    from acpctl.support_bundle import redact

    assert JWT not in redact(f"upstream returned 401 for {JWT}")


@pytest.mark.parametrize("name", ["API_TOKEN", "CLIENT_SECRET", "DB_PASSWORD", "SIGNING_KEY",
                                  "signing-key", "apiKey", "sessionKey"])
def test_generic_secret_key_names_are_redacted_by_name(name):
    """By NAME, not by shape. `DB_PASSWORD=letmein` has no recognisable shape at all — a short
    lowercase word — and it is the most common secret in any configuration."""
    from acpctl.support_bundle import redact, redact_tree

    assert "letmein" not in redact(f"{name}=letmein")
    assert "letmein" not in json.dumps(redact_tree({name: "letmein"}))


def test_key_names_from_the_documents_secret_refs_are_redacted():
    """The document names the keys an installation's credentials are stored under. Anything
    ELSEWHERE in the bundle carrying one of those names is a value that should have stayed in the
    vault, whatever it looks like."""
    from acpctl.support_bundle import Redactor

    document = load_example("standard-production")
    names = list((document.get("secrets") or {}).get("refs") or {})
    assert "langfuse-secret-key" in names, "the example stopped declaring the ref this test uses"
    redactor = Redactor(secret_key_names=names)
    tree = redactor.tree({"data": {"langfuse-secret-key": "sk-lf-0000", "LOG_LEVEL": "info"}})
    assert tree["data"]["langfuse-secret-key"] != "sk-lf-0000"
    assert tree["data"]["LOG_LEVEL"] == "info"


def test_an_unrecognised_high_entropy_value_is_redacted():
    """CONSERVATIVE IN THE RIGHT DIRECTION. Nothing about this string says what it is — no scheme,
    no key name, no vendor prefix — and the filter redacts it anyway, because the cost of being
    wrong in the other direction is a credential in a ticket."""
    from acpctl.support_bundle import redact

    out = redact(f"the upstream returned {UNRECOGNISED_HIGH_ENTROPY} and then stopped")
    assert UNRECOGNISED_HIGH_ENTROPY not in out
    assert "REDACTED[high-entropy#" in out


@pytest.mark.parametrize("survivor", [
    IMAGE,
    "sha256:" + "3f" * 32,
    POD_NAME,
    "aks-workers-41231234-vmss000002",
    "LOG_LEVEL=debug",
    "acp.example.org",
    "app.kubernetes.io/part-of=acp",
])
def test_the_facts_that_must_survive_survive(survivor):
    """OVER-REDACTION IS ITS OWN FAILURE. An image digest is 64 hex characters that every entropy
    heuristic wants to eat, and it is the single most useful fact in the bundle — "what actually
    ran". A pod name is 37 characters of apparent noise and it is how a reader finds the pod
    again. A filter that eats these produces a bundle nobody can use, and the response to that is
    to turn the filter off."""
    from acpctl.support_bundle import redact

    assert redact(f"context: {survivor} here") == f"context: {survivor} here"


# ══════════════════════════════════════════════════════════════════════════════
# Redaction — nesting
# ══════════════════════════════════════════════════════════════════════════════

def test_a_secret_inside_json_inside_a_string_is_redacted():
    from acpctl.support_bundle import redact_tree

    blob = json.dumps({"api_key": UNRECOGNISED_HIGH_ENTROPY, "password": PLAIN_PASSWORD,
                       "region": "eastus2"})
    out = json.dumps(redact_tree({"data": {"extra.json": blob}}))
    assert UNRECOGNISED_HIGH_ENTROPY not in out and PLAIN_PASSWORD not in out
    assert "eastus2" in out, "the non-secret fields of the embedded JSON should survive"


def test_a_secret_inside_a_yaml_block_scalar_is_redacted():
    from acpctl.support_bundle import redact_tree

    block = f"logging:\n  level: info\ndatabase:\n  password: {PLAIN_PASSWORD}\n  poolSize: 20\n"
    out = json.dumps(redact_tree({"data": {"app.yaml": block}}))
    assert PLAIN_PASSWORD not in out
    assert "poolSize" in out and "level: info" in out


def test_a_secret_inside_a_log_line_is_redacted():
    from acpctl.support_bundle import redact_tree

    line = (f"2026-09-08T09:00:01Z ERROR worker.remediate could not connect to {POSTGRES_URL} "
            f"(attempt 3)")
    out = json.dumps(redact_tree({"message": line}))
    assert POSTGRES_URL not in out and "Tr0ub4dor" not in out
    assert "worker.remediate" in out and "attempt 3" in out


def test_a_secret_nested_three_deep_in_a_structure_is_redacted():
    from acpctl.support_bundle import redact_tree

    tree = {"items": [{"spec": {"triggers": [{"metadata": {"connection": REDIS_URL}}]}}]}
    assert "R3dis-P4ssw0rd" not in json.dumps(redact_tree(tree))


def test_a_section_named_like_a_secret_keeps_its_structure():
    """The other direction of the key rule, and a real regression: the document's `secrets.refs`
    declares a ref named `object-storage`, which normalises to exactly `data.objectStorage`. The
    naive rule replaced that whole block — mode, encryption, retentionDays — with one placeholder,
    in the first file a support engineer reads, to hide three settings that are not secret."""
    from acpctl.support_bundle import Redactor

    redactor = Redactor(secret_key_names=["object-storage"])
    tree = redactor.tree({"data": {"objectStorage": {"mode": "managed", "retentionDays": 365}}})
    assert tree["data"]["objectStorage"] == {"mode": "managed", "retentionDays": 365}


def test_the_documents_secret_references_survive_redaction():
    """PRD S9: the document holds secret REFERENCES and never raw secrets. Redacting the refs
    would erase the most useful half of the document to hide something that is not there — and
    `which vault key is this pod missing` is the question the bundle most often answers."""
    from acpctl.support_bundle import Redactor

    document = load_example("standard-production")
    redactor = Redactor(secret_key_names=list((document.get("secrets") or {}).get("refs") or {}))
    out = redactor.tree(document, key_exempt_paths=(("secrets", "refs"),))
    assert out["secrets"] == document["secrets"], "the refs block should be unchanged"
    assert out == document, "the shipped example contains no secrets, so nothing should change"


# ══════════════════════════════════════════════════════════════════════════════
# The written bundle
# ══════════════════════════════════════════════════════════════════════════════

def test_no_planted_secret_appears_in_the_written_bytes(tmp_path):
    """THE ASSERTION THAT ACTUALLY CATCHES LEAKS.

    Against the raw bytes of every file in the bundle, not against parsed structures. A parsed
    assertion checks the fields somebody remembered to check; the bytes are what gets attached to
    a ticket. Every value in PLANTED is somewhere in the fixture — a ConfigMap, an env literal, a
    pod's termination message, an Event, a Secret's data — and none of them may come out.
    """
    report, root = generate_bundle(tmp_path)
    assert report["ok"] is True, report
    raw = bundle_bytes(root)
    assert raw, "the bundle is empty; this test would pass vacuously"
    leaked = [name for name, value in PLANTED.items() if value.encode("utf-8") in raw]
    assert not leaked, f"these planted secrets reached the written bundle: {leaked}"


def test_the_bundle_keeps_the_facts_a_reader_needs(tmp_path):
    """The complement of the sweep above, and just as necessary: a bundle that redacts everything
    passes the leak test perfectly and is worthless."""
    _, root = generate_bundle(tmp_path)
    raw = bundle_bytes(root).decode("utf-8")
    for survivor in (IMAGE, "sha256:" + "3f" * 32, POD_NAME, "CrashLoopBackOff",
                     "acp-worker-remediate", "acp.example.org", "acp-secrets"):
        assert survivor in raw, f"{survivor!r} should have survived redaction"


def test_secret_objects_contribute_names_and_keys_only(tmp_path):
    """PRD S13, at its narrowest point. The keys are worth having — "the Secret exists but has no
    `database-url` key" explains a pod stuck in CreateContainerConfigError — and they are worth
    having without anybody sending a vault."""
    _, root = generate_bundle(tmp_path)
    written = json.loads((root / "namespace" / NAMESPACE / "secrets.json").read_text())
    assert written == [{"name": "acp-secrets", "type": "Opaque",
                        "keys": ["database-url", "langfuse-secret-key", "redis-url"],
                        "annotations": []}]
    text = (root / "namespace" / NAMESPACE / "secrets.json").read_text()
    assert '"data"' not in text and '"stringData"' not in text
    assert SECRET_DATA_BASE64 not in text


def test_pod_images_and_restarts_are_collected(tmp_path):
    """How a reader learns what actually ran. `image` is what the spec asked for and `imageID` is
    what the kubelet pulled; they disagree exactly when the interesting bugs happen."""
    _, root = generate_bundle(tmp_path)
    pods = json.loads((root / "namespace" / NAMESPACE / "pods.json").read_text())
    assert len(pods) == 1
    container = pods[0]["containers"][0]
    assert container["image"] == IMAGE
    assert container["imageID"] == IMAGE_ID
    assert container["restarts"] == 7
    assert container["state"]["waiting"]["reason"] == "CrashLoopBackOff"
    assert pods[0]["phase"] == "Running" and pods[0]["name"] == POD_NAME


def test_the_manifest_describes_every_file_it_wrote(tmp_path):
    """Sizes and hashes taken from the bytes on disk, not from the objects before serialisation —
    the manifest has to describe the artifact, not the intention."""
    _, root = generate_bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    written = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    written.discard("manifest.json")
    recorded = {c["path"] for c in manifest["collections"] if c["path"]}
    assert recorded == written, "manifest.json and the directory disagree about what was collected"
    for entry in manifest["collections"]:
        if not entry["path"]:
            continue
        payload = (root / entry["path"]).read_bytes()
        assert entry["bytes"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()


def test_the_manifest_records_skipped_collections_with_a_reason(tmp_path):
    """THE THREE-OUTCOME RULE, WHICH IS THE POINT OF THE MANIFEST. "there are no ScaledObjects"
    and "this cluster does not serve KEDA, so we did not ask" lead to opposite investigations, and
    a bundle that silently omits the second sends a support engineer to the wrong place."""
    report, root = generate_bundle(tmp_path, bundle_fixture(
        api_resources=[r for r in fake.HEALTHY["api_resources"] if not r.endswith("keda.sh")]))
    entry = collection(report, "scaledobjects")
    assert entry["outcome"] == "SKIPPED"
    assert "keda" in entry["reason"].lower()
    assert entry["path"] is None
    # SKIPPED is not FAILED: nothing was broken, so the bundle is still complete.
    assert report["ok"] is True, report
    assert not (root / "namespace" / NAMESPACE / "scaledobjects.json").exists()


def test_a_missing_install_state_configmap_is_skipped_not_failed(tmp_path):
    """`acpctl install` writes it; a release installed with helm directly, or by an older acpctl,
    has none. Read opportunistically by name, and its absence is normal."""
    objects = bundle_objects()
    objects["configmap/acp-installation"] = (
        'Error from server (NotFound): configmaps "acp-installation" not found')
    report, _ = generate_bundle(tmp_path, bundle_fixture(objects=objects))
    entry = collection(report, "install-state")
    assert entry["outcome"] == "SKIPPED"
    assert "acpctl install" in entry["reason"]
    assert report["ok"] is True


def test_the_install_state_configmap_is_collected_when_present(tmp_path):
    _, root = generate_bundle(tmp_path)
    state = json.loads((root / "namespace" / NAMESPACE / "install-state.json").read_text())
    assert state["data"]["release"] == "2026.9"
    assert state["data"]["image"] == IMAGE


def test_a_refused_read_is_recorded_as_failed_with_its_reason(tmp_path):
    """An operator with permission to read pods and not Events should still get everything else,
    and be told which read did not happen — a partial bundle that says so beats a wrong one."""
    objects = bundle_objects()
    objects["events"] = ('Error from server (Forbidden): events is forbidden: User "acp-support" '
                         'cannot list resource "events" in the namespace')
    report, root = generate_bundle(tmp_path, bundle_fixture(objects=objects))
    entry = collection(report, "events")
    assert entry["outcome"] == "FAILED"
    assert "Forbidden" in entry["reason"]
    # Non-blocking: a bundle without Events is poorer, not useless.
    assert report["ok"] is True
    assert (root / "namespace" / NAMESPACE / "pods.json").exists()


def test_a_blocking_collection_failure_is_reported_and_the_bundle_is_kept(tmp_path):
    """Exit 1, and the bundle stays on disk. Something a support engineer will ask for is missing,
    and the rest of it is still worth sending — the manifest says which part is absent and why."""
    objects = bundle_objects()
    objects["pods"] = 'Error from server (Forbidden): pods is forbidden'
    report, root = generate_bundle(tmp_path, bundle_fixture(objects=objects))
    assert collection(report, "pods")["outcome"] == "FAILED"
    assert report["blockingFailures"] == ["pods"]
    assert report["ok"] is False
    assert root.exists() and (root / "manifest.json").exists()


def test_an_unreachable_cluster_writes_nothing(tmp_path):
    """Nothing established, so no artifact. An empty bundle for a cluster nobody reached is a
    thing that looks like evidence and contains none."""
    from acpctl import support_bundle as sb

    root = tmp_path / "bundle"
    env = install_fake(tmp_path, fake.shape(server_version=None))
    with using(env):
        report = sb.generate(out_dir=root, namespace=NAMESPACE,
                             document=load_example("standard-production"))
    assert report["reachable"] is False
    assert report["ok"] is False
    assert not root.exists(), "an unreachable cluster must not leave a directory behind"


def test_generation_refuses_a_non_empty_output_directory(tmp_path):
    """A SAFETY RULE, NOT TIDINESS. A bundle that fails verification is deleted wholesale, so this
    function must never be able to delete a directory it did not create — pointing `--out` at a
    home directory and having the filter fire would otherwise be catastrophic."""
    from acpctl import support_bundle as sb

    root = tmp_path / "bundle"
    root.mkdir()
    (root / "important.txt").write_text("someone else's file", encoding="utf-8")
    env = install_fake(tmp_path, bundle_fixture())
    with using(env), pytest.raises(sb.SupportBundleError) as excinfo:
        sb.generate(out_dir=root, namespace=NAMESPACE,
                    document=load_example("standard-production"))
    assert "refusing" in str(excinfo.value)
    assert (root / "important.txt").exists()


def test_two_bundles_of_the_same_state_are_byte_identical(tmp_path):
    """Determinism end to end, not only in the filter. Every collected file is a pure function of
    the cluster state and the document — the collection TIME is the one field that is not, and it
    is in the manifest where it can be ignored by a diff."""
    first, first_root = generate_bundle(tmp_path / "a", out="bundle")
    second, second_root = generate_bundle(tmp_path / "b", out="bundle")
    assert first["ok"] and second["ok"]

    def files(root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"}

    assert files(first_root) == files(second_root)

    first_manifest = json.loads((first_root / "manifest.json").read_text())
    second_manifest = json.loads((second_root / "manifest.json").read_text())
    assert first_manifest.pop("generatedAt") != "" and second_manifest.pop("generatedAt") != ""
    assert first_manifest == second_manifest


def test_the_archive_contains_the_bundle_and_leaves_it_in_place(tmp_path):
    """The directory stays: an operator should be able to read what they are about to attach to a
    ticket. The tar entries are normalised so the archive inherits the directory's determinism —
    and so the operator's uid and username do not travel to a vendor with it."""
    report, root = generate_bundle(tmp_path, archive=True)
    archive = Path(report["archive"])
    assert archive.exists() and root.exists()
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
    assert any(m.name.endswith("manifest.json") for m in members)
    assert all(m.mtime == 0 and m.uid == 0 and m.uname == "" for m in members), \
        "tar metadata carries the operator's identity into the artifact"


# ══════════════════════════════════════════════════════════════════════════════
# verify_bundle
# ══════════════════════════════════════════════════════════════════════════════

def test_verify_bundle_is_clean_for_a_bundle_the_filter_wrote(tmp_path):
    from acpctl.support_bundle import verify_bundle

    _, root = generate_bundle(tmp_path)
    assert verify_bundle(root) == []


def test_a_leak_that_gets_past_the_filter_deletes_the_bundle(tmp_path, monkeypatch):
    """THE BITE CHECK ON THE VERIFIER.

    The regexes cannot catch what they do not match, so re-running them proves nothing about the
    patterns. What `verify_bundle` guards is a COLLECTOR that writes a value without passing it
    through the filter at all — one line of ordinary-looking code, invisible in review. So the
    tree walker is neutered here to produce exactly that mistake, and the bundle must be DELETED
    rather than reported as written: a leaking artifact on disk is worse than no artifact, because
    the operator believes the redaction happened.
    """
    from acpctl import support_bundle as sb

    monkeypatch.setattr(sb.Redactor, "tree",
                        lambda self, value, **kwargs: value, raising=True)
    report, root = generate_bundle(tmp_path)

    assert report["ok"] is False
    assert report["leaks"], "the neutered filter published a connection string and nothing noticed"
    assert not root.exists(), "a bundle that fails its own scan must not be left on disk"
    categories = {leak["category"] for leak in report["leaks"]}
    assert "connection-string" in categories
    # The report names the shape and the place, never the value — it is printed to a terminal and
    # pasted into tickets, and re-publishing the secret there is the same leak again.
    assert POSTGRES_URL not in json.dumps(report["leaks"])


def test_verify_bundle_catches_a_secret_objects_data(tmp_path):
    """Defence in depth for the one object that is a secret by definition. A Secret's `data` is
    base64, so NO shape rule would ever fire on it — this is what says on disk that
    `_reduce_secret` kept names and keys only, and it fails the day somebody "simplifies" that
    reducer into a pass-through."""
    from acpctl.support_bundle import verify_bundle

    _, root = generate_bundle(tmp_path)
    target = root / "namespace" / NAMESPACE / "secrets.json"
    target.write_text(json.dumps([{"kind": "Secret", "metadata": {"name": "acp-secrets"},
                                   "data": {"database-url": SECRET_DATA_BASE64}}], indent=2),
                      encoding="utf-8")
    leaks = verify_bundle(root)
    assert any(leak.category == "secret-data" for leak in leaks), leaks


def test_verify_bundle_treats_an_unreadable_file_as_a_leak(tmp_path):
    """"We could not check it" must never resolve to "it is fine" — the same rule doctor's
    `unknown` outcome exists for."""
    from acpctl.support_bundle import verify_bundle

    _, root = generate_bundle(tmp_path)
    (root / "cluster" / "binary.bin").write_bytes(b"\xff\xfe\x00\x01not-utf-8")
    assert any(leak.category == "unreadable-file" for leak in verify_bundle(root))


# ══════════════════════════════════════════════════════════════════════════════
# The read-only and customer-data boundaries
# ══════════════════════════════════════════════════════════════════════════════

# Every Kubernetes resource the bundle is allowed to ask for. All of them describe the
# INSTALLATION. None of them is application data.
EXPECTED_RESOURCES = {
    "nodes", "daemonsets", "ingressclasses", "storageclasses", "secretstores", "namespace",
    "deployments", "pods", "services", "ingresses", "jobs", "poddisruptionbudgets",
    "networkpolicies", "scaledobjects", "externalsecrets", "secrets", "configmaps", "configmap",
    "events",
}


def test_the_whole_run_issues_only_read_verbs(tmp_path):
    """Asserted on the fake's call log, which is the only place the claim is checkable. A
    read-only promise nobody checks is a comment — and `doctor`'s docstring records that the
    phase-0 guard for this patched `open()`, which cannot see a subprocess at all."""
    generate_bundle(tmp_path)
    log = kubectl_log(tmp_path)
    assert log, "nothing was run; this test would pass vacuously"
    verbs = set()
    for line in log:
        args = line.split()
        while args and args[0] == "--context":
            args = args[2:]
        verbs.add(args[0] if args else "")
    assert verbs <= {"version", "api-resources", "get"}, sorted(verbs)


def test_the_read_verb_allow_list_has_not_been_widened():
    """The bundle's boundary is enforced by cluster.py's allow-list rather than by this module's
    good intentions — `kubectl logs` and `kubectl exec` are not refused by a check here, they are
    unreachable. A change that adds either would make container output collectable, and container
    output is where customer document names and content live."""
    from acpctl import cluster as cluster_mod

    assert set(cluster_mod.READ_VERBS) == {"version", "api-resources", "get"}


def test_the_bundle_never_reaches_for_customer_document_data(tmp_path):
    """THE BOUNDARY, NAMED. This bundle is about the INSTALLATION, not about the customer's
    documents. No object-storage object, no database row, no document name, no user identity, no
    job payload and no container log is collected — PRD S13 requires exactly that ("Support
    bundles redact tokens, document names, user identities and file contents"), and the cheapest
    way to keep the promise is never to fetch the data in the first place.

    Asserted on what was actually asked for rather than on the module's intentions: every
    resource in the call log has to be a Kubernetes object describing the install.
    """
    generate_bundle(tmp_path)
    requested = set()
    for line in kubectl_log(tmp_path):
        args = line.split()
        while args and args[0] == "--context":
            args = args[2:]
        if args and args[0] == "get":
            requested.add(args[1])
    assert requested, "nothing was requested; this test would pass vacuously"
    unexpected = requested - EXPECTED_RESOURCES
    assert not unexpected, (
        f"the bundle asked kubectl for {sorted(unexpected)}, which is not an installation object. "
        "If this is deliberate, the boundary in the module docstring has moved and needs saying.")


# ══════════════════════════════════════════════════════════════════════════════
# The command
# ══════════════════════════════════════════════════════════════════════════════

def parse(argv):
    import argparse

    from acpctl import support_bundle as sb

    parser = argparse.ArgumentParser(prog="acpctl")
    sub = parser.add_subparsers(dest="command", required=True)
    sb.add_parser(sub)
    return parser.parse_args(argv)


def test_add_parser_follows_the_conventions_of_the_other_commands():
    """Defined here rather than registered in cli.py: the command's arguments live beside the code
    that reads them, and `cli.build_parser` calls this."""
    from acpctl import support_bundle as sb

    args = parse(["support-bundle", str(EXAMPLE), "--out", "/tmp/x", "-n", "acp-production",
                  "--context", "prod", "--archive", "--json"])
    assert args.func is sb.cmd_support_bundle
    assert (args.spec, args.out, args.namespace, args.context) == (
        str(EXAMPLE), "/tmp/x", "acp-production", "prod")
    assert args.archive is True and args.json is True


def test_the_output_directory_is_required():
    """There is no default. A support bundle that lands somewhere the operator did not choose is
    one they cannot find, delete, or check before sending."""
    with pytest.raises(SystemExit):
        parse(["support-bundle", str(EXAMPLE)])


def test_the_command_exits_zero_on_a_bundle_that_verified(tmp_path, capsys):
    from acpctl import support_bundle as sb

    args = parse(["support-bundle", str(EXAMPLE), "--out", str(tmp_path / "bundle"),
                  "-n", NAMESPACE])
    with using(install_fake(tmp_path, bundle_fixture())):
        code = sb.cmd_support_bundle(args)
    assert code == 0
    out = capsys.readouterr().out
    assert "manifest.json" in out and "re-scanned" in out


def test_the_command_exits_two_when_the_cluster_is_unreachable(tmp_path, capsys):
    """Retryable, and deliberately not 1: there is no partial artifact and no leak, only an absent
    cluster. A pipeline should retry this and must not retry a blocking failure."""
    from acpctl import support_bundle as sb

    args = parse(["support-bundle", str(EXAMPLE), "--out", str(tmp_path / "bundle"),
                  "-n", NAMESPACE])
    with using(install_fake(tmp_path, fake.shape(server_version=None))):
        code = sb.cmd_support_bundle(args)
    assert code == 2
    assert "NOTHING WAS COLLECTED" in capsys.readouterr().out


def test_the_command_exits_one_when_a_blocking_collection_failed(tmp_path):
    from acpctl import support_bundle as sb

    objects = bundle_objects()
    objects["pods"] = "Error from server (Forbidden): pods is forbidden"
    args = parse(["support-bundle", str(EXAMPLE), "--out", str(tmp_path / "bundle"),
                  "-n", NAMESPACE])
    with using(install_fake(tmp_path, bundle_fixture(objects=objects))):
        code = sb.cmd_support_bundle(args)
    assert code == 1


def test_an_invalid_document_is_collected_rather_than_refused(tmp_path):
    """`plan`, `doctor` and `status` refuse an invalid document because their output would be
    derived from it and confidently wrong. A support bundle derives nothing — it collects — and
    the moment an operator most needs to send one is the moment their document does not validate.
    The validation result goes IN the bundle."""
    document = load_example("standard-production")
    document["profile"] = "not-a-profile"
    report, root = generate_bundle(tmp_path, document=document)
    assert report["ok"] is True, report
    validation = json.loads((root / "document-validation.json").read_text())
    assert validation["valid"] is False
    assert validation["errors"], "the failing rules belong in the bundle"


def test_an_unreadable_document_does_not_cost_the_cluster_half(tmp_path):
    """"The document could not be parsed" is itself a finding, and the cluster half is still worth
    having — so it is recorded as a failed collection rather than aborting the run."""
    from acpctl import support_bundle as sb

    root = tmp_path / "bundle"
    with using(install_fake(tmp_path, bundle_fixture())):
        report = sb.generate(out_dir=root, namespace=NAMESPACE, document=None,
                             document_error="ScannerError: mapping values are not allowed here")
    assert collection(report, "document")["outcome"] == "FAILED"
    assert "ScannerError" in collection(report, "document")["reason"]
    assert report["ok"] is False, "the document is blocking; the bundle is incomplete without it"
    assert (root / "namespace" / NAMESPACE / "pods.json").exists()
