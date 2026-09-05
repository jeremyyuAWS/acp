# PRD: ACP Portable Deployment and Packaging

> Owner-provided product requirements, recorded here so that the packaging contract, ADR 0048 and
> the semantic rules in `packaging/cli/acpctl/spec.py` can cite the requirement they implement.
> Section numbers referenced from code and tests (`PRD S11`, `PRD S13`, …) are the ones below.
>
> Implementation status is tracked in ADR 0048 and in `packaging/docs/service-inventory.md`, not
> here. Phase 0 and the §23 first slice have shipped; nothing else has.

## 1. Product Summary

Create a supported packaging system that allows ACP to be deployed consistently to Microsoft
Azure, Amazon Web Services, Google Cloud Platform, customer-managed Kubernetes, on-premises
infrastructure, and a single-server Docker Compose environment for evaluation and smaller
installations.

The deployment experience should preserve ACP's security, worker isolation, observability, data
residency, and functional behavior across platforms while allowing customers to use their
preferred managed services.

## 2. Problem

ACP currently has a mature Azure Container Apps deployment path, a Docker Compose local/VPC
stack, separate API, Discovery, Assess, and Remediate execution patterns, Postgres, Redis,
Ollama, Grafana and Langfuse dependencies, and platform-specific Azure scripts and configuration.

It does not yet have one supported, versioned packaging contract that produces portable release
artifacts, describes infrastructure consistently, validates a deployment before use, supports
upgrades and rollback, maps services to equivalent Azure, AWS, GCP, Kubernetes and on-prem
capabilities, and gives operators a non-technical installation workflow.

Customers should not need to reverse-engineer Azure scripts or application environment variables
to deploy ACP elsewhere.

## 3. Goals

**Primary.** Deliver the same ACP application and worker images on every platform. Provide a
guided deployment workflow with validated presets. Preserve customer control over documents,
credentials, telemetry and AI processing. Support separate API, Discovery, Assess and Remediate
worker tiers. Support horizontal and vertical worker scaling. Support connected Google Drive,
SharePoint and approved private-network sources. Provide production readiness checks, health
verification, backup, upgrade and rollback. Generate a deployment manifest recording exactly what
was installed. Minimize platform-specific application code.

**Secondary.** Estimate infrastructure cost before deployment. Support disconnected or
restricted-network installations. Enable customer-managed encryption keys. Provide
high-availability and disaster-recovery profiles. Surface infrastructure details in ACP Live
Operations.

## 4. Non-Goals

The first release will not guarantee identical cloud pricing or performance; abstract every cloud
service behind one lowest-common-denominator interface; automatically create customer
identity-provider applications without administrator approval; store cloud administrator
credentials inside ACP; support arbitrary Kubernetes distributions without passing certification
tests; include one-click multi-region active-active operation; or make external AI providers
mandatory.

## 5. Packaging Strategy

### 5.1 Canonical release artifacts

Every ACP release must produce immutable, signed OCI images: `acp-web-api`,
`acp-discovery-worker`, `acp-assess-worker`, `acp-remediate-worker`, `acp-ollama-gateway`,
`acp-migrations`, `acp-preflight`, and optional observability images or supported upstream image
references.

Images must use the same source revision; be tagged with ACP CalVer and immutable digest; include
an SBOM; be vulnerability-scanned; be cryptographically signed; support AMD64; support ARM64
where all analysis engines permit it; run without root privileges where technically possible; and
expose `/healthz`, `/readyz`, build version and capability metadata.

**Cloud templates must reference image digests, not mutable tags.**

### 5.2 Supported installation methods

**Kubernetes and enterprise on-prem** — the primary package: Helm chart, versioned values schema,
Kubernetes Secrets integration, NetworkPolicy, PodDisruptionBudget, HorizontalPodAutoscaler or
KEDA, PersistentVolumeClaim definitions, Ingress configuration, migration Job, backup and restore
Jobs.

**Single-server on-prem or evaluation** — Docker Compose package, guided `.env` generator,
persistent Postgres and model volumes, optional local Redis, Ollama, Grafana and Langfuse,
automated preflight and smoke tests, upgrade and backup scripts. Docker Compose is not the
recommended large-scale production topology.

**Cloud-native packages** — OpenTofu/Terraform modules and thin deployment wrappers under
`platform/azure`, `platform/aws`, `platform/gcp`, `platform/kubernetes`, `platform/onprem`. All
modules consume the same normalized ACP configuration.

