# ADR 0032 — Network-drive (SMB/CIFS) support via an on-prem connector

Status: Proposed
Date: 2026-08-18

Prompted by the UTSW pilot: a hospital's content estate is not only Google Drive and
SharePoint. A large share of it lives on **on-prem network drives** — Windows/NAS SMB (CIFS)
file shares mapped as `H:\`, `\\fileserver\dept`, etc. — and much of it is PHI. To assess and
remediate that estate, ACP needs a network-drive source. This ADR decides *how*, with the
constraint that PHI must not leave the hospital perimeter merely to be discovered.

## Context

### The source layer is already an abstraction

`scanner._list(source, svc, …)` (api/scanner.py) dispatches on a `kind`: today `drive`,
`sharepoint`, `folder`, `local`, `demo`. Each adapter does two things — **list** the tree into the
file dicts discovery consumes (`{id/path, name, mimeType, size, modifiedTime, …}`, fed straight to
`estate_inventory.summarize`), and **fetch** a file's bytes for assessment/remediation. Everything
downstream — the three-denominator inventory (ADR: discovery/assessment/remediation), the capability
matrix, the remediation appliers — is source-agnostic. A network drive is therefore **a new adapter,
not a new pipeline**. This ADR is almost entirely about the *adapter and its deployment*, not about
scanning.

### Why the deployment topology is the hard part

SMB (TCP/445) is a LAN protocol with a large attack surface; hospitals do not expose it to the WAN,
and Azure reaching *into* the hospital LAN inverts the trust boundary a PHI estate is built on. The
question "read the share" is easy; "read the share without punching an inbound hole or copying PHI to
a place the customer didn't authorize" is the decision.

## Decision

**Add a `kind: "smb"` source, ingested by a lightweight ACP connector that runs *inside* the
customer network and talks to ACP over an outbound-only HTTPS channel.** PHI stays in the perimeter
until a file is explicitly pulled for assessment; nothing inbound is opened.

### Topology

```
        HOSPITAL NETWORK  (trust perimeter — PHI stays inside)         │        AZURE  ·  ACP
   ────────────────────────────────────────────────────────────────── │ ──────────────────────────────
                                                                        │
    ┌──────────────────┐                                                │
    │  SMB / CIFS       │        ┌────────────────────────────────┐     │     ┌────────────────────────┐
    │  file server / NAS│  read  │        ACP CONNECTOR            │     │     │   ACP control plane    │
    │  \\fileserver\dept│──────▶ │   (worker image + SMB adapter)  │     │     │       (acp-app)        │
    │  \\nas\phi  ·  H:\ │  only  │                                │  out-│     │                        │
    └──────────────────┘        │  1  walk share → classify every │  bound    │  • dispatch scan jobs  │
              ▲                  │     file (3-denominator invy)   │  HTTPS ═════▶  • receive results     │
              │ svc-acp          │  2  assess / remediate locally  │  :443│     │                        │
              │ (read-only NTFS) │  3  write fixes ──────┐         │     │     └───────────┬────────────┘
              │                  └───────────────────────┼─────────┘     │                 │
    ┌─────────┴──────────┐                               ▼               │     ┌───────────▼────────────┐
    │ \\...\ACP-Remediated│ ◀──── fixed files (never over the original)   │     │  acp-worker + Azure T4 │
    │  (new path)         │                                               │     │  vision  (findings)    │
    └────────────────────┘                                               │     └────────────────────────┘
                                                                         │
    ══════════ FIREWALL: OUTBOUND 443 ONLY ═══════════════════════════════   (no inbound rule · no SMB/445 over WAN)
