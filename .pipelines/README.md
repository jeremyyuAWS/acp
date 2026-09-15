# ACP in Azure Pipelines

The source repository is `AI-Foundry/acp` in `MovateAI-Foundry`.

- **acp-ci (10)** uses `/azure-pipelines.yml`: four backend shards, PostgreSQL
  integration, frontend tests/build and advisory browser tests. A main-branch build
  validation policy is required for Azure PRs; `pr: none` does not replace that policy.
- **acp-deploy (22)** uses `/.pipelines/deploy.yml`. A successful main CI run supplies
  the exact commit and build ID. `check_azure_ci.py` verifies the build result, source
  branch, repository and definition before the existing redeploy script can mutate Azure.
- `verifyOnly: true` checks the service connection and resource visibility without
  changing an image. Normal deployment goes through staging before production.
- Service connection **acp-azure-deploy** uses workload identity federation with the
  existing `acp-gh-deploy` app. No client secret or GitHub token is used.
- Environments **acp-staging** and **acp-production** have exclusive-lock checks and
  sequential lock behavior. An older CI completion cannot roll back newer main.
- All four tier names are explicit for staging and production. Existing resource
  configuration and secrets are retained by `deploy/public/redeploy.sh`.

## Cutover

Validate the migration PR and the read-only deployment check. Merge only on green,
then verify a main CI build and the corresponding Azure deployment. Only after those
checks should GitHub's CI, deploy and deploy-staging workflows be disabled. Keep the
workflow files for rollback. Other scheduled diagnostics/monitoring are separate from
this build/deploy migration.

The local `origin` remains GitHub for existing concurrent sessions; `azure` is the
Azure remote. New development should use a fresh Azure clone or explicitly push the
feature branch to `azure`. A GitHub merge does not synchronize into Azure automatically.
