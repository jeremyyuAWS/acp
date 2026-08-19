"""SMB source preflight readiness (ADR 0032) — catch a misconfigured connector before a scan.

`describe_smb_readiness` inspects config only (no network) so a health check / the Content Sources UI
can say whether an SMB scan can be attempted, and fail with a specific reason rather than starting a
scan that returns an empty estate. Pins: shares + a credential source ⇒ ready; Key Vault wins over a
dev username+password when both are set; and each missing prerequisite is named.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import smb_source  # noqa: E402

SHARE = r"\\fs\dept"


def test_ready_with_shares_and_a_key_vault_credential():
    r = smb_source.describe_smb_readiness(
        {"shares": [SHARE], "credential_kv": "smb-svc", "username": None, "password": None})
    assert r["ready"] is True and r["missing"] == []
    assert r["credential_source"] == "key_vault" and r["share_count"] == 1


def test_ready_with_shares_and_a_username_password():
    r = smb_source.describe_smb_readiness(
        {"shares": [SHARE, r"\\nas\phi"], "credential_kv": None, "username": "u", "password": "p"})
    assert r["ready"] is True and r["credential_source"] == "userpass" and r["share_count"] == 2


def test_key_vault_wins_when_both_credential_sources_are_present():
    # A stray dev password in the env must not silently become the credential of record over the MI path.
    r = smb_source.describe_smb_readiness(
        {"shares": [SHARE], "credential_kv": "kv", "username": "u", "password": "p"})
    assert r["credential_source"] == "key_vault"


def test_not_ready_without_shares():
    r = smb_source.describe_smb_readiness({"shares": [], "credential_kv": "kv"})
    assert r["ready"] is False and any("shares" in m for m in r["missing"])


def test_not_ready_without_a_credential():
    r = smb_source.describe_smb_readiness(
        {"shares": [SHARE], "credential_kv": None, "username": None, "password": None})
    assert r["ready"] is False and r["credential_source"] is None
    assert any("credential" in m for m in r["missing"])
