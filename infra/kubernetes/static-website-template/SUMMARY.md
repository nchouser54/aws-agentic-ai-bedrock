# Static Website EKS Template - Summary

## 📦 What Was Created

A complete, production-ready template for deploying **any static website** to Kubernetes/EKS.

### Template Files

```
infra/kubernetes/static-website-template/
├── 📖 README.md           # Complete documentation (280+ lines)
├── ⚡ QUICK_START.md      # Quick reference card
├── 📚 EXAMPLES.md         # Real-world examples (400+ lines)
├── 🐳 Dockerfile          # Generic nginx container
├── 📝 .dockerignore       # Build optimizations
├── ☸️  deployment.yaml    # Kubernetes manifest template (300+ lines)
└── 🚀 deploy.sh           # Automated deployment script (500+ lines)
```

### Project-Specific Files (Chatbot Webapp)

```
webapp/
├── Dockerfile             # Chatbot webapp container
└── .dockerignore          # Build exclusions

infra/kubernetes/
├── README.md              # Updated with both options
├── webapp-simple.yaml     # Simple chatbot deployment
├── webapp-deployment.yaml # Advanced chatbot deployment
├── webapp-configmap.yaml  # Chatbot configuration
└── static-website-template/  # Generic template (above)

scripts/
└── deploy_webapp_eks.sh   # Chatbot-specific deployment

docs/
└── eks_deployment.md      # Detailed EKS guide
```

## 🎯 Two Deployment Options

### Option 1: Deploy This Project's Chatbot Webapp

```bash
# Use the project-specific deployment script
./scripts/deploy_webapp_eks.sh

# Or use the simple manifest
kubectl apply -f infra/kubernetes/webapp-simple.yaml
```

**Use this for:** Deploying the chatbot web interface for this project.

### Option 2: Deploy Any Static Website (Template)

```bash
# Copy template to your website project
cp -r infra/kubernetes/static-website-template /path/to/your-site/k8s/

# Deploy your site
cd /path/to/your-site
./k8s/deploy.sh --name my-site --source ./build
```

**Use this for:** 
- React/Vue/Angular applications
- Hugo/Jekyll/Gatsby blogs
- Documentation sites
- Landing pages
- Marketing sites
- Any static HTML/CSS/JS

## 🚀 Quick Start Examples

### Deploy a React App

```bash
# Build React app
cd my-react-app
npm run build

# Deploy to EKS
./infra/kubernetes/static-website-template/deploy.sh \
  --name my-react-app \
  --source ./build \
  --domain app.example.com \
  --cert arn:aws:acm:us-gov-west-1:123456:certificate/abc-123
```

### Deploy a Hugo Blog

```bash
# Build Hugo site
cd my-blog
hugo

# Deploy with public access
./infra/kubernetes/static-website-template/deploy.sh \
  --name blog \
  --source ./public \
  --public
```

### Deploy Plain HTML Site

```bash
# Deploy current directory
cd my-website
./infra/kubernetes/static-website-template/deploy.sh --name my-site
```

## 📚 Documentation Structure

### For Generic Static Sites

1. **[README.md](static-website-template/README.md)** - Start here
   - Complete feature list
   - Prerequisites
   - Full usage guide
   - Configuration options
   - Troubleshooting
   - Production checklist

2. **[QUICK_START.md](static-website-template/QUICK_START.md)** - Quick reference
   - One-line commands
   - Essential options table
   - Common commands
   - Framework-specific examples

3. **[EXAMPLES.md](static-website-template/EXAMPLES.md)** - Real-world scenarios
   - React SPA with routing
   - Vue app with environment variables
   - Hugo blog with custom domain
   - Angular multi-environment setup
   - Documentation sites
   - Blue-green deployments

### For This Project's Chatbot Webapp

- **[docs/eks_deployment.md](../../docs/eks_deployment.md)** - Chatbot-specific guide
- **[infra/kubernetes/README.md](../README.md)** - Quick reference for both options

## 🔑 Key Features

### Automated Deployment Script

The `deploy.sh` script handles everything:

```bash
./deploy.sh --name my-app [options]
```

**What it does:**
1. ✅ Validates prerequisites (kubectl, docker, aws CLI)
2. ✅ Builds Docker image
3. ✅ Creates ECR repository (if needed)
4. ✅ Pushes image to ECR
5. ✅ Generates customized Kubernetes manifests
6. ✅ Deploys to your cluster
7. ✅ Shows deployment status and URLs

### Production-Ready Features

- **High Availability:** Multi-replica with pod anti-affinity
- **Health Checks:** Liveness and readiness probes
- **Zero Downtime:** Rolling update strategy
- **Security:** Security headers, resource limits, HTTPS support
- **Performance:** Static asset caching, gzip compression
- **Monitoring:** Health endpoint at `/health`
- **Scalability:** Easy horizontal scaling

