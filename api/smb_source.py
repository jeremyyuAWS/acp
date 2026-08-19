"""Network-drive (SMB/CIFS) source adapter — Phase 1 scaffolding (ADR 0032).

A hospital's estate is not only Drive and SharePoint: a large, PHI-heavy share of it lives on on-prem
SMB file servers (`\\\\fileserver\\dept`, `H:\\`). ADR 0032 decides that a network drive is *a new
adapter, not a new pipeline* — everything downstream (the three-denominator inventory, the capability
matrix, the remediation appliers) is source-agnostic, so this only has to (1) LIST the tree into the
same file dicts discovery already consumes and (2) FETCH a file's bytes.

Deployment (per the UTSW variant of ADR 0032): the worker runs inside the customer's own VNet and
reaches on-prem shares over their private route; the read-only SMB service account credential comes
from Key Vault via Managed Identity. None of that lives here — this module is the adapter, and the
live SMB transport is isolated behind `_walk` / `_read` so the discovery logic is unit-testable
against a mock share with no server and no `smbprotocol` installed. What is DEPLOYMENT-GATED and
intentionally thin here: the real `smbprotocol` calls in `_walk`/`_read`, and Key Vault credential
resolution (see `smb_config`). The shaping, inventory, folder-skipping and truncation logic is real.

Mirrors `scanner._sp_list`: same file-dict shape, the same `scope_out["inventory"]` three-denominator
summary, the same honest truncation floor, the same `inventory_out` for non-scannable files.
"""
from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import PurePath

import estate_inventory

# The six formats ACP assesses — identical to the Drive/SharePoint adapters. Everything else is
# inventoried (counted, classified) but never opened, exactly as on the other sources.
_SCANNABLE_EXTS = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".htm"}

# ACP's own output must never be re-ingested (see provenance.py for the Drive equivalent): a share
# holding a `.../ACP-Remediated/` mirror would otherwise inflate the count and show "remediated" on a
# scan that remediated nothing. Skipped by PATH SEGMENT, so "ACP-Remediated Reports" is not matched.
SMB_MIRROR_FOLDER = "ACP-Remediated"


def smb_config() -> dict:
    """The SMB connection config, from the environment. Shares are the in-scope UNC roots; the
    credential is a read-only service account (`DOMAIN\\svc-acp`).

    In the UTSW/VNet deployment the password is not an env var — it is a Key Vault secret the worker's
    Managed Identity resolves. `ACP_SMB_CREDENTIAL_KV` names that secret; resolving it is deployment
    wiring (the worker's MI + Key Vault client), left to the caller/runtime rather than done here so
    this module has no cloud dependency. `password` is whichever of the two is present.
    """
    shares = [s.strip() for s in (os.environ.get("ACP_SMB_SHARES") or "").split(",") if s.strip()]
    return {
        "shares": shares,
        "domain": os.environ.get("ACP_SMB_DOMAIN") or None,
        "username": os.environ.get("ACP_SMB_USERNAME") or None,
        "password": os.environ.get("ACP_SMB_PASSWORD") or None,
        "credential_kv": os.environ.get("ACP_SMB_CREDENTIAL_KV") or None,  # Key Vault secret name
    }


def describe_smb_readiness(cfg: dict | None = None) -> dict:
    """A preflight readiness report for the SMB source — CONFIG ONLY, no network touched.

    Answers "can an SMB scan even be attempted?" before one is started, so a health check or the
    Content Sources UI fails with a clear, specific reason rather than starting a scan that returns an
    empty estate. `ready` is True when a share list AND some credential source are configured — either
    a Key Vault secret name (the VNet/Managed-Identity path, preferred) or a username+password
    (dev/test). The actual reachability of the shares is a separate live check the transport does; this
    only catches the misconfiguration that is cheap to catch.
    """
    cfg = cfg or smb_config()
    shares = cfg.get("shares") or []
    has_kv = bool(cfg.get("credential_kv"))
    has_userpass = bool(cfg.get("username") and cfg.get("password"))
    missing: list[str] = []
    if not shares:
        missing.append("shares (ACP_SMB_SHARES)")
    if not (has_kv or has_userpass):
        missing.append("credential (ACP_SMB_CREDENTIAL_KV, or ACP_SMB_USERNAME + ACP_SMB_PASSWORD)")
    return {
        "ready": not missing,
        "shares": shares,
        "share_count": len(shares),
        # Key Vault wins when both are set: the MI path is the one a real deployment uses, and a
        # stray dev password in the env should not silently become the credential of record.
        "credential_source": "key_vault" if has_kv else "userpass" if has_userpass else None,
        "missing": missing,
    }


