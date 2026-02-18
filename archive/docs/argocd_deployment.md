# Deploying with ArgoCD

## Yes, This Works Perfectly with ArgoCD! ✅

This system has **excellent ArgoCD support** since we've already built:
- ✅ Helm charts ([helm/chatbot-webapp/](../helm/chatbot-webapp/))
- ✅ Kubernetes manifests ([infra/kubernetes/](../infra/kubernetes/))
- ✅ GitOps-ready structure

ArgoCD can manage the **chatbot webapp** and **static website** deployments on EKS.

---

## What ArgoCD Manages

### ✅ Ideal for ArgoCD

**1. Chatbot Webapp (EKS)**
- Deployment, Service, Ingress
- ConfigMap for runtime config
- HorizontalPodAutoscaler
- OAuth2 Proxy (optional)
- Keycloak (optional)

**2. Static Websites**
- Generic template deployments
- Multiple environments (dev, staging, prod)

### ❌ NOT Managed by ArgoCD

**Lambda Functions** - These stay in Terraform/CloudFormation:
- Webhook receiver Lambda
- Worker Lambda
- API Gateway
- SQS queues

**Why:** Lambda is serverless infrastructure, not Kubernetes. Use Terraform for this.

---

## Architecture: ArgoCD + This System

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Repository (this repo)                               │
│                                                              │
│  ├── helm/chatbot-webapp/          ← ArgoCD watches this    │
│  ├── infra/kubernetes/             ← ArgoCD watches this    │
│  ├── infra/terraform/              ← Terraform manages      │
│  └── src/                          ← Lambda code            │
└─────────────────────────────────────────────────────────────┘
                     │
                     │ Git pull
          ┌──────────┴─────────────┐
          │                        │
          ▼                        ▼
┌─────────────────┐    ┌──────────────────────┐
│  ArgoCD         │    │  Terraform/GitHub    │
│  (EKS Apps)     │    │  Actions (Lambda)    │
└────────┬────────┘    └──────────────────────┘
         │
         │ Apply manifests
         │
         ▼
┌──────────────────────────────────────────────┐
│  EKS Cluster (GovCloud or Commercial)        │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ Namespace: chatbot-webapp              │ │
│  │                                        │ │
│  │  • Deployment (webapp pods)           │ │
│  │  • Service (ClusterIP)                │ │
│  │  • Ingress (ALB)                      │ │
│  │  • ConfigMap (config.js)              │ │
│  │  • HPA (autoscaling)                  │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ Namespace: oauth2-proxy (optional)     │ │
│  │                                        │ │
│  │  • OAuth2 Proxy deployment            │ │
│  │  • Keycloak deployment                │ │
│  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

---

## ArgoCD Application Configurations

### Option 1: Helm-Based Deployment (Recommended)

**File: `argocd/chatbot-webapp.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  
  # Source: Your Git repo
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main
    path: helm/chatbot-webapp
    helm:
      # Use values file from repo
      valueFiles:
        - values.yaml
      
      # Override values for this environment
      values: |
        webapp:
          image:
            repository: 123456789.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp
            tag: "latest"
            pullPolicy: Always
          
          replicaCount: 2
        
        config:
          chatbotUrl: "https://api-chatbot.your-domain.mil"
          bearerAuth: false
        
        ingress:
          enabled: true
          className: alb
          annotations:
            alb.ingress.kubernetes.io/scheme: internet-facing
            alb.ingress.kubernetes.io/certificate-arn: arn:aws-us-gov:acm:us-gov-west-1:123456789:certificate/xxxxx
            alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
          hosts:
            - host: chatbot.your-domain.mil
              paths:
                - path: /
                  pathType: Prefix
          tls:
            certificateArn: arn:aws-us-gov:acm:us-gov-west-1:123456789:certificate/xxxxx
        
        autoscaling:
          enabled: true
          minReplicas: 2
          maxReplicas: 10
          targetCPUUtilizationPercentage: 70
        
        oauth2Proxy:
          enabled: false  # Enable if you need Keycloak
        
        keycloak:
          enabled: false
  
  # Destination: EKS cluster
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp
  
  # Sync policy
  syncPolicy:
    automated:
      prune: true      # Delete resources not in Git
      selfHeal: true   # Auto-sync if cluster state drifts
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  
  # Health checks
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas  # Ignore HPA-managed replicas
```

