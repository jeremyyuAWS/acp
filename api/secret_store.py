"""Where a provider credential physically lives, and the only way a key value is ever written.

ADR 0019 §6 stores the NAME of an ops-provisioned secret and never the value, because a key in
Postgres is a key in every backup, every replica and every support dump. That is still true here:
this module does not put a key in the database. What it adds is a second KIND of name — a Key
Vault secret rather than an environment variable — so an admin can paste a key into the product
and have it land in the vault instead of asking their ops team to redeploy a container.

    key_secret_ref = "AZURE_OPENAI_API_KEY"           -> read from os.environ  (unchanged)
    key_secret_ref = "keyvault:acp-ai-anthropic-key"  -> read from the vault   (new)

WHY A PREFIX RATHER THAN A SECOND COLUMN. The two are the same fact — "where this credential
lives" — and a second column would let a row name both, which is a state nobody has an answer
for. The prefix also keeps the existing env-var validator (`^[A-Z][A-Z0-9_]{2,64}$`) exactly as
strict as it was: it still rejects a pasted key on PUT /ai/providers, and a vault ref never
travels through that route at all.

WHAT THIS DOES NOT REMOVE. The key value now crosses ONE boundary it did not before: the browser
-> API request that sets it. That is the whole cost of the feature and it is not hidden — the
value is never echoed, never stored, never logged, and never returned by any read path, but a
request body carrying a credential exists where none did before. An operator who does not want
that keeps `ACP_KEY_VAULT_URL` unset: the write endpoint then refuses, and the product behaves
exactly as it did before this module existed.

The Azure SDKs are LAZY, OPTIONAL imports (ADR 0019 rule 8) — the default keyless build installs
neither and reports the store as unavailable with a reason, rather than failing at import.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Protocol, runtime_checkable

log = logging.getLogger("acp.secret_store")

VAULT_PREFIX = "keyvault:"
#: Azure Key Vault object names: letters, digits and dashes only, 1-127 chars. Deliberately NOT
#: the env-var charset — an underscore is legal in one and rejected by the other, and generating
#: a name the vault will refuse is a failure at write time with a half-configured row behind it.
VAULT_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,127}$")

#: Reads are cached: `_resolve_key` runs on the AI request path and a vault round-trip per call
#: would add latency and burn the vault's own rate limit. Short enough that a rotated secret is
#: picked up without a restart.
_CACHE_TTL_S = float(os.environ.get("ACP_SECRET_CACHE_TTL_S", "300"))
_cache: dict[str, tuple[float, str | None]] = {}


def is_vault_ref(ref: str | None) -> bool:
    return bool(ref) and str(ref).startswith(VAULT_PREFIX)


def vault_name(ref: str) -> str:
    """The bare secret name inside a `keyvault:` reference."""
    return str(ref)[len(VAULT_PREFIX):]


def ref_for(provider: str) -> str:
    """The vault reference this product writes a provider's key to.

    Derived, not chosen by the caller: a name supplied over HTTP would let one admin overwrite
    another provider's secret — or something else entirely in a shared vault — through a field
    that looks like a label.
    """
    slug = re.sub(r"[^A-Za-z0-9-]", "-", provider.strip().lower()).strip("-")
    name = f"acp-ai-{slug}-key"
    if not VAULT_NAME_RE.match(name):
        raise ValueError(f"provider {provider!r} does not yield a legal vault secret name")
    return f"{VAULT_PREFIX}{name}"


@runtime_checkable
class SecretStore(Protocol):
    kind: str

    def writable(self) -> tuple[bool, str]:
        """(can this store accept a value, why not if it cannot). The reason is shown to an
        admin, so it names the missing piece rather than saying 'unavailable'."""

    def write(self, name: str, value: str) -> None: ...

    def read(self, name: str) -> str | None: ...


class NoWriteSecretStore:
    """The default, and the world as it was before this module: secrets are provisioned by an ops
    team into the environment and this product only ever reads them."""

    kind = "environment"

    def __init__(self, reason: str):
        self._reason = reason

    def writable(self) -> tuple[bool, str]:
        return False, self._reason

    def write(self, name: str, value: str) -> None:
        raise RuntimeError(f"this deployment cannot write secrets: {self._reason}")

    def read(self, name: str) -> str | None:
        return None


class AzureKeyVaultSecretStore:
    """Azure Key Vault via the app's managed identity.

    NOT EXERCISED AGAINST A REAL VAULT IN THIS REPO'S TESTS — there is no vault in CI and none in
    a development container, so every test here drives a fake through the same Protocol. The first
    deployment that configures `ACP_KEY_VAULT_URL` is the first real execution of the two SDK
    calls below, and `POST /ai/providers/{provider}/secret` reports the failure verbatim if the
    identity lacks `secrets/set`. That is stated rather than papered over: a green test suite is
    not evidence about this class.
    """

    kind = "azure_key_vault"

    def __init__(self, vault_url: str):
        self.vault_url = vault_url
        self._client = None

    def _sdk(self):
        if self._client is None:
            from azure.identity import DefaultAzureCredential      # noqa: PLC0415 - optional dep
            from azure.keyvault.secrets import SecretClient        # noqa: PLC0415 - optional dep
            self._client = SecretClient(vault_url=self.vault_url,
                                        credential=DefaultAzureCredential())
        return self._client

    def writable(self) -> tuple[bool, str]:
        try:
            import azure.identity        # noqa: F401,PLC0415
            import azure.keyvault.secrets  # noqa: F401,PLC0415
        except ImportError:
            return False, ("ACP_KEY_VAULT_URL is set but the azure-keyvault-secrets / "
                           "azure-identity packages are not installed in this image")
        return True, ""

    def write(self, name: str, value: str) -> None:
        # The value is a credential: it is passed straight to the SDK and never formatted into a
        # log line, an exception message this code constructs, or a return value.
        self._sdk().set_secret(name, value)
        _cache.pop(name, None)
        log.info("wrote provider secret to key vault: name=%s", name)

    def read(self, name: str) -> str | None:
        try:
            return self._sdk().get_secret(name).value
        except Exception as e:                       # a missing secret is a normal answer here
            log.info("key vault read failed: name=%s reason=%s", name, type(e).__name__)
            return None


def active_secret_store() -> SecretStore:
    """The store this deployment uses. Unset `ACP_KEY_VAULT_URL` -> the read-only environment
    store, i.e. exactly the pre-existing behaviour."""
    url = (os.environ.get("ACP_KEY_VAULT_URL") or "").strip()
    if not url:
        return NoWriteSecretStore("no ACP_KEY_VAULT_URL is configured for this deployment")
    if not url.startswith("https://"):
        return NoWriteSecretStore("ACP_KEY_VAULT_URL must be an https:// vault URL")
    return AzureKeyVaultSecretStore(url)


def read_ref(ref: str | None) -> str | None:
    """Resolve a `keyvault:` reference, with a short cache. Returns None for anything else —
    environment refs are resolved by the caller, which is where they have always been resolved."""
    if not is_vault_ref(ref):
        return None
    name = vault_name(str(ref))
    hit = _cache.get(name)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]
    val = active_secret_store().read(name)
    _cache[name] = (now, val)
    return val


def clear_cache() -> None:
    """Drop cached secret values — called after a write, and by tests."""
    _cache.clear()


def write_provider_secret(provider: str, value: str) -> str:
    """Write one provider's key and return the REFERENCE to store. Never returns the value.

    Raises RuntimeError when this deployment has no writable store, which is the refusal the
    route turns into a 422 — the field must not silently fall back to putting a key anywhere else.
    """
    store = active_secret_store()
    ok, reason = store.writable()
    if not ok:
        raise RuntimeError(reason)
    value = (value or "").strip()
    if not value:
        raise ValueError("empty value")
    ref = ref_for(provider)
    store.write(vault_name(ref), value)
    clear_cache()
    return ref