### Flexible Configuration

- ☸️ **Load Balancer:** ALB or NLB
- 🌐 **Access:** Public or internal
- 🔒 **HTTPS:** ACM certificate support
- 📍 **Domain:** Custom domain routing
- 🔢 **Scaling:** Configurable replicas
- 🏷️ **Versioning:** Image tag management

## 💡 Use Cases

### Internal Tools
```bash
./deploy.sh --name admin-dashboard --namespace tools
```

### Public Marketing Site
```bash
./deploy.sh --name landing-page --public --domain www.company.com --cert arn:...
```

### Multi-Environment
```bash
# Dev
./deploy.sh --name app --namespace dev --tag dev

# Staging  
./deploy.sh --name app --namespace staging --tag staging --domain staging.app.com --cert arn:...

# Production
./deploy.sh --name app --namespace prod --tag v1.0.0 --domain app.com --cert arn:... --replicas 5 --public
```

## 📊 Comparison with EC2 Approach

| Feature | EC2 (Old) | EKS Template (New) |
|---------|-----------|-------------------|
| Setup complexity | High (instance, SG, userdata) | Low (one command) |
| Updates | Replace instance | Rolling update |
| Scaling | Manual | Horizontal pod autoscaling |
| High availability | Single instance | Multi-replica |
| Cost | ~$12-14/month | ~$2-5/month (pods only)* |
| Management | Manual | Kubernetes automated |
| Health checks | CloudWatch | Built-in K8s probes |

*Assumes existing EKS cluster. Add ~$20-25/month for Load Balancer.

## 🎓 Learning Resources

### Quick Start Path
1. Read [QUICK_START.md](static-website-template/QUICK_START.md) (5 min)
2. Try basic deployment: `./deploy.sh --name test --dry-run`
3. Review generated manifest
4. Deploy for real: `./deploy.sh --name test`

### Deep Dive Path
1. Read [README.md](static-website-template/README.md) (15 min)
2. Study [EXAMPLES.md](static-website-template/EXAMPLES.md) (20 min)
3. Review [deployment.yaml](static-website-template/deployment.yaml) template
4. Understand [deploy.sh](static-website-template/deploy.sh) automation
5. Customize for your needs

## 🔧 Customization

### Modify Nginx Configuration

Edit [Dockerfile](static-website-template/Dockerfile):

```dockerfile
# Enable SPA routing
RUN echo '... location / { try_files $uri /index.html; } ...'

# Add CORS headers
RUN echo '... add_header Access-Control-Allow-Origin "*"; ...'

# Custom cache rules
RUN echo '... expires 30d; ...'
```

### Adjust Kubernetes Resources

Edit [deployment.yaml](static-website-template/deployment.yaml):

```yaml
# Change replicas
replicas: 5

# Adjust resources
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

# Add environment variables
env:
- name: APP_ENV
  value: "production"
```

### Customize Deployment Script

Edit [deploy.sh](static-website-template/deploy.sh):

```bash
# Change defaults
NAMESPACE="production"  # instead of "default"
REPLICAS=5             # instead of 2

# Add custom logic
# ... your customizations
```

## 🆘 Getting Help

### Check Documentation
1. [README.md](static-website-template/README.md) - Full guide
2. [QUICK_START.md](static-website-template/QUICK_START.md) - Quick reference
3. [EXAMPLES.md](static-website-template/EXAMPLES.md) - Real examples

### Common Issues
- **ImagePullBackOff:** Check EKS node IAM role has ECR permissions
- **CrashLoopBackOff:** Check logs: `kubectl logs <pod>`
- **502 Bad Gateway:** Pods not ready: `kubectl describe pod <pod>`
- **LB Pending:** Check AWS quotas and VPC configuration

### Debugging Commands
```bash
# Pod status
kubectl get pods -l app=my-app

# Logs
kubectl logs -f deployment/my-app

# Events
kubectl get events --sort-by='.lastTimestamp'

# Describe
kubectl describe pod <pod-name>

# Shell into pod
kubectl exec -it <pod-name> -- sh
```

## 🎉 Summary

You now have:

✅ **Generic template** for deploying any static website to EKS
✅ **Automated deployment script** that handles everything
✅ **Complete documentation** with examples and best practices
✅ **Production-ready configuration** with security and performance
✅ **Project-specific setup** for the chatbot webapp

**Next steps:**
1. Choose your deployment option (chatbot or generic template)
2. Read the appropriate documentation
3. Run a test deployment
4. Customize as needed
5. Deploy to production! 🚀

---

**Questions?** Check the comprehensive [README.md](static-website-template/README.md) or [EXAMPLES.md](static-website-template/EXAMPLES.md)