def _mime_of(name: str) -> str | None:
    """Best-effort MIME from the file name — an SMB directory listing carries no content type, so the
    extension is all we have, exactly as the `local` adapter does."""
    return mimetypes.guess_type(name)[0]


def _size_kb(size) -> int | None:
    try:
        return round(int(size) / 1024) if size is not None else None
    except (TypeError, ValueError):
        return None


def _join_unc(parent: str, name: str) -> str:
    """The UNC path of a child — the file's stable `id`, the SMB analogue of a Drive file id. Uses
    backslashes so the value round-trips as a real UNC (`\\\\server\\share\\dir\\file.docx`)."""
    return parent.rstrip("\\") + "\\" + name


def _file_dict(entry: dict, parent_unc: str) -> dict:
    """Shape one directory entry into the scannable-file dict discovery consumes — the SMB counterpart
    of `_sp_list`'s `rec`. `size`/`modified` come free from the listing (they feed the drill-down's
    biggest-first / recency lenses with no extra round trip); SMB gives no cheap owner, so owner is
    None rather than a wrong value."""
    name = entry["name"]
    return {
        "name": name,
        "path": _join_unc(parent_unc, name),      # UNC id + the download path
        "smb": True,
        "source_mime": _mime_of(name),
        "size_kb": _size_kb(entry.get("size")),
        "source_modified": entry.get("modified"),
        "owner": None,
        "parent_folder": parent_unc,
    }


# ── live SMB transport (deployment-gated; isolated so discovery is testable without it) ────────────
#
# ADR 0036 fills in the live walk/read. The split below is deliberate: everything ACP OWNS — the
# recursion, the parent-path shaping, the mtime→ISO conversion, the size handling — lives in the pure
# `_walk_tree` generator and is unit-tested against a fake `scandir` with no server (see
# test_smb_source). What stays deployment-gated is only the irreducible `smbprotocol` surface: opening
# an authenticated session (Kerberos-first, NTLM fallback — ADR 0036 §1) and the `smbclient.scandir` /
# `smbclient.open_file` calls themselves. Those ~4 lines are validated by the opt-in Samba-container CI
# lane (ADR 0036 "How it is tested"), NOT locally, and are commented as such — never claimed as proven.


def _server_of(unc: str) -> str:
    r"""The server host of a UNC root — `\\fs\dept` → `fs`. `smbclient.register_session` keys sessions
    by server, so the walk registers once per server before scandir'ing that server's shares. Parsed by
    hand rather than via PurePath: POSIX PurePath collapses a leading `\\`→`//` into a special root and
    would return `//` as the first part."""
    return unc.replace("\\", "/").lstrip("/").split("/")[0] if unc else ""


