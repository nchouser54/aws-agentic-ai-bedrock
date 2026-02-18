# Static Website Deployment Template for EKS

Deploy any static website to Kubernetes/EKS with one command. Perfect for:
- React, Vue, Angular, Svelte apps
- Hugo, Jekyll, Gatsby static sites
- Plain HTML/CSS/JavaScript sites
- Documentation sites
- Marketing/landing pages

## ✨ Features

- 🚀 **One-command deployment** - Build, push, and deploy automatically
- 🐳 **Docker-based** - Consistent environments, works anywhere
- ☸️ **Kubernetes-native** - Production-ready with health checks, scaling, rollouts
- 🔒 **Security built-in** - HTTPS, security headers, resource limits
- 📊 **Highly available** - Multi-replica with anti-affinity
- ⚡ **Performance** - Nginx caching, CDN-ready
- 🎯 **Flexible** - ALB or NLB, public or private, custom domains

## 📋 Prerequisites

1. **EKS Cluster** - Running and accessible via kubectl
2. **kubectl** - Configured to access your cluster
3. **Docker** - For building images
4. **AWS CLI** - Configured with credentials
5. **ECR Access** - Permissions to push images

### Optional (for HTTPS with ALB):
6. **AWS Load Balancer Controller** - Installed in your cluster
7. **ACM Certificate** - For HTTPS/TLS

## 🚀 Quick Start

### 1. Copy the Template

```bash
# Copy template to your project
cp -r infra/kubernetes/static-website-template/ my-website/k8s/

# Or download directly
curl -O https://raw.githubusercontent.com/.../static-website-template.tar.gz
tar xzf static-website-template.tar.gz
```

### 2. Build Your Static Site

```bash
# React example
npm run build
# Output in: build/

# Vue example
npm run build
# Output in: dist/

# Hugo example
hugo
# Output in: public/

# Plain HTML
# Just have index.html in current directory
```

### 3. Deploy with One Command

```bash
# From your static site directory (containing index.html or build/dist output)
cd my-website/

# Deploy!
../k8s/deploy.sh --name my-website

# Or specify source path
../k8s/deploy.sh --name my-website --source ./build
```

That's it! Your website is now running on Kubernetes.

## 📖 Usage Guide

### Basic Deployment

```bash
# Minimal (uses current directory)
./deploy.sh --name my-app

# Specify source directory
./deploy.sh --name my-app --source ./dist

# With custom namespace
./deploy.sh --name my-app --namespace production

# With custom domain and HTTPS
./deploy.sh \
  --name my-app \
  --domain www.example.com \
  --cert arn:aws:acm:us-gov-west-1:123456:certificate/abc-123

# Public website (internet-facing)
./deploy.sh --name my-app --public

# Use Network Load Balancer instead of ALB
./deploy.sh --name my-app --nlb

# Production deployment with 5 replicas
./deploy.sh \
  --name my-app \
  --namespace production \
  --replicas 5 \
  --domain www.example.com \
  --cert arn:aws:acm:...
```

### All Options

```bash
./deploy.sh [options]

Options:
  -n, --name NAME          Application name (required)
  -s, --source PATH        Path to static files (default: .)
  -N, --namespace NS       Kubernetes namespace (default: default)
  -r, --region REGION      AWS region (default: us-gov-west-1)
  -d, --domain DOMAIN      Domain for Ingress (optional)
  -c, --cert ARN           ACM certificate ARN (optional)
  -t, --tag TAG            Image tag (default: latest)
  -R, --replicas COUNT     Number of replicas (default: 2)
  --public                 Internet-facing LB (default: internal)
  --nlb                    Use NLB instead of ALB
  --no-push                Build only, skip push/deploy
  --dry-run                Generate manifests only
  -h, --help               Show help
```

## 🏗️ Manual Deployment

If you prefer step-by-step control:

### Step 1: Prepare Your Dockerfile

```bash
# Copy template Dockerfile to your project
cp Dockerfile /path/to/your/website/

# Edit if needed for your project structure
vim Dockerfile
```

For React, update the COPY line:
```dockerfile
COPY build/ /usr/share/nginx/html/
```

For Vue/Angular:
```dockerfile
COPY dist/ /usr/share/nginx/html/
```