## 6. Target Architecture

```text
Users
  |
Ingress / Load Balancer / WAF
  |
ACP Web + API
  |
  +---------------- Durable Postgres ----------------+
  |                                                  |
  +---- Redis progress, leases and live events ------+
  |
  +--> Discovery queue  --> Discovery workers
  +--> Assessment queue --> Assess workers
  +--> Remediation queue -> Remediate workers
  |
  +--> Object storage for corrected files and artifacts
  +--> Customer-hosted or approved AI providers
  +--> Self-hosted observability and Langfuse
```

Documents must not pass through a vendor-managed control plane unless explicitly selected by the
customer.

## 7. Cloud Service Mapping

| Capability | Azure | AWS | Google Cloud | On-Prem/Kubernetes |
|---|---|---|---|---|
| Containers | Container Apps or AKS | ECS/Fargate or EKS | Cloud Run or GKE | Kubernetes |
| Container registry | ACR | ECR | Artifact Registry | Customer registry |
| Database | Azure Database for PostgreSQL | RDS PostgreSQL | Cloud SQL PostgreSQL | PostgreSQL HA or single node |
| Redis | Azure Managed Redis | ElastiCache | Memorystore | Redis/Valkey |
| Object storage | Azure Blob Storage | S3 | Cloud Storage | S3-compatible storage/MinIO |
| Secrets | Key Vault | Secrets Manager | Secret Manager | External Secrets/Vault |
| Identity | Managed Identity | IAM roles | Workload Identity | Service accounts/Vault |
| Logging | Azure Monitor | CloudWatch | Cloud Logging | OpenTelemetry stack |
| Metrics | Azure Monitor/Grafana | CloudWatch/Grafana | Cloud Monitoring/Grafana | Prometheus/Grafana |
| Autoscaling | ACA/KEDA | ECS scaling/KEDA | Cloud Run/GKE autoscaling | HPA/KEDA |
| GPU | GPU VM/AKS | EC2/EKS GPU | Compute Engine/GKE GPU | Customer GPU nodes |

The packages must document which combinations are production-supported versus preview.

## 8. Deployment Profiles

**Evaluation** — one machine, Docker Compose, local Postgres, local Ollama, minimal replicas, no
high availability.

**Standard Production** — split API and worker tiers, managed Postgres and Redis, managed object
storage, automatic backups, minimum two API replicas, independent worker scaling, central
monitoring.

**Regulated / Private** — private networking, no public worker ingress, customer-managed keys,
restricted egress, self-hosted Langfuse, local-only AI option, detailed audit logging,
configurable retention, PHI-safe telemetry defaults.

**High Availability** — multi-zone services, Postgres high availability, Redis high availability,
at least two replicas per critical tier, pod/container disruption protection, tested restore and
failover procedures, customer-defined RTO and RPO.

## 9. Unified Configuration Contract

A versioned `acp-deployment.yaml` specification, with JSON Schema validation, backward-compatible
versioning, secret references only (never raw secrets), environment-specific overrides,
human-readable validation errors, a generated effective-configuration report, and a redacted
diagnostic export.

The shipped schema is `packaging/schema/acp-deployment.schema.json`; the shipped examples are
`packaging/examples/*.acp-deployment.yaml`. The schema adds `api`, `runtime.platform`, `secrets`,
`capacity` and `data.postgres.maxConnections` to the illustrative example this PRD was written
with — see ADR 0048 for why each was required to make the contract checkable.

## 10. Installer and Operator Experience

An `acpctl` command-line installer providing: `init`, `validate`, `plan`, `install`, `status`,
`doctor`, `upgrade`, `rollback`, `backup`, `restore`, `uninstall`, `support-bundle`.

**Guided workflow.** `acpctl init` asks: where will ACP run; is this evaluation, production,
regulated or HA; which document sources are required; which identity provider will authenticate
users; must all AI processing remain local; which managed data services should be used; what
document volume and concurrency are expected; what backup retention and recovery objectives
apply; are public endpoints allowed; which region and data-residency boundary apply.

The tool generates configuration but does not provision until `acpctl plan` is reviewed.

**Plan output** must show resources to create or change, images and exact digests, CPU, memory and
storage allocations, minimum and maximum replicas, network ingress and egress, public endpoints,
secret references, expected monthly cost range where supported, destructive changes, migration
requirements, and rollback implications.

