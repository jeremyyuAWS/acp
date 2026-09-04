{{/*
The data-service boundary, enforced at render time.

WHY THIS FAILS RATHER THAN WARNS. A deployment document may ask for `mode: self-hosted` or
`mode: embedded`, which means "provision Postgres/Redis/object storage inside the cluster".
This chart does not do that (see Chart.yaml for why the subcharts are not vendored). The
tempting behaviour is to render the application anyway and note the gap in NOTES.txt.

That behaviour installs an ACP that cannot start, and reports success doing it. The API comes up,
fails its readiness probe against a database that was never created, and the operator reads a
CrashLoop as a bug in ACP rather than as a chart that did not provision what it was asked for.
Helm's `fail` turns that into a render-time error naming the exact key — before anything is
applied to a cluster at all.

It is the same rule the rest of this codebase keeps arriving at from other directions: a
component that cannot establish what it needs must say so, not proceed on a guess. Here the guess
would be "somebody else probably created the database".

THE ESCAPE HATCH IS EXPLICIT, not a flag that turns the check off. An operator who genuinely has
provisioned the data services by other means sets `external: true` (which is what `managed` mode
renders) and supplies the endpoint through `secrets.refs` — that is the supported path, and it is
one edit to the deployment document rather than a chart override.
*/}}

{{- define "acp.checkDataServices" -}}
{{- $unsupported := list -}}
{{- range $name := (list "postgresql" "redis" "objectStorage") -}}
{{- $cfg := index $.Values $name -}}
{{- if and $cfg (not $cfg.external) -}}
{{- $unsupported = append $unsupported (printf "%s (mode: %s)" $name (default "unset" $cfg.mode)) -}}
{{- end -}}
{{- end -}}
{{- if $unsupported -}}
{{- fail (printf (join "\n" (list
  "This chart does not provision in-cluster data services, and these are asking for one:"
  "  %s"
  ""
  "The ACP application package is what is identical across platforms; Postgres, Redis and object"
  "storage are what the platform ADAPTER supplies (ADR 0048). Rendering the application against"
  "a database nobody created would install a workload that cannot start and call it a success."
  ""
  "Either:"
  "  * point the deployment document at provisioned services (data.<service>.mode: managed) and"
  "    supply the connection details through secrets.refs, or"
  "  * install the data services separately and set <service>.external=true with the endpoint in"
  "    secrets.refs."
  ""
  "For a single-machine evaluation, use deploy/compose/ instead — that is what the evaluation"
  "profile is for, and it is Compose-only by contract."
)) (join ", " $unsupported)) -}}
{{- end -}}
{{- end -}}

{{/*
Every connection detail this chart requires, and the render fails naming the ones that are
missing rather than producing a Deployment with an empty DATABASE_URL.

An empty env var is worse than an absent one: the process starts, builds a connection string from
nothing, and fails somewhere further in with an error about syntax rather than about
configuration.
*/}}
{{- define "acp.checkRequiredSecrets" -}}
{{- if not .Values.secrets.existingSecret -}}
{{- $required := list "database-url" "redis-url" -}}
{{- $missing := list -}}
{{- range $key := $required -}}
{{- if not (hasKey ($.Values.secrets.refs | default dict) $key) -}}
{{- $missing = append $missing $key -}}
{{- end -}}
{{- end -}}
{{- if $missing -}}
{{- fail (printf (join "\n" (list
  "Missing required secret reference(s): %s"
  ""
  "Add them to the deployment document's `secrets.refs` and re-run `acpctl values`, or set"
  "`secrets.existingSecret` to a Secret you manage yourself that already carries these keys."
)) (join ", " $missing)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
