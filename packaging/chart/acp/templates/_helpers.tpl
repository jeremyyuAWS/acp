{{/*
Names, labels, and the image reference — the three things every template needs and none should
compute for itself.
*/}}

{{- define "acp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "acp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "acp.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "acp.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: acp
acp.mova.io/profile: {{ .Values.acpDeployment.profile | quote }}
acp.mova.io/platform: {{ .Values.acpDeployment.platform | quote }}
{{- end -}}

{{- define "acp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "acp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "acp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "acp.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
The image reference for one component.

A DIGEST WINS OVER A TAG, ALWAYS. `image.tag` is a moving reference: two installs a week apart
can run different code from the same values file, and an installation that cannot say exactly
what it ran is not auditable — which is the whole point of `acpctl install` resolving digests
before it deploys. When a digest is present for a component, the tag is not even appended.

Call as: include "acp.image" (dict "root" $ "component" "api")
*/}}
{{- define "acp.image" -}}
{{- $root := .root -}}
{{- $component := .component -}}
{{- $img := $root.Values.image -}}
{{- /*
  THREE repositories now, not two, and spelled as a lookup rather than a nested ternary. The
  worker and the API share one image and differ by command; ollama is a genuinely different
  artifact (deploy/ollama/Dockerfile, models baked in) and cannot be a tag on either.
*/ -}}
{{- $repo := $img.repository -}}
{{- if eq $component "worker" -}}{{- $repo = $img.workerRepository -}}{{- end -}}
{{- if eq $component "ollama" -}}{{- $repo = $img.ollamaRepository -}}{{- end -}}
{{- if eq $component "grafana" -}}{{- $repo = $img.grafanaRepository -}}{{- end -}}
{{- $registry := $img.registry -}}
{{- $digest := get ($img.digests | default dict) $component -}}
{{- $base := $repo -}}
{{- if $registry -}}
{{- $base = printf "%s/%s" $registry $repo -}}
{{- end -}}
{{- if $digest -}}
{{- printf "%s@%s" $base $digest -}}
{{- else -}}
{{- $tag := $img.tag | default $root.Chart.AppVersion -}}
{{- printf "%s:%s" $base $tag -}}
{{- end -}}
{{- end -}}

{{/*
The Secret every workload reads its connection strings from.

One name, whichever backend produced it: a native Kubernetes Secret, one the External Secrets
Operator syncs from the platform's vault, or one that already existed. The workloads mount the
same name in all three cases, which is what lets the API and worker Deployments be identical
across platforms — the thing ADR 0048 claims and templates/tests/ checks.
*/}}
{{- define "acp.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "acp.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Environment shared by every ACP workload — API, workers, and both hook jobs.

DEFINED ONCE BECAUSE DRIFT HERE IS INVISIBLE. A worker that reads a different DATABASE_URL than
the API does not fail at startup; it connects to the wrong database and works, which is the
failure you find weeks later in somebody's data. The per-component parts (ACP_WORKERS,
ACP_WORKER_ROLE) are added by the caller; everything below is identical by construction.
*/}}
{{- define "acp.commonEnv" -}}
- name: ACP_RELEASE
  value: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
{{- /*
  ACP_DEPLOY_ENV, NOT ACP_ENVIRONMENT, AND THE DIFFERENCE IS A SECURITY CONTROL.

  This rendered `ACP_ENVIRONMENT` until 2026-09-08 — a name nothing in api/ reads, sitting one
  underscore away from two that it does. `api/core.py` computes IS_PROD from ACP_DEPLOY_ENV (or
  the legacy ACP_ENV), and IS_PROD is what forces TEST_BYPASS_ENABLED off: the X-E2E-Key and
  X-Demo-Key gate bypasses are refused in production REGARDLESS of the opt-in that enables them.

  That file records this exact failure happening once already, in its own words: "IS_PROD stayed
  False on the public demo, and the X-E2E-Key bypass stayed live", because the variable operators
  were told to set never reached the container. The bypass is fail-closed now — it needs an
  explicit ACP_ENABLE_TEST_BYPASS as well — so nothing was open here. What was true is that an
  installation which enabled the bypass for staging and promoted the same values to production
  kept it, because the chart gave the application no way to know which it was.

  The value space already matches: the document's `metadata.environment` is development, staging
  or production, and IS_PROD tests for production. Renaming rather than adding a second variable,
  because a workload carrying both would leave a reader to guess which one is live — and the old
  name was read by nothing, which tests/test_packaging_seams.py had established.
*/}}
- name: ACP_DEPLOY_ENV
  value: {{ .Values.acpDeployment.environment | quote }}
- name: ACP_DEPLOY_PROFILE
  value: {{ .Values.acpDeployment.profile | quote }}
- name: ACP_PLATFORM
  value: {{ .Values.acpDeployment.platform | quote }}
{{- if .Values.observability.openTelemetry.enabled }}
{{- /*
  THE SEAM NOW MEETS, and what was here before did not.

  It set three generic OpenTelemetry SDK variables: OTEL_SDK_DISABLED=false, OTEL_SERVICE_NAME,
  and OTEL_EXPORTER_OTLP_ENDPOINT — the last one never actually written, because `acpctl values`
  emits `observability.openTelemetry.{enabled, exporter}` and this template read `{enabled,
  endpoint}`. So the render said "instrumentation on" and gave it nowhere to go.

  The deeper half is that OTLP was never the mechanism. `api/telemetry.py` configures the AZURE
  MONITOR OpenTelemetry distribution and needs exactly one thing to start:
  APPLICATIONINSIGHTS_CONNECTION_STRING. Without it `configure()` returns
  `{"enabled": false, "reason": "not configured"}` and no exporter, no SDK and no egress exist —
  so OTEL_SDK_DISABLED=false was describing an SDK that was never constructed. The chart set
  three variables the application does not act on and omitted the one it reads.

  So what does the wiring now, and this is why this block shrank to one line: the SECRET REFS
  do. The loop below projects every entry of `secrets.refs` as its own uppercase env var, so
  `applicationinsights-connection-string` arrives as APPLICATIONINSIGHTS_CONNECTION_STRING and
  `acp-telemetry-salt` as ACP_TELEMETRY_SALT — exactly the two names api/telemetry.py reads,
  with no special case anywhere. Declaring the reference IS the wiring.

  The first draft of this block set the connection string explicitly and got it twice: once here
  and once from that loop, which Kubernetes resolves by taking the last and a reader resolves by
  wondering which one is live. It also mapped the salt by hand as `telemetry-salt`, which the
  same loop then ALSO emitted as TELEMETRY_SALT — a variable nothing reads, sitting next to the
  one that works. Renaming the reference to `acp-telemetry-salt` deleted both problems and the
  code that caused them.

  OTEL_SERVICE_NAME stays because it is the one thing no reference can supply: it names this
  release in Application Insights, and the distro honours it once there is an SDK to name.
*/}}
- name: OTEL_SERVICE_NAME
  value: {{ include "acp.fullname" . | quote }}
{{- end }}
{{- if .Values.ai.ollama.enabled }}
{{- /*
  THE CLIENT HALF, and the reason rendering the Deployment alone would not have been a fix.
  `api/ai.py` reaches Ollama through OLLAMA_BASE_URL; without it the workload runs against no
  model runtime while a perfectly healthy one sits in the same namespace. Compose has always set
  this (`OLLAMA_BASE_URL=http://ollama:11434`); the chart set nothing, so the seam existed on
  both sides at once and each half looked like the other one's problem.
*/}}
- name: OLLAMA_BASE_URL
  value: {{ printf "http://%s-ollama:%v" (include "acp.fullname" .) .Values.ai.ollama.port | quote }}
{{- range $k, $v := .Values.ai.ollama.clientEnv }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end }}
{{- if .Values.objectStorage.account }}
{{- /*
  THE REMEDIATED-OUTPUT STORE, AND THE SEAM THAT DID NOT MEET UNTIL 2026-09-08.

  `api/blob.py` is the PRIMARY store for a remediated file's fixed copy (ADR 0010) and reads
  exactly one variable to decide whether it exists: ACP_BLOB_ACCOUNT. Unset, `_ENABLED` is false
  and every function returns None — so an installation remediates documents, logs "corrected copy
  stored in ACP", and keeps the digest and the byte count while dropping the bytes
  (`api/store.py`'s record_remediation takes the `blob_url is None` branch; there is no BYTEA
  column, which ADR 0010 rejected deliberately).

  This chart set no such variable. `deploy/public/deploy.sh` has always set it on both the API and
  the worker apps, so the Container Apps deployment persists output and every Helm install
  silently did not — a deployment that comes up healthy, passes a smoke test, and loses the one
  artifact ACP exists to produce.

  THE NAME IS THE APPLICATION'S, NOT THIS CHART'S. ACP_BLOB_ACCOUNT is Azure-shaped because
  api/blob.py is: it builds `https://<account>.blob.core.windows.net` and authenticates with
  DefaultAzureCredential, with no endpoint override and no key-based path. Renaming it, or making
  it S3-compatible, is an application change and not a packaging one. What the chart can do is
  stop the value going unset, which is what this does — and `acpctl validate` warns when the
  document omits it rather than leaving the gap to be found in a remediation run.
*/}}
- name: ACP_BLOB_ACCOUNT
  value: {{ .Values.objectStorage.account | quote }}
{{- end }}
{{- if .Values.observability.langfuse.host }}
{{- /*
  THE THIRD OF THREE, AND THE OTHER TWO WERE ALREADY HERE.

  `api/lf.py` is `_ENABLED = bool(_HOST and _PK and _SK)`. The two keys arrive through the
  `secrets.refs` projection below — the contract requires both — and the host is an endpoint
  rather than a credential, so it comes from the document. Until 2026-09-08 the chart projected
  the secret key alone, so a document that declared a Langfuse mode, satisfied the reference the
  contract demanded and provisioned a Langfuse got one third of what the module needs. It reports
  itself disabled and raises nothing, which is the quietest way for a feature to be absent.
*/}}
- name: LANGFUSE_HOST
  value: {{ .Values.observability.langfuse.host | quote }}
{{- end }}
{{- if eq .Values.ai.mode "local-only" }}
{{- /*
  The regulated profile's central promise: no document content leaves the cluster for a model.
  Rendered as an explicit env var rather than left implicit, so an operator reading the running
  Deployment can see it — a promise nobody can read off the workload is one nobody can audit.
*/}}
- name: ACP_AI_LOCAL_ONLY
  value: "1"
{{- end }}
{{- range $key, $ref := .Values.secrets.refs }}
- name: {{ $key | upper | replace "-" "_" }}
  valueFrom:
    secretKeyRef:
      name: {{ include "acp.secretName" $ }}
      key: {{ $key }}
{{- end }}
{{- end -}}