## 11. Scaling

**Scale out.** Independent replica ranges for API, Discovery, Assess and Remediate. Queue depth
and oldest-job age should be the preferred autoscaling signals. CPU may be a secondary signal but
must not be the only one.

**Scale up.** Validated resource presets:

| Preset | CPU | Memory | Temporary storage |
|---|---:|---:|---:|
| Small | 1 | 2 GiB | 4 GiB |
| Standard | 2 | 4 GiB | 8 GiB |
| Large | 4 | 8 GiB | 16 GiB |
| X-Large | 8 | 16 GiB | 32 GiB |

Not every provider supports every combination. The installer must reject unsupported combinations
before deployment.

**Runtime controls.** ACP Live Operations may display and propose capacity changes, but
infrastructure writes must be admin-only, use least-privilege cloud roles, display cost and
operational impact, drain workers before scale-down, record an audit event, support rollback and
respect organization-defined limits. Do not give the ACP web process unrestricted
cloud-administrator credentials.

## 12. Storage Requirements

Differentiate clearly among Postgres durable state, object-storage artifacts and remediated
files, AI model storage, temporary per-worker processing storage, observability storage and
backup storage.

Temporary worker storage must be treated as disposable. **No authoritative output may exist only
on ephemeral disk.**

The installer must calculate minimum temporary storage from maximum source-file size,
simultaneous files per worker, Office/PDF rendering expansion, remediation output and a safety
margin.

## 13. Security Requirements

Secrets are referenced from the platform secret manager and never appear in generated manifests,
logs, plans or support bundles. Workers have no public ingress. Database and Redis are private in
production profiles. TLS is required for every network hop where supported. Images are signed and
verified before deployment. Default network policy denies unnecessary ingress and egress. Cloud
identities use least privilege. Customer-managed keys are supported for regulated deployments.
Audit records include deployment, configuration and capacity changes. Support bundles redact
tokens, document names, user identities and file contents. Google and Microsoft OAuth
configuration remains tenant/customer-owned. External AI traffic is disabled by default.
Deployment preflight identifies every enabled external data path.

## 14. Observability

Every installation must provide application health; worker health and heartbeat; actual replicas
versus application worker slots; CPU, memory and temporary-storage utilization; queue depth and
oldest wait; processing throughput; job failures and retries; database and Redis connectivity;
object-storage connectivity; AI provider reachability; version and configuration drift; and
backup age and restore-test status.

Use OpenTelemetry as the portable application instrumentation layer. Cloud-specific exporters may
send metrics to Azure Monitor, CloudWatch or Google Cloud Monitoring. **Regulated installations
must support fully local collection.**

## 15. Upgrade and Rollback

An upgrade must validate configuration compatibility; confirm backup freshness; check available
storage and database capacity; run backward-compatible migrations; deploy new API and workers by
immutable digest; drain old workers without abandoning jobs; run readiness and functional smoke
tests; promote traffic only after success; preserve the previous release for rollback; and record
the deployment result in the audit trail.

Database migrations must define whether rollback is supported. The installer must block a claimed
rollback when the schema transition is irreversible.

## 16. Backup and Disaster Recovery

Back up Postgres, required Redis state if any is not reconstructable, object-storage artifacts,
configuration metadata, encryption-key references and Langfuse data when enabled.

Provide tested runbooks for accidental deletion, database loss, region or cluster loss, failed
upgrade, lost worker during remediation, object-storage corruption and secret rotation.

**A backup is not considered healthy until a restore test has succeeded within the
customer-defined interval.**

## 17. Air-Gapped and Restricted-Network Mode

Support an exportable installation bundle containing signed ACP images, required upstream images,
the Helm chart, the Docker Compose package, SBOMs, checksums and signatures, offline
documentation, model artifacts selected by the customer, license notices, and preflight and
smoke-test utilities.

The installer must produce an explicit allowlist for installations with controlled egress.

## 18. Repository Deliverables

```text
packaging/
  schema/acp-deployment.schema.json
  cli/acpctl/
  helm/acp/
  compose/
  terraform/modules/{common,azure,aws,gcp}/
  overlays/{evaluation,production,regulated,high-availability}/
  tests/{contract,smoke,upgrade,disaster-recovery}/
  docs/{install,operations,security,troubleshooting}/
```

Existing deployment assets should be migrated incrementally, not deleted until their replacements
have proven parity.

