{{/* Validate that essential values like storageClassName and storagePath are provided. */}}
{{- define "validate.requiredValues" -}}
{{- if empty .Values.storageClassNames -}}
{{ fail "Please provide an array of storageclass names" }}
{{- end -}}
{{- if empty .Values.storagePaths -}}
{{ fail "Please provide an array of storage paths" }}
{{- end -}}
{{- $storageClassNames := .Values.storageClassNames | default (list) -}}
{{- $storagePaths := .Values.storagePaths | default (list) -}}
{{- end -}}

{{/* Convert metricsPort to an integer and validate its value. */}}
{{ define "validate.metricsPort" }}
{{- $metricsPort := .Values.metricsPort | int -}}
{{ if or (le $metricsPort 0) (gt $metricsPort 65535) }}
  {{ fail (printf "metricsPort must be set to a correct non-zero number. (Given value: %s)" .Values.metricsPort) }}
{{ end }}
{{- $metricsPort -}}
{{ end }}

{{- define "urlsafeB64enc" -}}
{{- $encoded := . | toString | b64enc -}}
{{- $urlsafe := $encoded | replace "+" "-" | replace "/" "_" -}}
{{- $noPadding := $urlsafe | trimSuffix "=" | trimSuffix "=" -}}
{{- $noPadding -}}
{{- end }}

{{/* Common labels */}}
{{- define "local-storage-exporter.labels" -}}
app.kubernetes.io/name: local-storage-exporter
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end }}