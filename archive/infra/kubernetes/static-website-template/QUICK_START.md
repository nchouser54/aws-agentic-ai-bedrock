# 🚀 Quick Reference Card

## One-Line Deployments

```bash
# Basic deployment
./deploy.sh --name my-app

# With custom domain + HTTPS
./deploy.sh --name my-app --domain app.com --cert arn:aws:acm:...

# Production setup
./deploy.sh --name my-app --namespace prod --replicas 5 --domain app.com --cert arn:... --public

# Use NLB instead of ALB
./deploy.sh --name my-app --nlb

# Just build, don't deploy
./deploy.sh --name my-app --no-push --dry-run
```

## Common Commands

```bash
# 🔍 Status
kubectl get pods -l app=my-app
kubectl get svc my-app
kubectl get ingress my-app-alb

# 📊 Logs
kubectl logs -f deployment/my-app
kubectl logs deployment/my-app --tail=100

# 🔧 Scale
kubectl scale deployment/my-app --replicas=5

# 🔄 Update
./deploy.sh --name my-app --tag v2.0.0

# ⏮️ Rollback
kubectl rollout undo deployment/my-app

# 🧪 Test locally
kubectl port-forward svc/my-app 8080:80

# 🗑️ Delete
kubectl delete -f my-app-deployment.yaml
```

## File Structure

```
static-website-template/
├── README.md          # Full documentation
├── EXAMPLES.md        # Real-world examples
├── QUICK_START.md     # This file
├── Dockerfile         # Generic nginx container
├── .dockerignore      # Build optimizations
├── deployment.yaml    # Kubernetes manifest template
└── deploy.sh          # Automated deployment script
```

## Essential Options

| Option | Purpose | Example |
|--------|---------|---------|
| `--name` | App name (required) | `--name my-website` |
| `--source` | Static files path | `--source ./build` |
| `--namespace` | K8s namespace | `--namespace production` |
| `--domain` | Custom domain | `--domain www.example.com` |
| `--cert` | ACM certificate ARN | `--cert arn:aws:acm:...` |
| `--replicas` | Number of pods | `--replicas 5` |
| `--tag` | Image version | `--tag v1.2.3` |
| `--public` | Internet-facing LB | `--public` |
| `--nlb` | Use NLB not ALB | `--nlb` |
| `--dry-run` | Generate only | `--dry-run` |

## Framework Quick Start

### React
```bash
npm run build
./deploy.sh --name my-react-app --source ./build
```

### Vue
```bash
npm run build
./deploy.sh --name my-vue-app --source ./dist
```

### Angular
```bash
ng build --configuration=production
./deploy.sh --name my-angular-app --source ./dist/my-app
```

### Hugo
```bash
hugo
./deploy.sh --name my-blog --source ./public
```

### Plain HTML
```bash
./deploy.sh --name my-site --source .
```

## URLs After Deployment

```bash
# Get ALB URL
kubectl get ingress my-app-alb -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Get NLB URL
kubectl get svc my-app-nlb -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Port forward for testing
kubectl port-forward svc/my-app 8080:80
# Then: http://localhost:8080
```

## Troubleshooting

| Error | Fix |
|-------|-----|
| ImagePullBackOff | Check EKS node role has ECR permissions |
| CrashLoopBackOff | Check logs: `kubectl logs <pod>` |
| 502 Bad Gateway | Pods not ready: `kubectl get pods` |
| LB Pending | Check AWS quotas and VPC config |

## Resource Sizes

| Traffic | Replicas | CPU/pod | Memory/pod | Cost/month* |
|---------|----------|---------|------------|------------|
| Low | 2 | 50m | 64Mi | ~$2 |
| Medium | 3 | 100m | 128Mi | ~$5 |
| High | 5 | 200m | 256Mi | ~$15 |

*Pod costs only, excluding LB (~$20-25/month)

## Next Steps

1. ✅ Copy template to your project
2. ✅ Run `./deploy.sh --name my-app`
3. ✅ Get URL: `kubectl get ingress`
4. ✅ Test: `kubectl port-forward svc/my-app 8080:80`
5. ✅ Configure domain + HTTPS
6. ✅ Set up CI/CD

## Help

```bash
# Show all options
./deploy.sh --help

# Check prerequisites
kubectl version
docker version
aws sts get-caller-identity

# Verify cluster access
kubectl cluster-info
kubectl get nodes
```

---

**Full docs:** [README.md](README.md) | **Examples:** [EXAMPLES.md](EXAMPLES.md)