### Option 2: Kustomize-Based Deployment

**File: `argocd/chatbot-webapp-kustomize.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-kustomize
  namespace: argocd
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main
    path: infra/kubernetes/kustomize/overlays/production
    kustomize:
      images:
        - name: chatbot-webapp
          newName: 123456789.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp
          newTag: v1.2.3
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Option 3: Plain Manifests

**File: `argocd/chatbot-webapp-plain.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-plain
  namespace: argocd
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main
    path: infra/kubernetes
    directory:
      recurse: true
      include: 'webapp-*.yaml'  # Only webapp files
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

## Multi-Environment Setup

### Environment-Specific Applications

**File: `argocd/environments/dev.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-dev
  namespace: argocd
  labels:
    environment: dev
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: develop  # Dev branch
    path: helm/chatbot-webapp
    helm:
      valueFiles:
        - values.yaml
        - examples/values-dev.yaml  # Dev-specific values
      values: |
        webapp:
          image:
            tag: "develop-latest"
          replicaCount: 1  # Lower for dev
        
        config:
          chatbotUrl: "https://dev-api-chatbot.your-domain.mil"
        
        ingress:
          hosts:
            - host: dev-chatbot.your-domain.mil
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp-dev
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**File: `argocd/environments/staging.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-staging
  namespace: argocd
  labels:
    environment: staging
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: release  # Release branch
    path: helm/chatbot-webapp
    helm:
      valueFiles:
        - values.yaml
      values: |
        webapp:
          image:
            tag: "v1.2.3-rc1"
          replicaCount: 2
        
        config:
          chatbotUrl: "https://staging-api-chatbot.your-domain.mil"
        
        ingress:
          hosts:
            - host: staging-chatbot.your-domain.mil
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp-staging
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**File: `argocd/environments/production.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-production
  namespace: argocd
  labels:
    environment: production
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main  # Production from main
    path: helm/chatbot-webapp
    helm:
      valueFiles:
        - values.yaml
        - examples/values-production.yaml
      values: |
        webapp:
          image:
            tag: "v1.2.3"  # Specific version, not latest
          replicaCount: 3
        
        config:
          chatbotUrl: "https://api-chatbot.your-domain.mil"
        
        ingress:
          hosts:
            - host: chatbot.your-domain.mil
        
        autoscaling:
          enabled: true
          minReplicas: 3
          maxReplicas: 20
        
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
            cpu: "500m"
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp-production
  
  syncPolicy:
    # Manual sync for production (more control)
    automated:
      prune: false  # Don't auto-delete in prod
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

---

## App of Apps Pattern

**File: `argocd/app-of-apps.yaml`**

Manage all environments from one application:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-apps
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
```

This will automatically create ArgoCD applications for dev, staging, and production.

---

## ArgoCD Project Configuration

**File: `argocd/project.yaml`**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: chatbot-webapp
  namespace: argocd