{{/*
Probes. The API serves both; workers have no HTTP listener and get neither, which is why this
takes the component rather than being pasted into each Deployment.

THE READINESS PATH IS /probe/readyz, AND THE TWO OBVIOUS-LOOKING ALTERNATIVES ARE BOTH WRONG.
The application has three health routes and its own source (api/routes/system.py, the block
comment above `probe_readyz`) says which one a platform probe may point at — this one, and only
this one:

  /healthz       build provenance. Touches NO dependency, so it answers 200 from a replica that
                 cannot reach the database — exactly the replica a readiness gate exists to hold
                 traffic away from. Correct for LIVENESS, which is what it is used for below.
  /readyz        "can this DEPLOYMENT do work" — the worker tier, the PDF engine, the renderer.
                 Two problems as a readiness target. It never sets a status code, so it returns
                 200 unconditionally and the gate can never close. And if it ever did fail it
                 would fail for a worker-tier outage, which evicts the API container — a restart
                 that cannot fix a worker tier and loses the API too.
  /probe/readyz  this container, its database, one round-trip, 503 when that fails. Deliberately
                 narrow: nothing about the worker tier, the vision model or any source adapter,
                 all of which are legitimately absent on a replica that serves perfectly well.

This chart pointed readiness at /readyz until 2026-09-08. Nothing failed, because nothing could:
a probe that cannot return non-200 is indistinguishable from a healthy deployment, and the window
it left open — traffic to a replica whose database reads have not started answering — is the one
`/probe/readyz` was added to close (sampled live during #1151: /healthz 200 in 0.39s while every
database-backed route hung for 25s on the same replica).
*/}}
{{- define "acp.apiProbes" -}}
readinessProbe:
  httpGet:
    path: /probe/readyz
    port: http
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 30
  periodSeconds: 20
  timeoutSeconds: 5
  failureThreshold: 6
{{- end -}}

