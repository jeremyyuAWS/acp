# ACP Lite — separate Container App infra

A cut-down build of ACP with Discover, Assess and Remediate as three separate stages, deployed as
its own Azure Container App beside `acp-app`.

```
bash deploy/lite/deploy.sh                         # acp-lite          (prod-like)
ACP_LITE_ENV=staging bash deploy/lite/deploy.sh    # acp-lite-staging
```

## What it is

One self-contained HTML page served by nginx. No backend, no database, no Redis, no worker tier,
no engines, no secrets. The estate it shows is generated in the page; it never contacts a Drive
or SharePoint tenant, and the Google/Microsoft buttons on the sign-in screen stand in for the
real SSO rather than performing it.

It exists to demonstrate three things the redesign turns on, in a form that can be opened and
argued with:

- **Stage separation.** Discover lists metadata only and hands a selection to Assess; Assess
  produces findings; Remediate acts on them. Each stage is entered deliberately.
- **The four-format scope.** PDF, DOCX, XLSX, PPTX. Files outside it are still inventoried and
  counted — `unsupported` never reads as `passed` — but never queued.
- **Lifecycle rules that state their scope.** A rule preview reports its whole-estate count and
  its in-folder count, both labelled. The live demo's "66 matching files on a 5-file folder" was
  a correct whole-estate number read as a folder one.

## Why separate infra rather than a route on `acp-app`

`acp-app` is the control plane: FastAPI, Postgres, Redis, the .NET Office CLI, the PDF analyser,
a worker tier. Adding a prototype page to it means every Lite change redeploys that image and
restarts running scans. A separate container app shares the resource group, registry and Container
Apps *environment* — network and Log Analytics — and nothing else: its own image, revisions,
scaling and URL.

It also scales to zero (`--min-replicas 0`), which is safe here precisely because there is no
state to lose on a cold start. The control plane cannot do that.

## Files

| File | Purpose |
|---|---|
| `index.html` | the app — one document, inline CSS/JS, Google Fonts the only external reference |
| `Dockerfile` | `nginx:1.27-alpine` via `mirror.gcr.io`, listening on 8080 |
| `nginx.conf` | static serving, `/healthz`, CSP + `noindex`, `no-store` |
| `deploy.sh` | ACR build + `containerapp create/update`, then verifies `/healthz` |

## Verification status — read this before trusting the deploy

Verified in the sandbox this was written in:

- `index.html` is a complete standalone document (doctype through `</html>`), and serving it over
  HTTP returns it byte-identical.
- Its only external references are the two Google Fonts hosts the CSP admits.
- `deploy.sh` passes `bash -n`.

**Not verified — no Azure CLI, no Azure credentials, and no Docker daemon were available:**

- The image has never been built. `docker build` could not run.
- `nginx.conf` has never been parsed by nginx (`nginx -t`).
- No `az` command in `deploy.sh` has been executed against a real subscription.

So the first run of `deploy.sh` is the first time any of it executes. Run it against **staging
first** (`ACP_LITE_ENV=staging`) and read the output; the script fails loudly rather than
silently if `/healthz` does not come back 200. If the image build fails, it will fail at step
1/3 before anything is deployed.

## Pointing it at the real backend

This build talks to nothing — `connect-src 'none'` in `nginx.conf` enforces that, and the estate
is generated in the page. Sharing `acp-app`'s backend is possible and is the obvious next step,
but it is real work rather than a config flag, so it is written down here rather than half-wired:

1. **CORS on `acp-app`.** The Lite container gets its own FQDN, so every call is cross-origin.
   `api/app.py`'s CORS middleware has to admit that origin — one entry, but a deliberate one:
   it widens who may call the control plane with a user's token.
2. **Auth.** The sign-in screen currently mirrors prod's *appearance*. Real sign-in means the GIS
   and MSAL clients (`frontend/src/googleIdentity.js`, `msalClient.js`) and the resulting
   `X-Drive-Token` / `X-Sp-Token` headers on every request. The Google client id must list the
   new origin as an authorised JavaScript origin, which is a Google Cloud console change.
3. **Endpoints.** Discover is `POST /scans?source=…&queue=true` plus the SSE stream at
   `GET /scans/{id}/discover/stream`; Assess is `POST /scans/{id}/assess`; the document list is
   `GET /scans/{id}`. Lifecycle rules are `/disposition/policies` — note that its preview is
   **owner-scoped, not folder-scoped**, which is why this build shows two labelled counts.
4. **Relax the CSP.** `connect-src 'none'` becomes `connect-src https://<acp-app-fqdn>`. Leaving
   it at `'none'` will make every call fail silently in the console, which is a confusing hour.

Until then, keeping the two apart has a real benefit worth stating: this page cannot read, write
or scan a customer's documents, because it has no way to reach anything that could.

## Prerequisites the script does not create

- An existing resource group and ACR (defaults `mdk-accessibility` / `mdkaccessibilityacr`,
  matching `deploy/public/deploy.sh`).
- An existing Container Apps environment in that resource group. The script picks the first one
  it finds; set `ACP_ACA_ENV` to pin it.
- ACR admin credentials enabled — the script reads them with `az acr credential show`, the same
  way `deploy/public/deploy.sh` does.
