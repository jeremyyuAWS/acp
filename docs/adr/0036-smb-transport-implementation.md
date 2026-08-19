# ADR 0036 — SMB transport implementation (the live walk/read, and how it is tested)

**Status:** Proposed. Implementation ADR for ADR 0032; resolves the four open questions ADR 0032
deferred. Depends on nothing merged here — the adapter shape (`api/smb_source.py`) and the
`scanner._list("smb", …)` dispatch already exist (#386); this decides how the deployment-gated
transport is built and verified.
**Date:** 2026-08-18
**Related:** ADR 0032 (the connector decision + UTSW VNet variant), `api/smb_source.py`,
`docs/smb-source-setup.md`.

## Context

`smb_source.list_smb` / `fetch_smb` already shape discovery and dispatch; the live SMB I/O is
isolated behind `_walk` / `_read`, which currently raise a clear error rather than fake an estate.
This ADR fills those two functions in, and answers the questions ADR 0032 explicitly left open:
Kerberos vs NTLM, DFS namespaces, edge-vs-central assessment, and incremental re-scan.

## Decision

### 1. Library and protocol — `smbprotocol` / `smbclient`, SMB 3.x, Kerberos-first

Use `smbprotocol`'s high-level `smbclient` API (SMB 2/3, pure-Python, no kernel mount, so it runs in
a container without `CAP_SYS_ADMIN`). **Kerberos is the default auth**, NTLM the fallback:

- Kerberos is what a hospital AD environment expects, avoids NTLM-relay exposure, and is required
  where the customer has disabled NTLM. It needs the container to have a krb5 config pointed at the
  domain KDC and a keytab or a TGT for `DOMAIN\svc-acp` — deployment wiring, documented in
  `smb-source-setup.md`.
- NTLM (username+password from Key Vault) stays as the fallback for shares/customers where Kerberos
  is not available, behind config, never silently.

`_walk` opens a session per share root with `smbclient.register_session(server, username, password
_or_ krb5)`, then walks with `smbclient.scandir` (which returns name / is_dir / stat in one call —
size and modified time come free, feeding the estate metadata with no extra round trip), recursing
into directories. `_read` is `smbclient.open_file(path, mode="rb").read()`.

### 2. DFS namespaces — resolve, then treat as a normal share

A `\\domain\dfsroot\link` path is a namespace that redirects to a real server share. `smbprotocol`
follows DFS referrals transparently for open/read; for the WALK we resolve the namespace root to its
target(s) once at session setup (a DFS referral request) and walk the resolved target, so a
multi-server DFS namespace is enumerated correctly rather than stopping at the reparse point. A
namespace that fans out to multiple targets is walked as multiple roots, deduplicated by resolved
UNC (the same identity-dedup rule the SharePoint multi-library walk uses).

### 3. Assessment locality — central for the pilot, edge as Phase 2

ADR 0032 did not commit. **Decision: central for the pilot** — the VNet-integrated worker stages a
working copy (per the UTSW variant), assesses/remediates it in the worker, writes evidence to
Postgres and remediated copies to Blob. This reuses the existing pipeline unchanged and keeps the
pilot's moving parts minimal. **PHI locality is still honoured** because, in the UTSW variant, the
worker *is* inside UTSW's subscription — "central" here is UTSW-central, not ACP-central; nothing
crosses UTSW's boundary. Edge-side assessment (assess in the connector, emit only findings) stays
Phase 2 and is only meaningful in the outbound-connector topology, where the worker is not already in
the customer's cloud.

### 4. Incremental re-scan — the EXISTING generic diff, keyed on `modifiedTime`

No SMB-specific diff. `scandir`'s `st_mtime` is written to `scan_inventory.source_modified` exactly
as the Drive path already does, so `store.get_inventory_diff` (#343) computes new/changed/removed
across two SMB scans of the same root with no new code. A file is "changed" when its `modifiedTime`
moved; the per-source baseline (`previous_run_for_source`) already scopes the comparison. This is why
the adapter carries `source_modified` from day one (see `smb_source._file_dict`).

### 5. Staging and write-back — stage to a temp dir, output to Blob, never over the original

The worker stages each in-scope file to a local temp path for the assess/remediate pass (the same
`cache_source_bytes` staging the other sources use), and remediated copies land in **Blob**, keyed by
scan — **no write-back to the source share** in the pilot (the UTSW variant grants read-only). The
`ACP-Remediated` mirror-skip in the adapter is therefore belt-and-braces for the outbound-connector
topology (where write-back to a share path is an option); in the VNet variant nothing is written to
the share at all.

## How it is tested (the part that makes this shippable)

The discovery logic is already unit-tested against a mock `_walk` (#386). The LIVE transport is
verified two ways, neither of which needs the customer:

- **Containerised Samba in CI** — a `samba`/`dperson/samba` service container in the backend job
  exposes a fixture share; an integration test (marked `@pytest.mark.smb`, opt-in so the default
  suite stays fast) runs the real `smbclient` walk/read against it and asserts the same file dicts +
  inventory the mock test asserts. This is the gate that proves `_walk`/`_read` actually speak the
  protocol, without a hospital.
- **A staging dry-run** against a local directory tree, to exercise the stage→assess→Blob path with
  no SMB at all.

Only after both are green does the connector touch a real customer share — and even then, read-only.

## Consequences

- `api/requirements.txt` (worker image) gains `smbprotocol`; the container gains a krb5 config for
  the Kerberos path. Neither is in the default API image — the SMB transport ships with the worker.
- `smb_source._walk` / `_read` get real bodies; the clear-error guards stay as the fallback when the
  library is absent, so a mis-provisioned deploy still fails loudly.
- CI gains an opt-in `smb` integration lane (a Samba service container). The default suite is
  unchanged.
- No change to the source-agnostic pipeline, the inventory, or the capability matrix.

## Effort estimate

Within ADR 0032's Phase-1 "SMB source adapter ~1 wk" line, now itemised: `_walk`/`_read` bodies +
DFS referral (~2 d), Kerberos/NTLM + Key Vault credential resolution via Managed Identity (~1.5 d),
the Samba-container CI integration test (~1 d), staging→Blob wiring reuse (~0.5 d). Gated on the four
customer-IT prerequisites in `smb-source-setup.md`.

## Status / next step

Proposed. The next code PR should add the Samba-container CI lane and the integration test FIRST (red
against the still-empty `_walk`), then fill `_walk`/`_read` to green — fixture before fix, so the
live transport is proven the day it is written, not the day a hospital first runs it.
