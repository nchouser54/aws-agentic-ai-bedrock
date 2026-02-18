# ArgoCD Deployment Configurations

This directory contains ArgoCD `Application` manifests for deploying the chatbot webapp to Kubernetes.

## Quick Start

### 1. Install ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

### 2. Access ArgoCD UI

```bash
# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Port-forward to access UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Open browser: https://localhost:8080
# Login: admin / <password-from-above>
```

### 3. Configure Your Application

Edit the appropriate YAML file and replace placeholders:

```bash
# For production
cp environments/production.yaml environments/production.yaml.configured

# Replace placeholders
sed -i 's|REPLACE_WITH_ECR_URL|123456789.dkr.ecr.us-gov-west-1.amazonaws.com|g' environments/production.yaml.configured
sed -i 's|REPLACE_WITH_VERSION|v1.0.0|g' environments/production.yaml.configured
sed -i 's|REPLACE_WITH_PROD_API_URL|https://api-chatbot.your-domain.com|g' environments/production.yaml.configured
sed -i 's|REPLACE_WITH_ACM_CERT_ARN|arn:aws-us-gov:acm:us-gov-west-1:123456789:certificate/xxxxx|g' environments/production.yaml.configured
sed -i 's|REPLACE_WITH_DOMAIN|your-domain.com|g' environments/production.yaml.configured
```

### 4. Deploy Application

```bash
# Deploy production
kubectl apply -f environments/production.yaml.configured

# Or deploy all environments
kubectl apply -f environments/
```

### 5. Monitor Deployment

```bash
# Via kubectl
kubectl get applications -n argocd
kubectl describe application chatbot-webapp-production -n argocd

# Via argocd CLI
argocd app get chatbot-webapp-production
argocd app sync chatbot-webapp-production --watch

# Check pods
kubectl get pods -n chatbot-webapp-production
```

## Files

### Base Application
- **`chatbot-webapp.yaml`** - Basic single-environment deployment

### Environment-Specific Applications
- **`environments/dev.yaml`** - Development environment
  - Tracks `develop` branch
  - 1 replica, minimal resources
  - Auto-sync enabled
  
- **`environments/staging.yaml`** - Staging environment
  - Tracks `release` branch
  - 2 replicas, moderate resources
  - Auto-sync enabled
  
- **`environments/production.yaml`** - Production environment
  - Tracks `main` branch
  - 3+ replicas, full resources
  - **Manual sync** (more control)
  - High availability, WAF, monitoring

## Configuration Requirements

Before deploying, you must configure these values in each YAML:

| Placeholder | Example | Where to Find |
|-------------|---------|---------------|
| `REPLACE_WITH_ECR_URL` | `123456789.dkr.ecr.us-gov-west-1.amazonaws.com` | AWS ECR Console |
| `REPLACE_WITH_VERSION` | `v1.0.0` | Your image tag |
| `REPLACE_WITH_API_URL` | `https://api-chatbot.example.com` | API Gateway endpoint |
| `REPLACE_WITH_ACM_CERT_ARN` | `arn:aws-us-gov:acm:us-gov-west-1:...` | AWS ACM Console |
| `REPLACE_WITH_DOMAIN` | `chatbot.example.com` | Your domain name |
| `REPLACE_WITH_WAF_ACL_ARN` | `arn:aws-us-gov:wafv2:...` | AWS WAF Console (prod only) |

## GitOps Workflow

### Development Flow
```
Developer → Git commit → Push to `develop` → ArgoCD auto-syncs → Dev environment updated
```

### Production Flow
```
Developer → Git commit → Push to `main` → ArgoCD detects change → Manual approval → Production updated
```

### Rollback
```
Git revert → Push → ArgoCD auto-syncs → Previous version deployed
```

## Advanced Usage

### App of Apps Pattern

Deploy all environments with one command:

```bash
# Create app-of-apps
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main
    path: argocd/environments
    directory:
      recurse: true
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

### Blue-Green Deployment

```bash
# Deploy blue (current)
kubectl apply -f environments/production.yaml

# Deploy green (new version)
sed 's/chatbot-webapp-production/chatbot-webapp-production-green/g' environments/production.yaml | \
  sed 's/v1.0.0/v1.1.0/g' | \
  kubectl apply -f -

# Test green environment
kubectl port-forward svc/chatbot-webapp-green -n chatbot-webapp-production 8080:80

# Switch traffic (update Ingress to point to green Service)
# ... then delete blue
```

### Canary Deployment

Requires Argo Rollouts:

```bash
# Install Argo Rollouts
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# Use Rollout instead of Deployment in your Helm chart
```

## Troubleshooting

### Application Stuck in "OutOfSync"

```bash
# Force sync
argocd app sync chatbot-webapp-production --force

# Or refresh
argocd app get chatbot-webapp-production --refresh
```

### Pods Not Starting

```bash
# Check events
kubectl get events -n chatbot-webapp-production --sort-by='.lastTimestamp'

# Check pod logs
kubectl logs -l app.kubernetes.io/name=chatbot-webapp -n chatbot-webapp-production

# Check ArgoCD logs
kubectl logs -l app.kubernetes.io/name=argocd-application-controller -n argocd
```

### Image Pull Errors

```bash
# Create ECR pull secret
kubectl create secret docker-registry ecr-secret \
  --docker-server=123456789.dkr.ecr.us-gov-west-1.amazonaws.com \
  --docker-username=AWS \
  --docker-password=$(aws ecr get-login-password --region us-gov-west-1) \
  -n chatbot-webapp-production

# Update application to use secret
# Add to values:
#   webapp:
#     imagePullSecrets:
#       - name: ecr-secret
```

## Notifications

### Slack Integration

Configure ArgoCD notifications:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.slack: |
    token: xoxb-your-slack-token
  
  trigger.on-deployed: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-deployed]
  
  template.app-deployed: |
    message: |
      Application {{.app.metadata.name}} deployed successfully!
    slack:
      attachments: |
        [{
          "title": "{{.app.metadata.name}}",
          "color": "good"
        }]
EOF
```

## GovCloud Considerations

For GovCloud deployments:
- Use `arn:aws-us-gov:` prefix for all ARNs
- Use internal ALB scheme by default
- Add compliance labels and annotations
- Enable security contexts and pod security policies
- Use KMS-encrypted Secrets

See [../docs/govcloud_deployment.md](../docs/govcloud_deployment.md) for details.

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Helm Chart](../helm/chatbot-webapp/)
- [Kubernetes Manifests](../infra/kubernetes/)
- [GovCloud Deployment Guide](../docs/govcloud_deployment.md)
- [Complete ArgoCD Guide](../docs/argocd_deployment.md)
