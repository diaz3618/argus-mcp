# Argus MCP Helm Chart

Helm chart for deploying [Argus MCP](https://github.com/diaz3618/argus-mcp) — a
multi-backend MCP proxy/gateway — on Kubernetes.

## Security Configuration

### Management API Token (K8s Secrets)

**Never store tokens in ConfigMaps or plain `values.yaml`.** Use Kubernetes
Secrets to provide the management API token:

```bash
# Generate a cryptographically random token (minimum 32 characters)
kubectl create secret generic argus-mgmt-token \
  --from-literal=token="$(openssl rand -hex 32)"
```

Reference the secret in your values override:

```yaml
gateway:
  existingSecret: argus-mgmt-token
  existingSecretKey: token
```

Rotate tokens periodically by updating the Secret and restarting the pods.

### Service Type and NodePort Exposure

> **Warning:** Using `service.type: NodePort` exposes the management API on
> every cluster node's IP address, which bypasses ingress-level access controls.

**Recommendations for production:**

| Service Type | Security | Use Case |
|---|---|---|
| `ClusterIP` (default) | Best — only reachable inside the cluster | Use with an Ingress controller |
| `LoadBalancer` | Good — cloud LB can enforce ACLs | Cloud-native deployments |
| `NodePort` | Risk — exposes on all nodes | Development and testing only |

If NodePort is required, restrict access with a NetworkPolicy ingress rule
limiting source CIDRs, and place a reverse proxy with authentication in front.

### TLS Configuration

TLS is **required** for all production deployments. Options:

1. **Ingress controller with TLS** (recommended): Use cert-manager or
   a manually provisioned certificate on the Ingress resource.

   ```yaml
   ingress:
     enabled: true
     tls:
       - secretName: argus-mcp-tls
         hosts:
           - argus-mcp.example.com
   ```

2. **Service mesh sidecar**: Istio or Linkerd provide mutual TLS between
   services without application changes.

3. **Application-level TLS**: Pass `--ssl-keyfile` and `--ssl-certfile` to
   uvicorn via the deployment command override.

### NetworkPolicy

The chart ships a `NetworkPolicy` that is **enabled by default**
(`networkPolicy.enabled: true`). The default policy:

- **Ingress:** Allows TCP traffic only on the gateway service port (9000).
- **Egress:** Allows DNS resolution (port 53 UDP/TCP). All other egress is
  **denied** unless you configure `networkPolicy.egress.cidrs`.

To allow the gateway to reach backend servers, add their CIDR blocks:

```yaml
networkPolicy:
  enabled: true
  egress:
    cidrs:
      - "10.96.0.0/12"    # Kubernetes service CIDR
      - "10.244.0.0/16"   # Pod CIDR (example — adjust for your cluster)
    allowDNS: true
```

Without explicit CIDRs the gateway cannot make outbound connections beyond DNS,
which prevents SSRF attacks against internal infrastructure.

### ServiceAccount and RBAC

The chart creates a dedicated ServiceAccount with **no additional RBAC
bindings** by default — the pod runs with least-privilege Kubernetes
permissions. This was verified and confirmed as the default in v0.8.2.

```yaml
serviceAccount:
  create: true
  automountServiceAccountToken: false  # default
```

Override `serviceAccount.create: false` if you supply a pre-existing
ServiceAccount.

## Values Reference

| Key | Default | Description |
|---|---|---|
| `networkPolicy.enabled` | `true` | Deploy a NetworkPolicy for the pods |
| `networkPolicy.egress.cidrs` | `[]` | CIDR blocks allowed for egress |
| `networkPolicy.egress.allowDNS` | `true` | Allow DNS egress (port 53) |
| `networkPolicy.ingress.enabled` | `true` | Restrict ingress to service port |
| `networkPolicy.allowFrom` | `[]` | Pod selectors allowed to reach the service |
| `networkPolicy.denyPrivateEgress` | `true` | Enable SSRF-protection comments |
| `serviceAccount.create` | `true` | Create a dedicated ServiceAccount |
| `ingress.enabled` | `false` | Create an Ingress resource |
| `ingress.tls` | `[]` | TLS configuration for the Ingress |