spec:
  description: PR Reviewer Chatbot Webapp
  
  # Source repos allowed
  sourceRepos:
    - https://github.com/nchouser54/aws-agentic-ai-bedrock.git
  
  # Destination clusters/namespaces allowed
  destinations:
    - namespace: 'chatbot-webapp*'
      server: https://kubernetes.default.svc
    - namespace: oauth2-proxy
      server: https://kubernetes.default.svc
    - namespace: keycloak
      server: https://kubernetes.default.svc
  
  # Allowed resource types
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: 'rbac.authorization.k8s.io'
      kind: ClusterRole
    - group: 'rbac.authorization.k8s.io'
      kind: ClusterRoleBinding
  
  namespaceResourceWhitelist:
    - group: '*'
      kind: '*'
  
  # Roles for RBAC
  roles:
    - name: developer
      description: Developers can sync dev environment
      policies:
        - p, proj:chatbot-webapp:developer, applications, sync, chatbot-webapp/chatbot-webapp-dev, allow
        - p, proj:chatbot-webapp:developer, applications, get, chatbot-webapp/*, allow
      groups:
        - engineering-team
    
    - name: deployer
      description: Full access to all environments
      policies:
        - p, proj:chatbot-webapp:deployer, applications, *, chatbot-webapp/*, allow
      groups:
        - devops-team
```

---

## Deployment Workflow with ArgoCD

### 1. Install ArgoCD on EKS

```bash
# Create namespace
kubectl create namespace argocd

# Install ArgoCD
kubectl apply -n argocd -f \
  https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available --timeout=300s \
  deployment/argocd-server -n argocd

# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# Port-forward to access UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Login via CLI
argocd login localhost:8080 --username admin --password <from-above>

# Change password
argocd account update-password
```

### 2. Add Your Repository

```bash
# Add Git repo (public)
argocd repo add https://github.com/nchouser54/aws-agentic-ai-bedrock.git

# Or add with SSH key (private repo)
argocd repo add git@github.com:nchouser54/aws-agentic-ai-bedrock.git \
  --ssh-private-key-path ~/.ssh/id_rsa

# Or add with HTTPS credentials
argocd repo add https://github.com/nchouser54/aws-agentic-ai-bedrock.git \
  --username <github-username> \
  --password <github-token>
```

### 3. Deploy Applications

```bash
# Create ArgoCD application from file
kubectl apply -f argocd/chatbot-webapp.yaml

# Or create via CLI
argocd app create chatbot-webapp \
  --repo https://github.com/nchouser54/aws-agentic-ai-bedrock.git \
  --path helm/chatbot-webapp \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace chatbot-webapp \
  --helm-set webapp.image.repository=123456789.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp \
  --helm-set webapp.image.tag=latest \
  --helm-set config.chatbotUrl=https://api-chatbot.your-domain.mil \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Deploy all environments
kubectl apply -f argocd/environments/
```

### 4. Monitor Deployment

```bash
# Check application status
argocd app get chatbot-webapp

# Watch sync progress
argocd app sync chatbot-webapp --watch

# View application in UI
open https://localhost:8080/applications/chatbot-webapp

# Check pod status
kubectl get pods -n chatbot-webapp
```

### 5. Rollback if Needed

```bash
# View application history
argocd app history chatbot-webapp

# Rollback to previous version
argocd app rollback chatbot-webapp <revision-id>

# Or rollback via Git
git revert <commit-hash>
git push origin main
# ArgoCD auto-syncs and deploys previous version
```

---

## GitOps Workflow

### Developer Workflow

```bash
# 1. Make changes to Helm chart or manifests
cd helm/chatbot-webapp
vim values.yaml  # Change image tag, config, etc.

# 2. Test locally (optional)
helm template . --values values.yaml

# 3. Commit and push
git add .
git commit -m "Update chatbot webapp to v1.2.4"
git push origin main

# 4. ArgoCD detects change and syncs automatically
# (if automated sync is enabled)

# 5. Monitor deployment
argocd app get chatbot-webapp
kubectl get pods -n chatbot-webapp -w
```

### Blue-Green Deployment

```yaml
# argocd/blue-green.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-blue
spec:
  # ... same as before ...
  source:
    helm:
      values: |
        webapp:
          image:
            tag: "v1.2.3"  # Current version
        
        service:
          name: chatbot-webapp-blue

---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-green
spec:
  # ... same as before ...
  source:
    helm:
      values: |
        webapp:
          image:
            tag: "v1.2.4"  # New version
        
        service:
          name: chatbot-webapp-green

# Switch traffic by updating Ingress to point to green service
```

### Canary Deployment with Argo Rollouts

```yaml
# argocd/rollout.yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: chatbot-webapp
spec:
  replicas: 5
  strategy:
    canary:
      steps:
        - setWeight: 20   # 20% traffic to new version
        - pause: {duration: 5m}
        - setWeight: 40
        - pause: {duration: 5m}
        - setWeight: 60
        - pause: {duration: 5m}
        - setWeight: 80
        - pause: {duration: 5m}
  template:
    spec:
      containers:
        - name: webapp
          image: chatbot-webapp:v1.2.4
```

---

## ArgoCD with GovCloud

### GovCloud-Specific Configuration

```yaml
# argocd/chatbot-webapp-govcloud.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chatbot-webapp-govcloud
  namespace: argocd
  labels:
    compliance: fedramp
    classification: sensitive
spec:
  project: default
  
  source:
    repoURL: https://github.com/nchouser54/aws-agentic-ai-bedrock.git
    targetRevision: main
    path: helm/chatbot-webapp
    helm:
      values: |
        webapp:
          image:
            repository: 123456789.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp
            tag: "v1.2.3"
          
          # Compliance annotations
          podAnnotations:
            compliance: "fedramp-moderate"
            classification: "sensitive"
            iam.amazonaws.com/role: arn:aws-us-gov:iam::123456789:role/chatbot-webapp
        
        ingress:
          annotations:
            # GovCloud ALB
            alb.ingress.kubernetes.io/scheme: internal  # Internal-only
            alb.ingress.kubernetes.io/certificate-arn: arn:aws-us-gov:acm:us-gov-west-1:123456789:certificate/xxxxx
            alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws-us-gov:wafv2:us-gov-west-1:123456789:regional/webacl/xxxxx
            alb.ingress.kubernetes.io/security-groups: sg-xxxxx
          hosts:
            - host: chatbot.internal.mil
        
        # Security context (FedRAMP requirement)
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          fsGroup: 1000
          seccompProfile:
            type: RuntimeDefault
        
        containerSecurityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
              - ALL
  
  destination:
    server: https://kubernetes.default.svc
    namespace: chatbot-webapp
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

## Monitoring and Alerting

### Prometheus Metrics

ArgoCD exposes metrics for monitoring:

```yaml
# prometheus-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: argocd-metrics
  namespace: argocd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  endpoints:
    - port: metrics
      interval: 30s
```

### Grafana Dashboard

Import ArgoCD dashboard ID: **14584**

### Slack Notifications

```yaml
# argocd-notifications-cm.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.slack: |
    token: $slack-token
  
  trigger.on-deployed: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-deployed]
  
  trigger.on-health-degraded: |
    - when: app.status.health.status == 'Degraded'
      send: [app-health-degraded]
  
  template.app-deployed: |
    message: |
      Application {{.app.metadata.name}} deployed successfully!
      Revision: {{.app.status.sync.revision}}
    slack:
      attachments: |
        [{
          "title": "Application Deployed",
          "color": "good"
        }]
```

---

## Troubleshooting

### Issue: ArgoCD Can't Reach Git Repo

**Symptoms:** "Unable to resolve repository"

**Solution:**
```bash
# Check repo credentials
argocd repo list

# Re-add with correct credentials
argocd repo add https://github.com/nchouser54/aws-agentic-ai-bedrock.git \
  --username <github-username> \
  --password <github-pat>
```

### Issue: Application Stuck in Progressing

**Symptoms:** App shows "Progressing" for extended time

**Solution:**
```bash
# Check for failing pods
kubectl get pods -n chatbot-webapp

# Check pod events
kubectl describe pod <pod-name> -n chatbot-webapp

# Check application events
argocd app get chatbot-webapp --show-operation
```

### Issue: Image Pull Errors

**Symptoms:** "ErrImagePull" or "ImagePullBackOff"

**Solution:**
```bash
# Check ECR credentials
kubectl get secret -n chatbot-webapp

# Create ECR pull secret
kubectl create secret docker-registry ecr-secret \
  --docker-server=123456789.dkr.ecr.us-gov-west-1.amazonaws.com \
  --docker-username=AWS \
  --docker-password=$(aws ecr get-login-password --region us-gov-west-1) \
  -n chatbot-webapp

# Add to Helm values
helm upgrade chatbot ./helm/chatbot-webapp \
  --set webapp.imagePullSecrets[0].name=ecr-secret
```

---

## Summary: ArgoCD Integration

| Component | ArgoCD Compatible | Deployment Method |
|-----------|-------------------|-------------------|
| Chatbot Webapp | ✅ Yes | Helm or Kubernetes manifests |
| Static Website Template | ✅ Yes | Kubernetes manifests |
| OAuth2 Proxy | ✅ Yes | Included in Helm chart |
| Keycloak | ✅ Yes | Included in Helm chart |
| Lambda Functions | ❌ No | Use Terraform/CDK |
| API Gateway | ❌ No | Use Terraform/CDK |

**Best Practice:**
- **ArgoCD**: Manage Kubernetes workloads (webapp, Keycloak)
- **Terraform**: Manage AWS infrastructure (Lambda, API Gateway, SQS)
- **Git**: Single source of truth for both

**Benefits:**
- 🔄 GitOps workflow (Git as source of truth)
- 🔍 Declarative deployments
- 🎯 Automated sync and drift detection
- 🔙 Easy rollbacks
- 👀 Visual deployment status
- 🔐 RBAC and audit logs
- 🌍 Multi-cluster support
