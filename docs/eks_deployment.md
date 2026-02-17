# EKS Deployment Guide for Chatbot Webapp

This guide explains how to deploy the chatbot webapp to an **existing EKS cluster** using Kubernetes instead of EC2.

## Why EKS Instead of EC2?

- ✅ **No EC2 instance management** - Kubernetes handles container lifecycle
- ✅ **Auto-scaling** - Scale pods based on load
- ✅ **High availability** - Multiple replicas across availability zones
- ✅ **Rolling updates** - Zero-downtime deployments
- ✅ **Resource efficiency** - Better utilization with pod scheduling
- ✅ **Existing infrastructure** - Use your current EKS cluster

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ User Browser                                        │
└───────────────┬─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│ AWS ALB (Created by ALB Ingress Controller)         │
│ - HTTPS/443 with ACM certificate                    │
│ - Internal load balancer                            │
└───────────────┬─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│ Kubernetes Service (chatbot-webapp)                 │
│ - ClusterIP type                                    │
│ - Port 80                                           │
└───────────────┬─────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│ Deployment (chatbot-webapp)                         │
│ - 2 replicas (configurable)                         │
│ - Nginx container serving static files              │
│ - ConfigMap for runtime configuration               │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│ Backend API Gateway (Lambda functions)              │
│ - Chatbot, webhook, worker remain as-is            │
└─────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Existing EKS cluster** (already running)
2. **kubectl** configured to access your cluster
3. **AWS CLI** configured with appropriate credentials
4. **Docker** installed for building images
5. **AWS ALB Ingress Controller** installed in your cluster (optional for HTTPS)
6. **ECR repository** access (will be created if doesn't exist)

### Verify Your EKS Cluster

```bash
# Check cluster access
kubectl get nodes

# Check current context
kubectl config current-context

# Check if ALB Ingress Controller is installed (optional)
kubectl get deployment -n kube-system aws-load-balancer-controller
```

## Quick Start - One Command Deployment

The easiest way to deploy:

```bash
# From the repository root
./scripts/deploy_webapp_eks.sh

# Or specify namespace and region
./scripts/deploy_webapp_eks.sh my-namespace us-gov-west-1
```

This script will:
1. ✅ Build the Docker image
2. ✅ Create ECR repository (if needed)
3. ✅ Push image to ECR
4. ✅ Apply Kubernetes manifests
5. ✅ Wait for deployment to complete
6. ✅ Show you the webapp URL

## Manual Deployment Steps

If you prefer step-by-step control:

### Step 1: Build and Push Docker Image

```bash
cd webapp/

# Get your AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-gov-west-1"
ECR_REPO="chatbot-webapp"

# Build image
docker build -t ${ECR_REPO}:latest .

# Create ECR repository (if doesn't exist)
aws ecr create-repository \
    --repository-name ${ECR_REPO} \
    --region ${AWS_REGION} \
    --image-scanning-configuration scanOnPush=true || true

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Tag and push
docker tag ${ECR_REPO}:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest
```

### Step 2: Configure the Deployment

Edit [infra/kubernetes/webapp-configmap.yaml](webapp-configmap.yaml):

```bash
cd infra/kubernetes/

# Update ConfigMap with your API Gateway URL
vim webapp-configmap.yaml
```

**Required changes:**
- `chatbotUrl`: Your API Gateway chatbot endpoint (from Terraform outputs)
- `authMode`: "token", "oauth", or "none"
- `authValue`: Your API token (if using token auth)

Edit [webapp-deployment.yaml](webapp-deployment.yaml):

**Required changes:**
- Replace `<ACCOUNT_ID>` with your AWS account ID
- Replace `<CERT_ID>` in certificate ARN (if using HTTPS ingress)
- Update `namespace` if not using `default`
- Update `host` in Ingress if you have a custom domain

### Step 3: Deploy to Kubernetes

```bash
# Create namespace (if using custom namespace)
kubectl create namespace my-app

# Apply manifests
kubectl apply -f webapp-configmap.yaml
kubectl apply -f webapp-deployment.yaml

# Watch the deployment
kubectl rollout status deployment/chatbot-webapp -n default
```

### Step 4: Access the Webapp

**Option A: Via Ingress (HTTPS with ALB)**

```bash
# Get the ALB DNS name
kubectl get ingress chatbot-webapp -n default

# Access via browser
https://<ALB_DNS_NAME>
```

**Option B: Via Port Forward (for testing)**

```bash
# Forward port 8080 to the webapp
kubectl port-forward svc/chatbot-webapp 8080:80 -n default

# Open browser to
http://localhost:8080
```

**Option C: Via LoadBalancer Service (alternative)**

If you don't have ALB Ingress Controller, edit `webapp-deployment.yaml` and change the Service type:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: chatbot-webapp
spec:
  type: LoadBalancer  # Changed from ClusterIP
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internal"
```

Then apply and get the NLB DNS:
```bash
kubectl apply -f webapp-deployment.yaml
kubectl get svc chatbot-webapp -n default
```

## Configuration

### Update ConfigMap Without Redeploying

You can update the webapp configuration without rebuilding the image:

```bash
# Edit ConfigMap
kubectl edit configmap chatbot-webapp-config -n default

# Restart pods to pick up changes
kubectl rollout restart deployment/chatbot-webapp -n default
```

### Scale Replicas

```bash
# Scale to 5 replicas
kubectl scale deployment chatbot-webapp --replicas=5 -n default

# Or edit the deployment
kubectl edit deployment chatbot-webapp -n default
```

### Update to New Version

```bash
# Build new image with version tag
docker build -t chatbot-webapp:v1.1.0 webapp/
docker tag chatbot-webapp:v1.1.0 ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/chatbot-webapp:v1.1.0
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/chatbot-webapp:v1.1.0

# Update deployment
kubectl set image deployment/chatbot-webapp \
    webapp=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/chatbot-webapp:v1.1.0 \
    -n default

# Watch rollout
kubectl rollout status deployment/chatbot-webapp -n default
```

## Monitoring and Troubleshooting

### View Logs

```bash
# All pods
kubectl logs -f deployment/chatbot-webapp -n default

# Specific pod
kubectl logs <POD_NAME> -n default

# Previous crashed container
kubectl logs <POD_NAME> --previous -n default
```

### Check Pod Status

```bash
# List pods
kubectl get pods -n default -l app=chatbot-webapp

# Describe pod (shows events)
kubectl describe pod <POD_NAME> -n default

# Get pod events
kubectl get events -n default --sort-by='.lastTimestamp' | grep chatbot-webapp
```

### Shell into Pod

```bash
# Get a shell
kubectl exec -it <POD_NAME> -n default -- /bin/sh

# Test nginx
kubectl exec -it <POD_NAME> -n default -- curl http://localhost/

# Check files
kubectl exec -it <POD_NAME> -n default -- ls -la /usr/share/nginx/html/
```

### Common Issues

#### 1. ImagePullBackOff

```bash
# Check pod events
kubectl describe pod <POD_NAME> -n default

# Common causes:
# - ECR authentication expired (re-run: kubectl create secret docker-registry ...)
# - Wrong image URL
# - Wrong region in ECR URL
# - IAM permissions missing for nodes to pull from ECR
```

Solution: Ensure EKS node role has ECR pull permissions:

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

#### 2. CrashLoopBackOff

```bash
# Check logs
kubectl logs <POD_NAME> -n default

# Check previous container logs
kubectl logs <POD_NAME> --previous -n default
```

#### 3. Ingress Not Working

```bash
# Check if ALB Ingress Controller is running
kubectl get deployment -n kube-system aws-load-balancer-controller

# Check ingress status
kubectl describe ingress chatbot-webapp -n default

# Check ALB created
aws elbv2 describe-load-balancers --region us-gov-west-1 | grep chatbot
```

#### 4. 502 Bad Gateway

Usually means pods aren't ready:

```bash
# Check pod status
kubectl get pods -n default -l app=chatbot-webapp

# Check readiness probe
kubectl describe pod <POD_NAME> -n default | grep -A 5 Readiness
```

## Clean Up

```bash
# Delete all webapp resources
kubectl delete -f infra/kubernetes/webapp-deployment.yaml
kubectl delete -f infra/kubernetes/webapp-configmap.yaml

# Or delete by label
kubectl delete deployment,service,ingress,configmap -l app=chatbot-webapp -n default
```

## Cost Comparison

### EC2 Approach
- 1 t3.micro instance: ~$8-10/month (GovCloud)
- Elastic IP: $3.65/month (if not attached 24/7)
- **Total: ~$12-14/month**

### EKS Approach (using existing cluster)
- EKS cluster: **$0** (already exists)
- Container resources: ~$1-2/month (2 small pods)
- ALB: ~$20-25/month (if created for webapp)
- **Total: ~$1-2/month if sharing existing ALB, or ~$22-27/month with dedicated ALB**

**Recommendation:** If you already have an EKS cluster and ALB, this is **much cheaper** and more reliable!

## Integration with Backend

The Kubernetes webapp still connects to your Lambda-based backend:

```
Webapp (EKS) → API Gateway → Lambda (webhook, worker, chatbot, etc.)
```

**No changes needed to your backend infrastructure!** Just update the `chatbotUrl` in the ConfigMap to point to your API Gateway.

## Next Steps

1. ✅ Deploy the webapp: `./scripts/deploy_webapp_eks.sh`
2. ✅ Update ConfigMap with your API Gateway URL
3. ✅ Test: `kubectl port-forward svc/chatbot-webapp 8080:80`
4. ✅ Access: http://localhost:8080
5. ✅ Configure Ingress for HTTPS access (optional)
6. ✅ Set up monitoring with CloudWatch Container Insights (optional)

## Questions?

- **Do I need to change my Terraform?** No, keep your Lambda backend as-is
- **Can I use both EC2 and EKS?** Yes, but choose one for simplicity
- **What about the other Lambda functions?** They stay as Lambda, no changes needed
- **Can I use an existing ALB?** Yes, modify the Ingress annotations to use existing ALB
- **What if I don't have ALB Ingress Controller?** Use LoadBalancer service type instead

## See Also

- [Kubernetes manifests](./infra/kubernetes/)
- [Deployment script](./scripts/deploy_webapp_eks.sh)
- [Original EC2 setup](./docs/SETUP.md)
