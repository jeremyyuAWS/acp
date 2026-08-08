# Self-hosted Azure Pipelines agent

Runs `azure-pipelines.yml` on this machine instead of a Microsoft-hosted VM.

**Why.** MovateAI-Foundry has **one** hosted parallel job across all of its pipelines, so
acp's PRs queue behind every other project's builds — observed 2026-08-08, PR #182's run sat
in `notStarted` for the duration of an unrelated run on `main`. Azure DevOps grants one
**self-hosted parallel job free, with unlimited minutes**, so this is a second lane nothing
else contends for. It is also warmer: a hosted agent re-downloads the .NET SDK, Node and
every npm/pip package on a clean VM each run, while this one keeps `_work/` on a volume.

## What you do (the parts that need your credentials)

These are yours because they involve minting and pasting a token. Nothing here should be
committed, and nothing here should be handed to an assistant.

**1. Create the pool.** Azure DevOps → Organization settings → **Agent pools** → *Add pool*
→ type **Self-hosted**, name **`acp-local`**. Tick *Grant access permission to all
pipelines* (or add the `AI-Foundry` project explicitly afterwards).

**2. Mint a PAT.** User settings → **Personal access tokens** → *New Token*.

| field | value |
|---|---|
| Organization | `MovateAI-Foundry` |
| Scopes | **Agent Pools → Read & manage** |
| Expiration | as short as you can live with |

Agent Pools is the *only* scope needed — an agent does not read code with this token, it
gets the source through the pipeline's own job token. A broader PAT buys nothing and costs
you if it leaks.

> If the container exits with *"Could not resolve an agent package"*, the token is
> almost certainly under-scoped rather than invalid. That endpoint answers `200` with an
> empty list when the scope is missing, so it reads like an unsupported platform.

**3. Put it in `.env`,** in `deploy/compose/` — which is gitignored:

```
AZP_URL=https://dev.azure.com/MovateAI-Foundry
AZP_TOKEN=<the token you just minted>
```

## Then

```bash
docker compose --profile ci up -d --build azp-agent
```

The agent registers, takes one job, and exits; compose restarts it. Confirm it is online
under Agent pools → `acp-local` → **Agents**.

Once it shows online, switch the pipeline over — `azure-pipelines.yml` carries the exact
two-line change in a comment at `pool:`. Do it in that order: a pool with no online agent
leaves runs queued indefinitely rather than failing, so CI looks slow instead of broken.

## Notes worth having before you debug something

- **`UsePythonVersion@0` installs nothing.** Unlike `UseDotNet@2` and `UseNode@1`, it only
  selects an interpreter already in the agent's tool cache. Hosted images ship that cache
  pre-baked; a fresh self-hosted agent has none, and `Python 3.12` — the pipeline's first
  step — goes red with an error that reads like a missing *version*. The Dockerfile stages
  3.12 into the cache for exactly this reason, marker file and all.
- **No Docker socket is mounted, deliberately.** The pipeline builds no images locally
  (`az acr build` runs server-side in Azure), so the agent has no need of the host daemon —
  and not mounting it means a change to a pipeline file cannot acquire root on your laptop.
- **The agent is one laptop.** When it is closed or away, runs queue. The fallback is to put
  the two hosted-pool lines back; they are kept in the comment for that reason.
- **Ollama is not part of this.** Containers on macOS get no GPU — Docker's Linux VM has no
  Metal passthrough, so a containerised Ollama runs CPU-only on Apple Silicon. Run Ollama
  natively and point `OLLAMA_BASE_URL` at `http://host.docker.internal:11434`.