{{/*
Zone spreading for a tier that runs more than one pod.

WHAT THIS ADDS OVER THE ANTI-AFFINITY ALREADY ON THE API. That rule is
`preferredDuringScheduling` across `kubernetes.io/hostname`: it asks for different NODES and says
nothing about zones, so three replicas can land on three nodes in one availability zone and
satisfy it completely. The failure a multi-replica API tier is bought to survive is losing a zone,
and nothing in the chart addressed it.

WHY `ScheduleAnyway` IS THE DEFAULT, AND WHY THAT IS NOT TIMIDITY. `DoNotSchedule` on this
constraint is a claim about the cluster, and two of its failure modes are outages:

  - Nodes without the `topologyKey` LABEL are not eligible at all under `DoNotSchedule`. A cluster
    whose nodes carry no `topology.kubernetes.io/zone` — every kind and k3d cluster, and any
    single-zone install — has no eligible node, and every replica stays Pending forever. The
    reference cluster this chart is installed on is exactly that cluster.
  - Without `matchLabelKeys` (Kubernetes 1.27+, and `doctor.MINIMUM_KUBERNETES` is 1.23) the
    constraint counts the OUTGOING ReplicaSet's pods during a rolling update, so an update can
    wedge itself against its own predecessors.

`ScheduleAnyway` makes the scheduler actively BALANCE across zones and fall back rather than
refuse, which is a real improvement over ignoring zones and cannot strand a pod. Hardening it is
one value, for an operator who knows their nodes are labelled and their version is high enough —
and PRD S4 is explicit that a target is not supported because Helm renders for it, so the chart
does not assert multi-zone survival it has never demonstrated.

NOT RENDERED FOR A SINGLE-REPLICA TIER, where the constraint is arithmetic on one pod, nor for
Ollama and Grafana, which are one pod by construction.
*/}}
{{- define "acp.topologySpread" -}}
{{- $root := .root -}}
{{- $spread := $root.Values.topologySpread -}}
{{- if $spread.enabled }}
topologySpreadConstraints:
  - maxSkew: {{ $spread.maxSkew }}
    topologyKey: {{ $spread.topologyKey }}
    whenUnsatisfiable: {{ $spread.whenUnsatisfiable }}
    {{- /*
      THE SELECTOR IS PASSED IN, NOT DERIVED FROM A COMPONENT NAME, because the three worker
      Deployments all carry `app.kubernetes.io/component: worker` and differ only by
      `acp.mova.io/worker-role`. A constraint built from a component name alone would have
      selected zero pods on the workers — and a topology constraint whose selector matches
      nothing is not an error: it is satisfied vacuously, renders correctly, and spreads nothing.
      Callers pass the SAME labels their Deployment selects on, so the two cannot drift.
    */}}
    labelSelector:
      matchLabels:
        {{- include "acp.selectorLabels" $root | nindent 8 }}
        {{- toYaml .selector | nindent 8 }}
{{- end }}
{{- end -}}

{{/*
A map Kubernetes will accept where it demands string values.

`toYaml` PRESERVES YAML'S TYPES, AND FOR ANNOTATIONS AND nodeSelector THAT IS WRONG. Both are
`map[string]string` in the API, so a value that parses as a number or a boolean is rejected — not
by the template, not by `helm template`, not by `helm lint`, but by the API server, at install or
upgrade, with:

    cannot patch "acp-api" with kind Deployment: "" is invalid: patch: Invalid value: "{…}":
    json: cannot unmarshal number into Go struct field ObjectMeta.spec.template.metadata.
    annotations of type string

FOUND BY THE UPGRADE STEP ON ITS FIRST RUN, 2026-09-08, with a probe annotation set to
`$GITHUB_RUN_ID`. Nothing about it is upgrade-specific: an install carrying the same value fails
identically. And `--set-string` is not the fix, because the operator most likely to hit this is
writing a values FILE — `build-number: 1234` in YAML is an int before helm ever sees it, and there
is no per-key string flag for a file.

Quoting every value is the whole fix, and it costs nothing: a value that was already a string
quotes to itself.
*/}}
{{- define "acp.stringMap" -}}
{{- range $key, $value := . }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end -}}
