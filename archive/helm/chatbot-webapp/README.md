# Chatbot Webapp Helm Chart

A comprehensive Helm chart for deploying the AI Chatbot Webapp to Kubernetes with optional Keycloak authentication.

## Features

- 🚀 **Production-ready deployment** with health checks and resource limits
- 🔄 **Horizontal Pod Autoscaling** (optional) based on CPU/memory
- 🔐 **OAuth2 Proxy integration** for authentication (optional)
- 🔑 **Keycloak deployment** with OIDC support (optional)
- 🌐 **AWS ALB Ingress** with HTTPS support
- 📊 **Configurable replicas** with pod anti-affinity
- 🛠️ **Extensive configuration** via values.yaml

## Prerequisites

- Kubernetes 1.23+
- Helm 3.8+
- AWS Load Balancer Controller (for ALB Ingress)
- ACM Certificate for HTTPS
- Docker image in ECR or container registry

## Quick Start

### 1. Build and Push Docker Image

```bash
# Build the webapp image
docker build -t your-repo/chatbot-webapp:latest ./webapp

# Tag for ECR
docker tag your-repo/chatbot-webapp:latest \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/chatbot-webapp:latest

# Push to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789012.dkr.ecr.us-east-1.amazonaws.com

docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/chatbot-webapp:latest
```

### 2. Create Values File

Create `my-values.yaml`:

```yaml
webapp:
  image:
    repository: "123456789012.dkr.ecr.us-east-1.amazonaws.com/chatbot-webapp"
    tag: "latest"

config:
  chatbotUrl: "https://your-api-gateway-url.execute-api.us-east-1.amazonaws.com/prod/chatbot/query"
  authMode: "token"

ingress:
  hosts:
    - host: "chatbot.your-domain.com"
      paths:
        - path: /
          pathType: Prefix
  tls:
    certificateArn: "arn:aws:acm:us-east-1:123456789012:certificate/abcd1234-..."
```

### 3. Install the Chart

```bash
# Install in default namespace
helm install chatbot-webapp ./helm/chatbot-webapp -f my-values.yaml

# Or install in custom namespace
helm install chatbot-webapp ./helm/chatbot-webapp \
  -f my-values.yaml \
  --namespace chatbot \
  --create-namespace
```

### 4. Verify Deployment

```bash
# Check pods
kubectl get pods -l app.kubernetes.io/name=chatbot-webapp

# Check ingress
kubectl get ingress

# Get ALB URL
kubectl get ingress chatbot-webapp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# View logs
kubectl logs -l app.kubernetes.io/name=chatbot-webapp -f
```

## Configuration

### Basic Webapp Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `webapp.enabled` | Enable webapp deployment | `true` |
| `webapp.replicaCount` | Number of replicas | `2` |
| `webapp.image.repository` | Image repository | `""` (required) |
| `webapp.image.tag` | Image tag | `"latest"` |
| `webapp.resources.requests.cpu` | CPU request | `50m` |
| `webapp.resources.requests.memory` | Memory request | `64Mi` |
| `webapp.resources.limits.cpu` | CPU limit | `200m` |
| `webapp.resources.limits.memory` | Memory limit | `128Mi` |

### Autoscaling

| Parameter | Description | Default |
|-----------|-------------|---------|
| `webapp.autoscaling.enabled` | Enable HPA | `false` |
| `webapp.autoscaling.minReplicas` | Minimum replicas | `2` |
| `webapp.autoscaling.maxReplicas` | Maximum replicas | `10` |
| `webapp.autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `80` |
| `webapp.autoscaling.targetMemoryUtilizationPercentage` | Target memory % | `80` |

### Application Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.chatbotUrl` | Backend API URL | `""` (required) |
| `config.authMode` | Auth mode (token/bearer/none) | `token` |
| `config.authValue` | Default auth token | `""` |
| `config.retrievalMode` | Retrieval mode | `hybrid` |
| `config.assistantMode` | Assistant mode | `contextual` |
| `config.modelId` | LLM model ID | `anthropic.claude-3-5-sonnet-20240620-v1:0` |

### Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.className` | Ingress class | `alb` |
| `ingress.hosts[0].host` | Hostname | `""` (required) |
| `ingress.tls.enabled` | Enable HTTPS | `true` |
| `ingress.tls.certificateArn` | ACM certificate ARN | `""` (required) |
| `ingress.public` | Internet-facing ALB | `false` |

### OAuth2 Proxy (Keycloak Auth)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `oauth2Proxy.enabled` | Enable OAuth2 Proxy | `false` |
| `oauth2Proxy.replicaCount` | Number of replicas | `2` |
| `oauth2Proxy.config.provider` | OAuth provider | `keycloak-oidc` |
| `oauth2Proxy.config.oidcIssuerUrl` | OIDC issuer URL | `""` (required if enabled) |
| `oauth2Proxy.config.clientId` | Client ID | `""` (required if enabled) |
| `oauth2Proxy.config.clientSecret` | Client secret | `""` (required if enabled) |
| `oauth2Proxy.config.emailDomain` | Allowed email domains | `*` |

### Keycloak Deployment

| Parameter | Description | Default |
|-----------|-------------|---------|
| `keycloak.enabled` | Enable Keycloak | `false` |
| `keycloak.replicaCount` | Number of replicas | `1` |
| `keycloak.admin.username` | Admin username | `admin` |
| `keycloak.admin.password` | Admin password (auto-generated if empty) | `""` |
| `keycloak.persistence.enabled` | Enable persistent storage | `false` |
| `keycloak.persistence.size` | Storage size | `10Gi` |
| `keycloak.database.enabled` | Use external PostgreSQL | `false` |
| `keycloak.ingress.enabled` | Enable Keycloak ingress | `true` |
| `keycloak.ingress.host` | Keycloak hostname | `""` (required if enabled) |

