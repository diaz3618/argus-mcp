# Kubernetes Deployment

Deploy Argus MCP to Kubernetes using the official Helm chart.

## Prerequisites

- Kubernetes 1.28+
- Helm 3.12+
- Container image available (GHCR or Docker Hub)

## Quick Start

```bash
# Add/update chart (from local source)
helm install argus-mcp ./charts/argus-mcp \
  --namespace argus --create-namespace \
  --set gateway.managementToken="$(openssl rand -hex 32)"
```

## Configuration

All configuration is managed through `values.yaml`. Key settings:

### Image

```yaml
image:
  repository: ghcr.io/diaz3618/argus-mcp
  tag: ""          # Defaults to Chart.appVersion
  pullPolicy: IfNotPresent
```

### Gateway

```yaml
gateway:
  host: "0.0.0.0"
  port: 9000
  managementToken: ""      # Auto-creates a Secret
  existingSecret: ""       # Use a pre-existing Secret instead
  extraEnv: []             # Additional environment variables
```

### Replicas & Autoscaling

```yaml
replicaCount: 2            # Ignored when autoscaling is enabled

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 90
  targetMemoryUtilizationPercentage: 90
```

### Resources

```yaml
resources:
  requests:
    cpu: 500m
    memory: 768Mi
  limits:
    cpu: "2"
    memory: 2Gi
```

### Health Probes

The chart configures three health probes with conservative thresholds:

| Probe | Path | Initial Delay | Period | Failure Threshold |
|-------|------|---------------|--------|-------------------|
| Startup | `/manage/v1/health` | 5s | 5s | 12 |
| Readiness | `/manage/v1/ready` | 30s | 15s | 8 |
| Liveness | `/manage/v1/health` | 120s | 30s | 10 |

### Ingress

```yaml
ingress:
  enabled: false
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/hsts: "true"
    nginx.ingress.kubernetes.io/hsts-max-age: "31536000"
  hosts:
    - host: argus.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: argus-tls
      hosts:
        - argus.example.com
```

### Network Policy

```yaml
networkPolicy:
  enabled: true
  denyPrivateEgress: true    # SSRF protection guidance
```

### Config File

Mount a custom `config.yaml`:

```yaml
configMap:
  create: true
  data:
    config.yaml: |
      version: "1"
      server:
        host: 0.0.0.0
        port: 9000
      backends:
        - name: my-backend
          transport: stdio
          command: npx
          args: ["-y", "@example/mcp-server"]
```

## Install

```bash
# Basic install
helm install argus-mcp ./charts/argus-mcp \
  --namespace argus --create-namespace

# With custom values
helm install argus-mcp ./charts/argus-mcp \
  --namespace argus --create-namespace \
  -f my-values.yaml

# With inline overrides
helm install argus-mcp ./charts/argus-mcp \
  --namespace argus --create-namespace \
  --set replicaCount=3 \
  --set image.tag=0.7.1
```

## Upgrade

```bash
helm upgrade argus-mcp ./charts/argus-mcp \
  --namespace argus \
  -f my-values.yaml
```

## Rollback

```bash
# List revisions
helm history argus-mcp --namespace argus

# Rollback to previous
helm rollback argus-mcp --namespace argus

# Rollback to specific revision
helm rollback argus-mcp 2 --namespace argus
```

## Validation

After install, verify the deployment:

```bash
# Check pod status
kubectl get pods -n argus -l app.kubernetes.io/name=argus-mcp

# Check health endpoint
kubectl exec -n argus deploy/argus-mcp -- \
  curl -s http://localhost:9000/manage/v1/health

# Check readiness endpoint
kubectl exec -n argus deploy/argus-mcp -- \
  curl -s http://localhost:9000/manage/v1/ready

# Check HPA status
kubectl get hpa -n argus

# View logs
kubectl logs -n argus -l app.kubernetes.io/name=argus-mcp --tail=50
```

## Uninstall

```bash
helm uninstall argus-mcp --namespace argus
kubectl delete namespace argus
```

## Security

The chart follows security best practices:

- **Non-root container**: `runAsNonRoot: true`, `runAsUser: 1000`
- **Read-only filesystem**: `readOnlyRootFilesystem: true`
- **No privilege escalation**: `allowPrivilegeEscalation: false`
- **Dropped capabilities**: All Linux capabilities dropped
- **Network policies**: Restrict ingress/egress traffic
- **Service account**: `automountServiceAccountToken: false`
- **Secrets**: Management token stored in Kubernetes Secret (not in env directly)
