#!/usr/bin/env bash
#
# Quick deployment script for chatbot webapp to EKS
#
# Usage: ./deploy_webapp_eks.sh [namespace] [region]
#
set -euo pipefail

NAMESPACE="${1:-default}"
AWS_REGION="${2:-us-gov-west-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check prerequisites
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl not found. Please install kubectl."
    exit 1
fi

if ! command -v aws &> /dev/null; then
    log_error "aws CLI not found. Please install AWS CLI."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    log_error "docker not found. Please install Docker."
    exit 1
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log_info "AWS Account ID: ${AWS_ACCOUNT_ID}"

# ECR repository name and image tag
ECR_REPO="chatbot-webapp"
IMAGE_TAG="${IMAGE_TAG:-latest}"
ECR_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"

log_info "Building Docker image..."

# Build from webapp directory
cd "${REPO_ROOT}/webapp"
docker build -t "${ECR_REPO}:${IMAGE_TAG}" .

log_info "Docker image built successfully"

# Check if ECR repository exists, create if not
log_info "Checking ECR repository..."
if ! aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${AWS_REGION}" &> /dev/null; then
    log_warn "ECR repository ${ECR_REPO} does not exist. Creating..."
    aws ecr create-repository \
        --repository-name "${ECR_REPO}" \
        --region "${AWS_REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256
    log_info "ECR repository created"
else
    log_info "ECR repository exists"
fi

# Login to ECR
log_info "Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Tag and push image
log_info "Tagging image for ECR..."
docker tag "${ECR_REPO}:${IMAGE_TAG}" "${ECR_IMAGE}"

log_info "Pushing image to ECR..."
docker push "${ECR_IMAGE}"

log_info "Image pushed successfully: ${ECR_IMAGE}"

# Update Kubernetes manifests with correct image
cd "${REPO_ROOT}/infra/kubernetes"

log_info "Updating Kubernetes manifests..."
sed -i.bak "s|<ACCOUNT_ID>|${AWS_ACCOUNT_ID}|g" webapp-deployment.yaml
sed -i.bak "s|us-gov-west-1|${AWS_REGION}|g" webapp-deployment.yaml

# Create namespace if it doesn't exist
if [ "${NAMESPACE}" != "default" ]; then
    log_info "Creating namespace ${NAMESPACE} (if not exists)..."
    kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
fi

# Update namespace in manifests
if [ "${NAMESPACE}" != "default" ]; then
    sed -i.bak "s|namespace: default|namespace: ${NAMESPACE}|g" webapp-configmap.yaml
    sed -i.bak "s|namespace: default|namespace: ${NAMESPACE}|g" webapp-deployment.yaml
fi

log_info "Deploying ConfigMap..."
kubectl apply -f webapp-configmap.yaml

log_info "Deploying webapp..."
kubectl apply -f webapp-deployment.yaml

# Wait for rollout
log_info "Waiting for deployment to complete..."
kubectl rollout status deployment/chatbot-webapp -n "${NAMESPACE}" --timeout=5m

# Get service info
log_info "Deployment complete!"
echo ""
log_info "=== Deployment Summary ==="
kubectl get pods -n "${NAMESPACE}" -l app=chatbot-webapp
echo ""
kubectl get svc -n "${NAMESPACE}" chatbot-webapp
echo ""

# Get ingress info if exists
if kubectl get ingress chatbot-webapp -n "${NAMESPACE}" &> /dev/null; then
    log_info "Ingress information:"
    kubectl get ingress chatbot-webapp -n "${NAMESPACE}"
    echo ""
    
    INGRESS_ADDRESS=$(kubectl get ingress chatbot-webapp -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
    if [ "${INGRESS_ADDRESS}" != "pending" ] && [ -n "${INGRESS_ADDRESS}" ]; then
        log_info "Webapp URL: https://${INGRESS_ADDRESS}"
    else
        log_warn "Ingress is still being provisioned. Check status with:"
        echo "  kubectl get ingress chatbot-webapp -n ${NAMESPACE} -w"
    fi
fi

log_info "=== Next Steps ==="
echo "1. Update the ConfigMap with your API Gateway URL:"
echo "   kubectl edit configmap chatbot-webapp-config -n ${NAMESPACE}"
echo ""
echo "2. Monitor logs:"
echo "   kubectl logs -f deployment/chatbot-webapp -n ${NAMESPACE}"
echo ""
echo "3. Port-forward for local testing:"
echo "   kubectl port-forward svc/chatbot-webapp -n ${NAMESPACE} 8080:80"
echo "   Then open: http://localhost:8080"
echo ""

log_info "Done! 🚀"
