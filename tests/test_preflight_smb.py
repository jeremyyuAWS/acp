"""Preflight covers the network-drive (SMB) source (ADR 0032/0036).

scripts/preflight.py asks each deployment dependency directly and reports PASS / WARN / FAIL, never
borrowing PASS for what did not run. SMB is an optional source, so: unconfigured is a single WARN
(a choice, not a failure); shares + a credential is PASS on config with the live reach reported WARN
(cannot be verified headlessly); a half-configured connector (shares without a credential, or vice
versa) is FAIL; a dev username+password earns a posture WARN over the Key Vault path.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

_SMB_VARS = ("ACP_SMB_SHARES", "ACP_SMB_CREDENTIAL_KV", "ACP_SMB_USERNAME",
             "ACP_SMB_PASSWORD", "ACP_SMB_DOMAIN")


def _run(monkeypatch, env):
    for k in _SMB_VARS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import preflight
    importlib.reload(preflight)
    preflight.results.clear()
    preflight.check_smb()
    return dict((r["check"], r["state"]) for r in preflight.results)


def test_unconfigured_smb_is_a_single_warn_not_a_failure(monkeypatch):
    assert _run(monkeypatch, {}) == {"configured": "WARN"}


def test_shares_plus_key_vault_is_pass_with_reach_unverified(monkeypatch):
    r = _run(monkeypatch, {"ACP_SMB_SHARES": r"\\fs\a,\\fs\b", "ACP_SMB_CREDENTIAL_KV": "kv"})
    assert r["shares"] == "PASS" and r["credential"] == "PASS"
    assert r["share reachability"] == "WARN"                 # honest: config right ≠ reachable


def test_shares_without_a_credential_fails(monkeypatch):
    r = _run(monkeypatch, {"ACP_SMB_SHARES": r"\\fs\a"})
    assert r["credential"] == "FAIL"


def test_a_dev_password_earns_a_posture_warn(monkeypatch):
    r = _run(monkeypatch, {"ACP_SMB_SHARES": r"\\fs\a", "ACP_SMB_USERNAME": "u", "ACP_SMB_PASSWORD": "p"})
    assert r["credential"] == "PASS" and r["credential posture"] == "WARN"