```

Three properties this buys: (1) PHI never leaves the perimeter to be *discovered* — only findings/
coverage (and, if allowed, remediated bytes) egress; (2) outbound-only — no inbound hole, no SMB over
the WAN; (3) read-only + non-destructive — `svc-acp` reads, and fixes land in a new path.

### The adapter interface (mirrors the existing sources)

A network-drive source is defined by:

- **`list(root, *, max_files, scope_out) -> list[dict]`** — walk the SMB tree (via `smbprotocol`,
  which speaks SMB2/3 with NTLM/Kerberos) and yield the same file dicts discovery already consumes.
  `id` becomes the UNC path (`\\server\share\dir\file.docx`); `size`/`modifiedTime` come free from
  the directory listing (they feed the #304 triage metadata with no extra call). Folders are skipped,
  exactly as Drive folders are.
- **`fetch(path) -> bytes`** — read one file for assessment/remediation.
- **`write_back(path, bytes)`** — see the write-back policy below.

This is the same two-method shape as the Drive and SharePoint adapters; `_list` gains one more
`elif kind == "smb"` branch and the rest of `scanner.py` is untouched.

### Deployment: the connector, not a direct mount

The connector is the **existing worker image plus the SMB adapter**, run as a container (or Windows
service) on a host inside the hospital network. It:

- holds the **read-only** credentials locally (a domain service account, `DOMAIN\svc-acp`, with NTFS
  *read* on the in-scope shares) — credentials never reach Azure;
- opens an **outbound** HTTPS connection to the ACP control plane, receives scan jobs, does discovery
  and (optionally) assessment/remediation locally, and streams **results** (findings, coverage,
  remediated bytes) back out;
- requires **no inbound firewall rule** and **no SMB-over-WAN**.

### Write-back policy: a separate path, never overwrite

Remediation writes the fixed file to a **distinct `/<share>/ACP-Remediated/…` location**, not over
the original. Hospitals rarely grant write on source shares, originals must be preserved for audit,
and this keeps the service account's write scope to a single, reviewable directory. This mirrors the
"documents never retained / originals preserved" posture the product already advertises.

## Alternatives considered

- **Direct SMB mount from the Azure worker over site-to-site VPN / ExpressRoute.** Simplest code
  (mount `//server/share`, reuse the `local` adapter almost verbatim). **Rejected as the default:**
  it carries PHI across the WAN into Azure for *every* discovered file, needs SMB/445 over the tunnel
  (a security-review hurdle), and couples ACP availability to the tunnel. Kept as an *option* for
  customers who already run such a tunnel and accept the data-egress posture.
- **Azure File Sync bridge** — the customer syncs the share into Azure Files with Microsoft's File
  Sync agent; ACP reads Azure Files via the existing `local`/SMB path. **Rejected as the default:**
  it duplicates the entire estate into Azure (cost + a second copy of PHI to govern) and adds a sync
  dependency ACP doesn't control. Reasonable where a customer *already* uses Azure File Sync.

The connector wins because it is the only option where PHI does not traverse the WAN or land in a
second store just to be *discovered*, and it needs no change to the customer's inbound firewall.

## Amendment (2026-08-18) — UTSW pilot selects a VNet-integrated variant

UTSW's architecture review chose a topology this ADR listed as an *alternative*, but in a form that
resolves the objection that alternative carried. Rather than ACP's outbound connector, or a direct
mount over VPN into *our* Azure, the pilot runs the **ACP worker inside UTSW's own Azure
subscription**, VNet-integrated, reaching on-prem file servers over **UTSW's VPN/ExpressRoute private
hybrid route** (SMB allowed by UTSW policy; no public internet path). Because the worker and all
processing live in **UTSW's** cloud, PHI never leaves UTSW's control boundary — which is exactly the
property the on-prem connector was chosen to protect, achieved a different way.

Concretely (per UTSW's diagram):

- **Worker in UTSW subscription**, VNet-integrated Container Apps env; read-only SMB session to the
  on-prem shares (up to ~10), enumerate → stage a working copy → assess/remediate.
- **SMB credential in Azure Key Vault**, accessed via a **Managed Identity** — and the MI is *not*
  the SMB identity; the SMB read-only service account is separate (UTSW-issued).
- **Evidence/decisions → PostgreSQL; remediated copies → Azure Blob.** No write-back to source shares.
- **UTSW controls the connection** end to end: selects shares, grants read, controls the network
  route, and can revoke access.

**What this changes for effort:** it *removes* the connector-packaging line item — the biggest cost
in the Phase-1 LOE — because there is no agent to build, enroll, or ship; the existing worker image
deploys into UTSW's env. The ACP-side work reduces to the `kind: "smb"` adapter + staging + Key
Vault/Managed-Identity wiring + Blob output + deploy/test. **Estimate for this variant: ~1–1.5
engineer-weeks**, gated entirely on UTSW's prerequisites being live: the VNet-integrated environment,
the VPN/ExpressRoute route with SMB permitted, firewall+DNS validation, and the read-only SMB service
account. Those four are UTSW's to deliver and are the real critical path for a next-week target.

## Consequences

- **New artifact to build and ship:** the connector (packaging, an enrollment/pairing flow for the
  outbound channel, auto-update). This is the bulk of the work; the scanner-side adapter is small.
- **Identity model gains a service account** (`DOMAIN\svc-acp`, read-only), documented for the
  customer's IT the way the SharePoint app-registration already is (see the SharePoint read-only
  scopes doc).