def _iso_mtime(mtime) -> str | None:
    """A POSIX mtime (float epoch seconds, what `smbclient` stat returns) → an ISO-8601 UTC string, so
    an SMB file's `source_modified` matches the shape the Drive/SharePoint paths already emit and feeds
    `store.get_inventory_diff` (#343) unchanged — the generic staleness diff keys on this (ADR 0036 §4).
    None passes through as None (a listing that carried no mtime), never a fabricated timestamp."""
    if mtime is None:
        return None
    try:
        return datetime.fromtimestamp(float(mtime), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _walk_tree(scandir, root: str):
    r"""Recursively yield entries under `root` using a `scandir`-like callable, in the exact shape the
    discovery layer consumes: {name, is_dir, size, modified, path} where `path` is the entry's PARENT
    directory UNC (so `_file_dict`'s `_join_unc(parent, name)` reconstructs the file's own UNC id).

    `scandir(path)` yields objects exposing `.name`, `.is_dir()`, and `.stat()` (with `.st_size` /
    `.st_mtime`) — the `smbclient.scandir` contract, and equally a fake in tests. This is where the
    walk's real logic lives, so it is provable without a server: directory entries are yielded (the
    consumer skips them) and then recursed into; a size is only read for files. `scandir` errors on a
    single directory (a permission-denied subtree) propagate — the caller decides policy — rather than
    being swallowed into a silently short estate.
    """
    for de in scandir(root):
        is_dir = de.is_dir()
        st = de.stat()
        yield {
            "name": de.name,
            "is_dir": is_dir,
            "size": None if is_dir else getattr(st, "st_size", None),
            "modified": _iso_mtime(getattr(st, "st_mtime", None)),
            "path": root,                                   # PARENT dir UNC — the shaping contract
        }
        if is_dir:
            yield from _walk_tree(scandir, _join_unc(root, de.name))


def _register_session(server: str, cfg: dict) -> None:
    """Open an authenticated SMB session to `server` (ADR 0036 §1). DEPLOYMENT-GATED wiring: Kerberos
    is the default (a hospital AD environment, no NTLM-relay exposure — the container carries a krb5
    config + keytab/TGT for the service account), and an explicit username+password (from Key Vault in
    the VNet variant) is the NTLM fallback, used only when configured, never silently. Validated by the
    Samba-container CI lane and a real deploy, not by the local suite."""
    import smbclient
    user, password, domain = cfg.get("username"), cfg.get("password"), cfg.get("domain")
    if user and password:                                   # NTLM fallback (explicit creds)
        smbclient.register_session(
            server, username=f"{domain}\\{user}" if domain else user, password=password)
    else:                                                   # Kerberos default (ambient TGT/keytab)
        smbclient.register_session(server)


def _smbclient_or_raise():
    """Import `smbclient` or fail LOUDLY. The library ships with the worker image, not the default API
    image (ADR 0036 consequences), so its absence means the SMB transport is not provisioned — a scan
    must raise here, never return an empty estate a customer would read as "nothing to remediate"."""
    try:
        import smbclient
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "SMB transport not available: install smbprotocol/smbclient and configure the read-only "
            "service account (ADR 0032/0036). Discovery logic is tested against a mock `_walk`/a fake "
            "scandir; the live session + scandir/open are deployment-gated."
        ) from e
    return smbclient


def _walk(root: str, cfg: dict):
    r"""Yield every entry under an SMB `root`, recursively (see `_walk_tree` for the shape). The ONLY
    SMB-native steps are registering the session and handing `smbclient.scandir` to the pure walker;
    both are deployment-gated and covered by the Samba CI lane, so tests monkeypatch `_walk` (or drive
    `_walk_tree` directly) and run the discovery logic against a mock share."""
    smbclient = _smbclient_or_raise()
    _register_session(_server_of(root), cfg)                # gated: real auth, CI-validated
    yield from _walk_tree(smbclient.scandir, root)          # gated seam: smbclient.scandir


def _read(path: str, cfg: dict) -> bytes:
    r"""Read one file's bytes for assessment/remediation. Registers the session (same gated auth as
    `_walk`) and reads through `smbclient.open_file` — a read-only open, no write-back to the share
    (ADR 0036 §5). Deployment-gated; fails loudly when the library is absent."""
    smbclient = _smbclient_or_raise()
    _register_session(_server_of(path), cfg)
    with smbclient.open_file(path, mode="rb") as fh:        # gated seam: smbclient.open_file
        return fh.read()