### Step 2: Build and Push Image

```bash
cd /path/to/your/website

# Get AWS info
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-gov-west-1"
APP_NAME="my-website"

# Build
docker build -t ${APP_NAME}:latest .

# Create ECR repo (first time only)
aws ecr create-repository --repository-name ${APP_NAME} --region ${AWS_REGION}

# Login
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Tag and push
docker tag ${APP_NAME}:latest ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}:latest
docker push ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}:latest
```

### Step 3: Customize Kubernetes Manifest

```bash
cp deployment.yaml ${APP_NAME}-deployment.yaml
vim ${APP_NAME}-deployment.yaml

# Replace:
#   <APP_NAME> → your-app-name
#   <NAMESPACE> → default (or your namespace)
#   <IMAGE_URL> → AWS_ACCOUNT.dkr.ecr.REGION.amazonaws.com/APP_NAME:latest
#   <DOMAIN> → your-domain.com (or remove host: line)
#   <CERT_ARN> → your ACM certificate ARN (or remove)
```

### Step 4: Deploy

```bash
kubectl apply -f ${APP_NAME}-deployment.yaml

# Watch deployment
kubectl rollout status deployment/${APP_NAME} -n default

# Get URL
kubectl get ingress ${APP_NAME}-alb -n default
```

## 🔧 Configuration

### Nginx Configuration

The Dockerfile includes a production-ready nginx config with:
- ✅ Security headers (X-Frame-Options, CSP, etc.)
- ✅ Static asset caching (1 year for images/css/js)
- ✅ No caching for HTML (always fresh)
- ✅ SPA routing support (commented, uncomment if needed)
- ✅ CORS headers (commented, uncomment if needed)
- ✅ Health check endpoint at `/health`

To customize, edit the Dockerfile or create a separate nginx.conf:

```dockerfile
# In Dockerfile
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

### Resource Limits

Default resource allocation (per pod):

```yaml
resources:
  requests:
    cpu: 50m       # 0.05 CPU cores
    memory: 64Mi   # 64 MB
  limits:
    cpu: 200m      # 0.2 CPU cores max
    memory: 128Mi  # 128 MB max
```

Adjust in `deployment.yaml` based on your site size and traffic.

### Load Balancer Type

**ALB (Application Load Balancer)** - Default
- Layer 7 (HTTP/HTTPS)
- Path-based routing
- Host-based routing
- AWS WAF integration
- Advanced features
- ~$20-25/month

**NLB (Network Load Balancer)** - Use `--nlb` flag
- Layer 4 (TCP/UDP)
- Static IPs
- Ultra-low latency
- Simpler setup
- ~$20-25/month

Choose ALB for most web applications. Use NLB if you need static IPs or raw TCP performance.

## 📊 Monitoring and Management

### View Logs

```bash
# All pods
kubectl logs -f deployment/my-app -n production

# Specific pod
kubectl logs <POD_NAME> -n production

# Last 100 lines
kubectl logs deployment/my-app --tail=100 -n production
```

### Scale Replicas

```bash
# Scale to 5 replicas
kubectl scale deployment/my-app --replicas=5 -n production

# Or edit deployment
kubectl edit deployment/my-app -n production
```

### Update Website

```bash
# Build new version
docker build -t my-app:v2.0.0 .

# Push to ECR
docker tag my-app:v2.0.0 ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/my-app:v2.0.0
docker push ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/my-app:v2.0.0