- **Discovery honesty holds unchanged:** the whole share is inventoried by format and capability
  status; unsupported files are counted, never passed; the truncation floor still applies when a
  very large share hits the fan-out cap.
- **Assessment/remediation can run *at the edge*** (inside the connector) or *central* (stream bytes
  out). Edge-first keeps PHI local for the assessment pass and only emits findings; this is the
  preferred default and worth its own follow-up once the connector exists.

## Open questions (for the implementation ADR/PR, not decided here)

- Kerberos vs NTLM and DFS-namespace resolution across multi-server shares.
- Enrollment/trust for the outbound channel (mTLS client cert vs a short-lived enrollment token).
- Whether assessment runs edge-side or central by default (the PHI-locality vs. central-GPU tradeoff
  — note ADR 0032 does not commit either way).
- Incremental re-scan using SMB `modifiedTime` (the same source-staleness signal the Drive path
  already captures).

## Effort estimate (LOE)

Rough order-of-magnitude, in engineer-weeks for one experienced engineer. It assumes the existing
worker image and discovery→assess→remediate pipeline are reused (they are source-agnostic today), so
the estimate is dominated by the connector packaging and the outbound channel — the parts that are
genuinely new, not the scanning.

**Phase 1 — pilot-ready MVP** (central assessment, read-only + separate-path write-back, one auth path):

| Component | Scope | LOE |
|---|---|---|
| SMB source adapter | `list`/`fetch`/`write_back` via `smbprotocol`; wire into `_list`; unit tests against a mock share | ~1 wk |
| Connector agent | worker image as an on-prem container/service; outbound enrollment + job-pull/result-push channel; local config (shares, creds, scope) | ~3 wk |
| Identity & IT enablement | read-only service account, NTLM/Kerberos auth, basic DFS; customer IT setup doc (mirrors the SharePoint app-reg doc) | ~1 wk |
| Write-back + scoping | `/ACP-Remediated` path, permission handling, in-scope share selection | ~0.5 wk |
| Integration + scale test | real SMB share, large-share fan-out cap, incremental re-scan via `modifiedTime` | ~1 wk |
| Security-review support | threat model, outbound-channel review, customer infosec Q&A | ~1 wk (+ customer-side time) |

**Phase 1 subtotal: ~7.5 engineer-weeks** — roughly **one engineer for ~2 months, or two for ~1 month**.

**Phase 2 — production hardening** (add when moving past pilot):

| Component | LOE |
|---|---|
| Edge-side assessment (PHI never leaves the LAN for the assess pass; only findings egress) | ~2 wk |
| DFS namespaces, multi-domain, connector auto-update | ~1.5 wk |
| HA / monitoring / packaging polish | ~1 wk |

**Phase 2 subtotal: ~4.5 engineer-weeks.**

**Totals: ~7.5 wk to a pilot-ready MVP; ~12 wk to production-hardened.**

Caveats that move the number: (1) the connector's outbound channel is the least-reused piece and the
biggest single risk to the estimate; (2) the security review timeline is partly the customer's, not
ours; (3) edge-side assessment (Phase 2) interacts with the GPU-lane decision (where the vision model
runs) — if assessment must stay in-perimeter, the connector needs local inference, which is a larger
lift not costed above.

## Status / next step

Proposed. The scanner-side `kind: "smb"` adapter is a small, self-contained follow-up; the connector
packaging is the real project and should be scoped as its own implementation ADR once this direction
is accepted.
