{{/*
Expand the name of the chart.
*/}}
{{- define "chatbot-webapp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "chatbot-webapp.fullname" -}}
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
{{- define "chatbot-webapp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "chatbot-webapp.labels" -}}
helm.sh/chart: {{ include "chatbot-webapp.chart" . }}
{{ include "chatbot-webapp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "chatbot-webapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chatbot-webapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "chatbot-webapp.serviceAccountName" -}}
{{- if .Values.webapp.serviceAccount.create }}
{{- default (include "chatbot-webapp.fullname" .) .Values.webapp.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.webapp.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
OAuth2 Proxy name
*/}}
{{- define "chatbot-webapp.oauth2ProxyName" -}}
{{- printf "%s-oauth2-proxy" (include "chatbot-webapp.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
OAuth2 Proxy labels
*/}}
{{- define "chatbot-webapp.oauth2ProxyLabels" -}}
helm.sh/chart: {{ include "chatbot-webapp.chart" . }}
{{ include "chatbot-webapp.oauth2ProxySelectorLabels" . }}
app.kubernetes.io/version: {{ .Values.oauth2Proxy.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
OAuth2 Proxy selector labels
*/}}
{{- define "chatbot-webapp.oauth2ProxySelectorLabels" -}}
app.kubernetes.io/name: {{ include "chatbot-webapp.name" . }}-oauth2-proxy
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: oauth2-proxy
{{- end }}

{{/*
Keycloak name
*/}}
{{- define "chatbot-webapp.keycloakName" -}}
{{- printf "%s-keycloak" (include "chatbot-webapp.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Keycloak labels
*/}}
{{- define "chatbot-webapp.keycloakLabels" -}}
helm.sh/chart: {{ include "chatbot-webapp.chart" . }}
{{ include "chatbot-webapp.keycloakSelectorLabels" . }}
app.kubernetes.io/version: {{ .Values.keycloak.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Keycloak selector labels
*/}}
{{- define "chatbot-webapp.keycloakSelectorLabels" -}}
app.kubernetes.io/name: {{ include "chatbot-webapp.name" . }}-keycloak
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: keycloak
{{- end }}

{{/*
Generate cookie secret for OAuth2 Proxy
*/}}
{{- define "chatbot-webapp.oauth2ProxyCookieSecret" -}}
{{- if .Values.oauth2Proxy.config.cookieSecret }}
{{- .Values.oauth2Proxy.config.cookieSecret }}
{{- else }}
{{- randAlphaNum 32 | b64enc }}
{{- end }}
{{- end }}

{{/*
Generate Keycloak admin password
*/}}
{{- define "chatbot-webapp.keycloakAdminPassword" -}}
{{- if .Values.keycloak.admin.password }}
{{- .Values.keycloak.admin.password }}
{{- else }}
{{- randAlphaNum 16 }}
{{- end }}
{{- end }}

{{/*
Ingress host
*/}}
{{- define "chatbot-webapp.ingressHost" -}}
{{- if .Values.ingress.hosts }}
{{- (index .Values.ingress.hosts 0).host }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
OAuth2 Proxy redirect URL
*/}}
{{- define "chatbot-webapp.oauth2ProxyRedirectUrl" -}}
{{- if .Values.oauth2Proxy.config.redirectUrl }}
{{- .Values.oauth2Proxy.config.redirectUrl }}
{{- else }}
{{- $host := include "chatbot-webapp.ingressHost" . }}
{{- if $host }}
{{- printf "https://%s/oauth2/callback" $host }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}
{{- end }}