# Update deployment (rolling update, zero downtime)
kubectl set image deployment/my-app \
  nginx=${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/my-app:v2.0.0 \
  -n production

# Or re-run deploy script
./deploy.sh --name my-app --tag v2.0.0
```

### Rollback

```bash
# View rollout history
kubectl rollout history deployment/my-app -n production

# Rollback to previous version
kubectl rollout undo deployment/my-app -n production

# Rollback to specific revision
kubectl rollout undo deployment/my-app --to-revision=3 -n production
```

### Health Checks

```bash
# Get pod status
kubectl get pods -n production -l app=my-app

# Describe pod (shows events and health checks)
kubectl describe pod <POD_NAME> -n production

# Test health endpoint
kubectl exec -it <POD_NAME> -n production -- curl http://localhost/health
```

## 🐛 Troubleshooting

### ImagePullBackOff

**Problem:** Pods can't pull image from ECR

**Solution:** Check EKS node IAM role has ECR permissions:

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

### CrashLoopBackOff

**Problem:** Container keeps crashing

```bash
# Check logs
kubectl logs <POD_NAME> -n production

# Check previous container
kubectl logs <POD_NAME> --previous -n production

# Check Dockerfile COPY paths match your build output
```

### LoadBalancer Pending

**Problem:** LoadBalancer stuck in pending state

```bash
# Check service
kubectl describe svc my-app -n production

# Check AWS load balancers
aws elbv2 describe-load-balancers --region us-gov-west-1

# Common causes:
# - Insufficient permissions
# - Subnet configuration issues
# - Security group issues
# - AWS service limits reached
```

### 502 Bad Gateway

**Problem:** Load balancer returns 502

```bash
# Check if pods are running
kubectl get pods -n production -l app=my-app

# Check readiness probe
kubectl describe pod <POD_NAME> -n production | grep -A 5 Readiness

# Check logs for errors
kubectl logs deployment/my-app -n production

# Test pod directly
kubectl port-forward <POD_NAME> 8080:80 -n production
curl http://localhost:8080/
```

### Cannot Connect to Cluster

```bash
# Check current context
kubectl config current-context

# List available contexts
kubectl config get-contexts

# Switch context
kubectl config use-context my-cluster

# Update kubeconfig
aws eks update-kubeconfig --name my-cluster --region us-gov-west-1
```

## 📚 Examples

### React App

```bash
# Build React app
cd my-react-app
npm run build

# Deploy
./deploy.sh --name my-react-app --source ./build
```

### Vue App with Custom Domain

```bash
cd my-vue-app
npm run build

./deploy.sh \
  --name my-vue-app \
  --source ./dist \
  --domain app.example.com \
  --cert arn:aws:acm:us-gov-west-1:123456:certificate/abc-123 \
  --namespace production
```

### Hugo Static Site

```bash
cd my-hugo-site
hugo

./deploy.sh --name blog --source ./public --public
```

### Multi-Environment Setup

```bash
# Staging
./deploy.sh --name my-app --namespace staging --tag staging

# Production
./deploy.sh \
  --name my-app \
  --namespace production \
  --tag v1.0.0 \
  --replicas 5 \
  --domain www.example.com \
  --cert arn:aws:acm:...
```

## 🔐 Security Best Practices

1. **Use HTTPS** - Always provide ACM certificate for production
2. **Internal by default** - Use `--public` only when needed
3. **Resource limits** - Set appropriate CPU/memory limits
4. **Keep images updated** - Regularly rebuild with latest base image
5. **Scan images** - ECR image scanning is enabled by default
6. **Network policies** - Add Kubernetes NetworkPolicies for isolation
7. **Secrets** - Never commit credentials, use Kubernetes Secrets

## 💰 Cost Estimation

**Typical small website (2 replicas):**
- EKS cluster: $73/month (but shared with other apps)
- Pods: ~$1-2/month (0.1 vCPU, 128MB RAM per pod)
- Load Balancer: ~$20-25/month
- ECR storage: ~$0.10/month per GB
- Data transfer: $0.09/GB out

**Total:** ~$21-27/month (if EKS cluster already exists)

**Scaling to 10 replicas:** Add ~$5-10/month

## 🎯 Production Checklist

Before going live:

- [ ] Use versioned image tags (not `latest`)
- [ ] Set appropriate replica count (≥2 for HA)
- [ ] Configure HTTPS with ACM certificate
- [ ] Set up proper domain/DNS
- [ ] Review resource limits for your traffic
- [ ] Enable CloudWatch Container Insights
- [ ] Set up monitoring/alerts
- [ ] Test health checks and readiness probes
- [ ] Verify rolling update strategy
- [ ] Document rollback procedure
- [ ] Set up backup/DR plan

## 📖 Additional Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- [EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
- [Nginx Documentation](https://nginx.org/en/docs/)

## 🤝 Contributing

Found a bug or want to improve the template? PRs welcome!

## 📝 License

This template is provided as-is for use in your projects.
