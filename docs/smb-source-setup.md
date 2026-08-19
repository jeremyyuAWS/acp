# Network-drive (SMB) source — setup & implementation status

Implements ADR 0032 (network-drive connector), UTSW VNet variant. A network drive is *a new adapter,
not a new pipeline*: `api/smb_source.py` lists the same file dicts discovery already consumes and
builds the same three-denominator estate inventory, and `scanner._list` gains one `source == "smb"`
branch. Everything downstream (inventory, capability matrix, remediation appliers) is unchanged.

## What ACP needs from customer IT (the critical path)

Per the UTSW variant, ACP's worker runs **inside the customer's own Azure VNet** and reaches on-prem
shares over the customer's private route — PHI never leaves the customer's control boundary. The four
prerequisites are the customer's to deliver and are the real gate for a pilot date:

1. **A read-only SMB service account** (`DOMAIN\svc-acp`) with NTFS *read* on the in-scope shares.
   ACP never gets write on source shares; remediated copies go to Blob, not back over the original.
2. **The in-scope share list** (UNC roots, up to ~10 for the pilot), e.g. `\\fileserver\dept`,
   `\\nas\phi`.
3. **A private network route** (VPN / ExpressRoute) from the VNet-integrated worker to the file
   servers, with SMB permitted by policy — **no public-internet path, no inbound hole**.
4. **The service-account credential in Azure Key Vault**, read by the worker's **Managed Identity**
   (the MI is *not* the SMB identity — the SMB service account is separate).

## Configuration (worker environment)

| Variable | Meaning |
|---|---|
| `ACP_SMB_SHARES` | Comma-separated in-scope UNC roots (`\\fs\dept,\\nas\phi`). |
| `ACP_SMB_DOMAIN` | AD domain for the service account. |
| `ACP_SMB_USERNAME` | Service-account name (`svc-acp`). |
| `ACP_SMB_CREDENTIAL_KV` | Key Vault secret name holding the password; resolved by the worker's Managed Identity. Preferred over `ACP_SMB_PASSWORD` in the VNet deployment. |
| `ACP_SMB_PASSWORD` | Direct password — dev/test only; use the Key Vault path in any real deployment. |

## Implementation status

**Done and tested (this scaffolding):**
- The adapter `smb_source.list_smb` — walks a share, shapes the scannable analysis set, builds
  `scope_out["inventory"]` (discovered / by_status / truncated) at parity with Drive/SharePoint,
  routes non-scannable files to the inventory, skips folders and ACP's own `ACP-Remediated` mirror,
  and reports an honest truncation floor at the fan-out cap.
- Dispatch: `scanner._list("smb", folder=<share root>, …)`.
- `smb_config()` reads the environment above.
- Tests (`tests/test_smb_source.py`) drive all of the above against a mock share, and assert the
  **un-mocked transport fails loudly** rather than silently returning an empty estate.

**Deployment-gated / remaining for Phase-1 MVP** (deliberately not in this PR):
- **Live SMB transport** — the real `smbprotocol`/`smbclient` walk and read in `smb_source._walk` /
  `_read` (currently raise a clear error). Add `smbprotocol` to `api/requirements.txt` with the
  worker image, and implement the recursive SMB2/3 walk (NTLM/Kerberos).
- **Key Vault credential resolution** via the worker Managed Identity.
- **Staging + Blob output** — stage a working copy for assess/remediate; write remediated copies to
  Blob (no write-back to source).
- **Scan trigger + UI** — let a scan be started with `source="smb"` and a chosen share (a route +
  Content Sources affordance).
- **Scale + incremental** — large-share fan-out cap validation, and incremental re-scan via SMB
  `modifiedTime` (the same source-staleness signal the Drive path already captures).

## Open questions carried from ADR 0032

Kerberos vs NTLM and DFS-namespace resolution across multi-server shares; whether the assess pass
runs edge-side (PHI stays on the LAN) or central; the incremental re-scan cadence.