## 19. Testing Requirements

**Contract tests** run the same deployment assertions against every target: API readiness, worker
registration, queue processing, source authentication, discovery, assessment, remediation,
artifact persistence, SSE/live event delivery, audit logging, backup, upgrade, and rollback where
supported.

**Platform tests** use automated ephemeral environments for Azure, AWS, GCP, Kubernetes and
Docker Compose reference deployments.

**Failure tests** verify behavior when a worker dies mid-job, Redis is unavailable, Postgres fails
over, object storage is unavailable, temporary disk fills, the AI provider is unavailable, a
deployment is interrupted, scale-down occurs during active processing, credentials expire, and a
migration fails.

## 20. Acceptance Criteria

1. One ACP release produces signed, immutable multi-platform artifacts.
2. A new operator can generate a valid deployment plan in under 15 minutes.
3. Azure, AWS, GCP, Kubernetes and Docker Compose reference deployments pass the same smoke suite.
4. API and worker tiers scale independently.
5. No authoritative document or remediation artifact depends on ephemeral storage.
6. Secrets never appear in configuration output or support bundles.
7. Upgrade and rollback are demonstrated from the previous supported release.
8. Backup and restore are demonstrated.
9. Live Operations reports actual infrastructure and application-worker capacity.
10. Documentation distinguishes supported, preview and unsupported configurations.
11. A regulated deployment can run without external AI or external telemetry.
12. Every deployment produces a redacted, immutable installation manifest.

## 21. Delivery Phases

**Phase 0 — architecture and inventory.** Inventory current Azure and Compose behavior. Define
the portable service and configuration contracts. Identify Azure-specific assumptions in
application code. Publish an ADR covering the packaging architecture.

**Phase 1 — canonical containers.** Split and standardize release images. Add image signing,
SBOMs and provenance. Create migration and preflight images. Establish multi-architecture
feasibility.

**Phase 2 — Helm and Docker Compose.** Build the Helm chart. Normalize the existing Compose
deployment. Add configuration schema and smoke tests. Implement `acpctl init`, `validate`, `plan`,
`status` and `doctor`.

**Phase 3 — Azure reference implementation.** Rebuild the current Azure deployment using the
common contract. Prove feature and performance parity. Add managed service and private-network
options.

**Phase 4 — AWS and GCP.** Add Terraform/OpenTofu modules. Run the portable acceptance suite.
Document provider-specific constraints and costs.

**Phase 5 — enterprise operations.** Upgrade and rollback. Backup and restore. Air-gapped bundle.
HA profile. Capacity controls. Support bundles. Production certification matrix.

## 22. Engineering Guardrails

- Do not create separate application forks per cloud.
- Keep provider differences in infrastructure adapters.
- Prefer OpenTelemetry, OCI, Postgres, Redis/Valkey and S3-compatible abstractions.
- Do not silently downgrade from managed production services to embedded services.
- Do not claim high availability without failure testing.
- Do not expose infrastructure mutation controls before RBAC and audit logging exist.
- Do not place raw customer documents in centralized vendor telemetry.
- Do not replace the existing Azure deployment until the new Azure adapter demonstrates parity.
- Preserve current deployment assets until their retirement is explicit and tested.

## 23. First Implementation Slice

A bounded foundation change:

1. Add the deployment specification and JSON Schema.
2. Add an ADR describing the portable architecture.
3. Add a read-only `acpctl validate` and `acpctl plan`.
4. Add a normalized service inventory generated from the specification.
5. Add contract tests for worker resources, storage, networking, secrets and version consistency.
6. Do not provision cloud resources in the first PR.
7. Do not modify the current production deployment workflow in the first PR.

The first PR should make the packaging contract reviewable before implementation choices become
expensive.

## 24. Architecture direction (owner, 2026-09-04)

Refines §5.2 and §7, and is what ADR 0048 implements:

- **Kubernetes + Helm becomes the primary production portability layer.**
- **Azure, AWS and GCP packages become infrastructure adapters around the same Helm release.**
- **Docker Compose remains the evaluation / small on-prem option.**
- **Customer-managed Kubernetes becomes the recommended enterprise on-prem path.**
- **`acpctl` should generate Helm values, validate prerequisites, plan changes, install, upgrade
  and roll back.**

This preserves one application package while allowing AKS, EKS, GKE and customer Kubernetes to
supply their own managed Postgres, Redis, object storage, secrets and ingress.