## Deployment Scenarios

### Scenario 1: Simple Deployment (No Auth)

```yaml
webapp:
  image:
    repository: "your-ecr-url/chatbot-webapp"
    tag: "latest"

config:
  chatbotUrl: "https://api.example.com/chatbot/query"
  authMode: "token"

ingress:
  hosts:
    - host: "chatbot.example.com"
  tls:
    certificateArn: "arn:aws:acm:..."
```

```bash
helm install chatbot ./helm/chatbot-webapp -f simple-values.yaml
```

### Scenario 2: With Keycloak Authentication

```yaml
webapp:
  image:
    repository: "your-ecr-url/chatbot-webapp"
    tag: "latest"

config:
  chatbotUrl: "https://api.example.com/chatbot/query"
  authMode: "bearer"  # Use bearer tokens from Keycloak

ingress:
  hosts:
    - host: "chatbot.example.com"
  tls:
    certificateArn: "arn:aws:acm:..."

oauth2Proxy:
  enabled: true
  config:
    provider: "keycloak-oidc"
    oidcIssuerUrl: "https://keycloak.example.com/auth/realms/chatbot"
    clientId: "chatbot-webapp"
    clientSecret: "your-client-secret"

keycloak:
  enabled: true
  admin:
    password: "your-secure-password"
  ingress:
    enabled: true
    host: "keycloak.example.com"
    tls:
      certificateArn: "arn:aws:acm:..."
```

```bash
helm install chatbot ./helm/chatbot-webapp -f keycloak-values.yaml
```

### Scenario 3: With Autoscaling

```yaml
webapp:
  replicaCount: 2  # Initial replicas
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

### Scenario 4: Production Setup with External Keycloak

```yaml
webapp:
  replicaCount: 3
  image:
    repository: "your-ecr-url/chatbot-webapp"
    tag: "v1.2.3"

config:
  chatbotUrl: "https://api.prod.example.com/chatbot/query"

ingress:
  public: true  # Internet-facing
  hosts:
    - host: "chatbot.example.com"

oauth2Proxy:
  enabled: true
  config:
    provider: "keycloak-oidc"
    oidcIssuerUrl: "https://auth.example.com/realms/production"
    clientId: "chatbot-prod"
    clientSecret: "secret-from-vault"

keycloak:
  enabled: false  # Using external Keycloak
```

## Upgrade

```bash
# Upgrade with new values
helm upgrade chatbot ./helm/chatbot-webapp -f my-values.yaml

# Upgrade only image tag
helm upgrade chatbot ./helm/chatbot-webapp --reuse-values \
  --set webapp.image.tag=v1.2.3
```

## Uninstall

```bash
helm uninstall chatbot

# With namespace cleanup
helm uninstall chatbot -n chatbot
kubectl delete namespace chatbot
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=chatbot-webapp

# View pod events
kubectl describe pod <pod-name>

# Check logs
kubectl logs <pod-name>
```

### Ingress Not Working

```bash
# Check ingress status
kubectl get ingress chatbot-webapp -o yaml

# Verify ALB Controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller

# Check target group health in AWS Console
```

### OAuth2 Proxy Issues

```bash
# Check OAuth2 Proxy logs
kubectl logs -l app.kubernetes.io/component=oauth2-proxy

# Verify secret
kubectl get secret chatbot-webapp-oauth2-proxy -o yaml

# Test OIDC discovery
curl https://keycloak.example.com/auth/realms/chatbot/.well-known/openid-configuration
```

### Keycloak Issues

```bash
# Check Keycloak logs
kubectl logs -l app.kubernetes.io/component=keycloak

# Get admin password
kubectl get secret chatbot-webapp-keycloak -o jsonpath='{.data.admin-password}' | base64 -d

# Port-forward for direct access
kubectl port-forward svc/chatbot-webapp-keycloak 8080:8080
# Access at http://localhost:8080/auth
```

## Security Considerations

1. **Secrets Management**: Use external secret managers (AWS Secrets Manager, HashiCorp Vault)
2. **Network Policies**: Implement NetworkPolicies to restrict pod communication
3. **TLS**: Always use HTTPS in production (set `ingress.tls.certificateArn`)
4. **Resource Limits**: Set appropriate CPU/memory limits to prevent resource exhaustion
5. **Image Scanning**: Scan container images for vulnerabilities
6. **Pod Security**: Enable pod security contexts and standards

## Advanced Configuration

### Custom Labels and Annotations

```yaml
commonLabels:
  team: platform
  environment: production

webapp:
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "80"

service:
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-backend-protocol: http
```

### Service Account with IAM Role

```yaml
webapp:
  serviceAccount:
    create: true
    annotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/chatbot-webapp-role"
```

### Node Affinity

```yaml
webapp:
  nodeSelector:
    nodegroup: webapp
  
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: workload-type
            operator: In
            values:
            - web
```

## Related Documentation

- [Keycloak Integration Guide](../../docs/keycloak_integration.md)
- [EKS Deployment Guide](../../infra/kubernetes/README.md)
- [Static Website Template](../../infra/kubernetes/static-website-template/README.md)

## License

See main repository LICENSE file.

## Support

For issues and questions:
- GitHub Issues: https://github.com/your-org/aws-agentic-ai-pr-reviewer/issues
- Documentation: docs/ directory
