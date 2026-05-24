{{/*
Expand the name of the chart.
*/}}
{{- define "packvault.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "packvault.fullname" -}}
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
{{- define "packvault.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "packvault.labels" -}}
helm.sh/chart: {{ include "packvault.chart" . }}
{{ include "packvault.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "packvault.selectorLabels" -}}
app.kubernetes.io/name: {{ include "packvault.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use.
*/}}
{{- define "packvault.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "packvault.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Render the Deployment strategy.

Default behavior:
- local backend uses Recreate so a replacement pod does not compete for the same RWO PVC.
- s3 backend uses RollingUpdate because object storage is the source of truth.

Users may override the strategy with deploymentStrategy.type.
For RollingUpdate, deploymentStrategy.rollingUpdate.maxSurge and maxUnavailable are rendered when set.
*/}}
{{- define "packvault.deploymentStrategy" -}}
{{- $strategyType := .Values.deploymentStrategy.type -}}
{{- if not $strategyType -}}
{{- if eq .Values.config.storage.backend "local" -}}
{{- $strategyType = "Recreate" -}}
{{- else -}}
{{- $strategyType = "RollingUpdate" -}}
{{- end -}}
{{- end -}}
strategy:
  type: {{ $strategyType }}
{{- if eq $strategyType "RollingUpdate" }}
  rollingUpdate:
    maxSurge: {{ .Values.deploymentStrategy.rollingUpdate.maxSurge | quote }}
    maxUnavailable: {{ .Values.deploymentStrategy.rollingUpdate.maxUnavailable | quote }}
{{- end }}
{{- end }}
