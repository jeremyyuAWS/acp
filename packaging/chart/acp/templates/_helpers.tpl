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
- name: ACP_ENVIRONMENT
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

/readyz is the readiness probe and /healthz the liveness one, and they are NOT interchangeable:
readyz reports on dependencies (the database, the renderer) and a failing dependency should take
a pod out of the load balancer, while restarting it would only move the outage around.
*/}}
{{- define "acp.apiProbes" -}}
readinessProbe:
  httpGet:
    path: /readyz
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
