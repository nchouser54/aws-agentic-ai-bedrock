# Kubernetes Manifests

## 🎯 Two Options Available

### Option 1: Chatbot Webapp (This Project)
Deploy the **chatbot webapp** specifically for this project.

### Option 2: Generic Static Website Template ⭐ NEW
Deploy **any static website** to EKS using our reusable template.

---

## Chatbot Webapp Deployment

Deploy the chatbot webapp to your existing EKS cluster.

### Quick Start

```bash
# From repository root
./scripts/deploy_webapp_eks.sh

# Or manually
cd infra/kubernetes
kubectl apply -f webapp-simple.yaml
```

## Files

- **webapp-simple.yaml** - All-in-one manifest (ConfigMap + Deployment + LoadBalancer Service)
  - ✅ Easiest option
  - ✅ No Ingress Controller required
  - ✅ Creates Network Load Balancer automatically
  - Use this if you want the simplest deployment

- **webapp-configmap.yaml** - Configuration for the webapp
  - Runtime settings (API URLs, auth modes, etc.)
  - Can be updated without rebuilding image

- **webapp-deployment.yaml** - Full deployment with Ingress
  - Deployment with 2 replicas
  - ClusterIP Service
  - ALB Ingress with HTTPS/TLS
  - Requires AWS ALB Ingress Controller

## Which File Should I Use?

### Use `webapp-simple.yaml` if:
- ✅ You want the **simplest deployment**
- ✅ You **don't have** ALB Ingress Controller
- ✅ You're okay with a Network Load Balancer
- ✅ You want HTTP or basic HTTPS (with annotations)

### Use `webapp-deployment.yaml` if:
- ✅ You **have** ALB Ingress Controller installed
- ✅ You want **advanced ALB features** (path routing, auth, etc.)
- ✅ You want to share an ALB with other services
- ✅ You need Application Load Balancer instead of Network Load Balancer

## Configuration

Before deploying, update these values:

1. **In webapp-simple.yaml (or webapp-configmap.yaml):**
   ```yaml
   chatbotUrl: "https://<YOUR_API_GATEWAY_URL>/chatbot/query"
   ```

2. **In webapp-deployment.yaml (or webapp-simple.yaml):**
   ```yaml
   image: <ACCOUNT_ID>.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:latest
   ```

3. **Optional - TLS certificate (in webapp-deployment.yaml):**
   ```yaml
   alb.ingress.kubernetes.io/certificate-arn: arn:aws-us-gov:acm:...
   ```

## Deployment

### Option 1: Automated Script (Recommended)

```bash
./scripts/deploy_webapp_eks.sh [namespace] [region]
```

This will:
1. Build Docker image
2. Push to ECR
3. Update manifests
4. Deploy to Kubernetes
5. Show status

### Option 2: Manual Deployment

```bash
# Build and push image
cd webapp
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker build -t chatbot-webapp:latest .
aws ecr get-login-password --region us-gov-west-1 | docker login --username AWS --password-stdin $AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com
docker tag chatbot-webapp:latest $AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:latest
docker push $AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:latest

# Deploy
cd ../infra/kubernetes
kubectl apply -f webapp-simple.yaml

# Check status
kubectl get pods -l app=chatbot-webapp
kubectl get svc chatbot-webapp
```

## Testing

```bash
# Port forward for local testing
kubectl port-forward svc/chatbot-webapp 8080:80
open http://localhost:8080

# Get LoadBalancer URL
kubectl get svc chatbot-webapp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# View logs
kubectl logs -f deployment/chatbot-webapp

# Shell into pod
kubectl exec -it deployment/chatbot-webapp -- sh
```

## Troubleshooting

```bash
# Check pod status
kubectl get pods -l app=chatbot-webapp
kubectl describe pod <POD_NAME>

# View events
kubectl get events --sort-by='.lastTimestamp' | grep chatbot-webapp

# Check logs
kubectl logs deployment/chatbot-webapp --tail=50

# Test from inside pod
kubectl exec -it deployment/chatbot-webapp -- curl http://localhost/
```