# ── discovery (real, testable) ─────────────────────────────────────────────────────────────────
def list_smb(root: str, *, max_files: int = 2000, cfg: dict | None = None,
             scope_out: dict | None = None, inventory_out: list | None = None) -> list[dict]:
    """List scannable files under an SMB `root`, with the whole-estate inventory on the side.

    The RETURN value is the scannable analysis set (the six supported extensions) — unchanged shape,
    so search/assess scope is exactly the other sources'. `scope_out["inventory"]` gets the same
    three-denominator estate summary `_search_drive`/`_sp_list` build (discovered / by_status /
    truncated), so a SMB scan's coverage dashboard is populated. `inventory_out`, when given, collects
    a row for every NON-scannable file so Discover reports the whole estate while Assess only opens
    supported types. `truncated` is honest: True only when the cap stopped the walk with items still
    unlisted, never merely because the analysis set equalled the cap.
    """
    cfg = cfg or smb_config()
    files: list[dict] = []
    est_files: list[dict] = []           # every file (scannable or not) → the estate classifier
    hit_cap = _walk_root_into(root, cfg, files=files, est_files=est_files,
                              max_files=max_files, inventory_out=inventory_out)
    if scope_out is not None:
        scope_out["inventory"] = estate_inventory.summarize(est_files, truncated=hit_cap)
    return files


def _walk_root_into(root: str, cfg: dict, *, files: list, est_files: list,
                    max_files: int, inventory_out: list | None) -> bool:
    """Walk ONE share root, appending scannable files to `files` and an estate row for EVERY file to
    `est_files`. Both lists are passed in so a multi-share walk accumulates one combined estate.
    Returns True when the scannable cap stopped this walk with items still unlisted (truncation)."""
    for entry in _walk(root, cfg):
        if entry.get("is_dir"):
            continue
        parent = entry.get("path") or root
        # Skip ACP's own remediation mirror by path segment (see SMB_MIRROR_FOLDER).
        segments = PurePath(parent.replace("\\", "/")).parts
        if SMB_MIRROR_FOLDER in segments:
            continue
        name = entry["name"]
        scannable = PurePath(name).suffix.lower() in _SCANNABLE_EXTS
        # Cap check BEFORE counting this file anywhere: a scannable file past the cap is the floor
        # boundary — stop, and do not count it, so `discovered` matches exactly what was listed and
        # `truncated` truthfully says there is more.
        if scannable and len(files) >= max_files:
            return True
        # size + modifiedTime come free from the directory listing, so the estate drill-down's
        # biggest-first and recency lenses work for SMB exactly as they do for Drive/SharePoint
        # (estate_inventory._sample_meta reads these keys). owner and shared are NOT cheap on SMB —
        # they need per-file Windows ACL reads — so they are honestly left absent (owner None,
        # shared False) rather than a wrong value; a later ACL pass can add them.
        est_files.append({"id": _join_unc(parent, name), "name": name, "mimeType": _mime_of(name),
                          "size": entry.get("size"), "modifiedTime": entry.get("modified")})
        if scannable:
            files.append(_file_dict(entry, parent))
        elif inventory_out is not None:
            inventory_out.append(_file_dict(entry, parent))
    return False


def list_smb_estate(roots: list[str], *, max_files: int = 2000, cfg: dict | None = None,
                    scope_out: dict | None = None, inventory_out: list | None = None) -> list[dict]:
    """List the whole SMB estate across EVERY in-scope share, presented as one.

    A hospital estate spans several shares (UTSW: up to ~10). Walking only the first would report an
    estate smaller than it is — the same failure the SharePoint multi-library walk guards against. So
    every root is walked into one combined analysis set + one estate summary. The cap is GLOBAL across
    shares (it bounds the whole scan, not each share), and truncation is honest: True only when the cap
    stopped a walk with items unlisted — which also means later shares were never reached, so the
    estate is a floor. Roots are walked in order; a bare/empty `roots` yields an empty estate.
    """
    cfg = cfg or smb_config()
    files: list[dict] = []
    est_files: list[dict] = []
    truncated = False
    for root in roots:
        if _walk_root_into(root, cfg, files=files, est_files=est_files,
                           max_files=max_files, inventory_out=inventory_out):
            truncated = True        # cap hit mid-share → this share has more AND later shares unreached
            break
    if scope_out is not None:
        scope_out["inventory"] = estate_inventory.summarize(est_files, truncated=truncated)
    return files


def fetch_smb(path: str, cfg: dict | None = None) -> bytes:
    """Read one file for assessment/remediation. Thin pass-through to the gated transport."""
    return _read(path, cfg or smb_config())
