{{/*
Expand the name of the chart.
*/}}
{{- define "local-storage-exporter.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "local-storage-exporter.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "local-storage-exporter.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "local-storage-exporter.labels" -}}
helm.sh/chart: {{ include "local-storage-exporter.chart" . }}
{{ include "local-storage-exporter.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "local-storage-exporter.selectorLabels" -}}
app.kubernetes.io/name: {{ include "local-storage-exporter.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "local-storage-exporter.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "local-storage-exporter.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* Validate that essential values like storageClassName and storagePath are provided. */}}
{{- define "validate.requiredValues" -}}
{{- if empty .Values.storageClassNames -}}
{{ fail "Please provide an array of storageclass names" }}
{{- end -}}
{{- if empty .Values.storagePaths -}}
{{ fail "Please provide an array of storage paths" }}
{{- end -}}
{{- end -}}

{{/* Validate that exactly one of daemonSet or deployment is enabled. */}}
{{- define "validate.workloadMode" -}}
{{- if and .Values.daemonSet.enabled .Values.deployment.enabled -}}
{{ fail "Only one of daemonSet.enabled or deployment.enabled can be true, not both" }}
{{- end -}}
{{- if and (not .Values.daemonSet.enabled) (not .Values.deployment.enabled) -}}
{{ fail "At least one of daemonSet.enabled or deployment.enabled must be true" }}
{{- end -}}
{{- end -}}

{{/* Convert metricsPort to an integer and validate its value. */}}
{{- define "validate.metricsPort" -}}
{{- $metricsPort := .Values.metricsPort | int -}}
{{- if or (le $metricsPort 0) (gt $metricsPort 65535) -}}
{{ fail (printf "metricsPort must be set to a correct non-zero number. (Given value: %s)" .Values.metricsPort) }}
{{- end -}}
{{- $metricsPort -}}
{{- end -}}

{{/* Validate that ServiceMonitor dependencies are met. */}}
{{- define "validate.monitorDependencies" -}}
{{- if and .Values.serviceMonitor.enabled (not .Values.service.enabled) -}}
{{ fail "serviceMonitor.enabled requires service.enabled to be true. ServiceMonitor needs a Service resource to scrape from." }}
{{- end -}}
{{- end -}}

{{/* Validate ServiceAccount + RBAC configuration to prevent security issues. */}}
{{- define "validate.serviceAccountRBAC" -}}
{{- if and .Values.rbac.create (not .Values.serviceAccount.create) (empty .Values.serviceAccount.name) -}}
{{ fail "When rbac.create=true and serviceAccount.create=false, you must explicitly set serviceAccount.name. Otherwise RBAC will bind to the 'default' ServiceAccount, granting permissions to all pods in the namespace." }}
{{- end -}}
{{- end -}}

{{- define "urlsafeB64enc" -}}
{{- $encoded := . | toString | b64enc -}}
{{- $urlsafe := $encoded | replace "+" "-" | replace "/" "_" -}}
{{- $noPadding := $urlsafe | trimSuffix "=" | trimSuffix "=" -}}
{{- $noPadding -}}
{{- end }}
