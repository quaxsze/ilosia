{{- define "agent-workspace.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: agent-workspace
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "agent-workspace.selectorLabels" -}}
app.kubernetes.io/name: agent-workspace
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