## Common Issues

### ImagePullBackOff

Ensure your EKS node IAM role has ECR pull permissions:

```json
{
  "Effect": "Allow",
  "Action": [
    "ecr:GetAuthorizationToken",
    "ecr:BatchCheckLayerAvailability",
    "ecr:GetDownloadUrlForLayer",
    "ecr:BatchGetImage"
  ],
  "Resource": "*"
}
```

### LoadBalancer Stuck in Pending

Check AWS quotas and VPC configuration:

```bash
kubectl describe svc chatbot-webapp
aws elbv2 describe-load-balancers --region us-gov-west-1
```

### 502 Bad Gateway

Pods aren't ready. Check:

```bash
kubectl get pods -l app=chatbot-webapp
kubectl logs deployment/chatbot-webapp
```

## Updating

### Update Configuration Only

```bash
# Edit ConfigMap
kubectl edit configmap chatbot-webapp-config

# Restart pods to pick up changes
kubectl rollout restart deployment/chatbot-webapp
```

### Update Image

```bash
# Build and push new version
docker build -t chatbot-webapp:v2 webapp/
docker tag chatbot-webapp:v2 $AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:v2
docker push $AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:v2

# Update deployment
kubectl set image deployment/chatbot-webapp webapp=$AWS_ACCOUNT.dkr.ecr.us-gov-west-1.amazonaws.com/chatbot-webapp:v2

# Watch rollout
kubectl rollout status deployment/chatbot-webapp
```

## Clean Up

```bash
kubectl delete -f webapp-simple.yaml
# or
kubectl delete deployment,service,configmap -l app=chatbot-webapp
```

## Documentation

- **Chatbot Webapp:** [docs/eks_deployment.md](../../docs/eks_deployment.md)
- **Keycloak Authentication:** [docs/keycloak_integration.md](../../docs/keycloak_integration.md) 🔐
- **Generic Static Sites:** [static-website-template/README.md](static-website-template/README.md)

---

## 🆕 Generic Static Website Template

Want to deploy **any static website** to EKS? We've created a complete, production-ready template!

### ✨ Features

- 🚀 **One-command deployment** for any static site
- 🐳 Works with React, Vue, Angular, Hugo, Jekyll, plain HTML
- ☸️ Production-ready with health checks, scaling, HTTPS
- 📝 Complete documentation and real-world examples
- 🔧 Fully customizable

### Quick Start

```bash
# Deploy any static site
cd infra/kubernetes/static-website-template

# Deploy your React/Vue/Angular app
./deploy.sh --name my-app --source /path/to/build

# With custom domain + HTTPS
./deploy.sh \
  --name my-app \
  --domain www.example.com \
  --cert arn:aws:acm:us-gov-west-1:123456:certificate/abc-123
```

### Documentation

- **[📖 Full Guide](static-website-template/README.md)** - Complete documentation
- **[⚡ Quick Start](static-website-template/QUICK_START.md)** - Get started in 5 minutes  
- **[📚 Examples](static-website-template/EXAMPLES.md)** - Real-world scenarios

### What's Included

```
static-website-template/
├── 📖 README.md          # Complete documentation
├── ⚡ QUICK_START.md     # Quick reference
├── 📚 EXAMPLES.md        # Real-world examples
├── 🐳 Dockerfile         # Generic nginx container
├── 📝 .dockerignore      # Build optimizations
├── ☸️  deployment.yaml   # Kubernetes manifest template
└── 🚀 deploy.sh          # Automated deployment script
```

### Example: Deploy a React App

```bash
# 1. Build your React app
cd my-react-app
npm run build

# 2. Deploy to EKS
cd ../infra/kubernetes/static-website-template
./deploy.sh --name my-react-app --source ../../../my-react-app/build

# That's it! 🎉
```

---
