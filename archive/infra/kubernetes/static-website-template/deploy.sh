#!/usr/bin/env bash
#
# Generic Static Website Deployment Script for EKS
#
# This script automates the deployment of static websites to Kubernetes/EKS:
#   1. Builds Docker image from your static files
#   2. Creates/uses ECR repository
#   3. Pushes image to ECR
#   4. Generates Kubernetes manifests from template
#   5. Deploys to your EKS cluster
#
# Usage:
#   ./deploy.sh [options]
#
# Options:
#   -n, --name APP_NAME          Application name (required)
#   -s, --source PATH            Path to static files (default: current directory)
#   -N, --namespace NAMESPACE    Kubernetes namespace (default: default)
#   -r, --region REGION          AWS region (default: us-gov-west-1)
#   -d, --domain DOMAIN          Domain name for Ingress (optional)
#   -c, --cert CERT_ARN          ACM certificate ARN (optional)
#   -t, --tag TAG                Image tag (default: latest)
#   -R, --replicas COUNT         Number of replicas (default: 2)
#   --public                     Create internet-facing load balancer (default: internal)
#   --nlb                        Use NLB instead of ALB (default: ALB)
#   --no-push                    Build only, don't push or deploy
#   --dry-run                    Generate manifests but don't apply
#   -h, --help                   Show this help message
#
# Examples:
#   # Deploy blog from ./dist directory
#   ./deploy.sh --name my-blog --source ./dist
#
#   # Deploy with custom domain and HTTPS
#   ./deploy.sh --name docs --domain docs.example.com --cert arn:aws:acm:...
#
#   # Deploy to production namespace with 5 replicas
#   ./deploy.sh --name webapp --namespace production --replicas 5
#
#   # Use NLB instead of ALB
#   ./deploy.sh --name site --nlb
#
#   # Generate manifests without deploying
#   ./deploy.sh --name test --dry-run
#
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}==>${NC} $*"; }

# Default values
APP_NAME=""
SOURCE_PATH="."
NAMESPACE="default"
AWS_REGION="us-gov-west-1"
DOMAIN=""
CERT_ARN=""
IMAGE_TAG="latest"
REPLICAS=2
PUBLIC=false
USE_NLB=false
NO_PUSH=false
DRY_RUN=false

# Parse arguments
show_help() {
    grep '^#' "$0" | grep -v '#!/usr/bin/env' | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name) APP_NAME="$2"; shift 2 ;;
        -s|--source) SOURCE_PATH="$2"; shift 2 ;;
        -N|--namespace) NAMESPACE="$2"; shift 2 ;;
        -r|--region) AWS_REGION="$2"; shift 2 ;;
        -d|--domain) DOMAIN="$2"; shift 2 ;;
        -c|--cert) CERT_ARN="$2"; shift 2 ;;
        -t|--tag) IMAGE_TAG="$2"; shift 2 ;;
        -R|--replicas) REPLICAS="$2"; shift 2 ;;
        --public) PUBLIC=true; shift ;;
        --nlb) USE_NLB=true; shift ;;
        --no-push) NO_PUSH=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) show_help ;;
        *) log_error "Unknown option: $1"; show_help ;;
    esac
done

# Validate required arguments
if [ -z "$APP_NAME" ]; then
    log_error "Application name is required. Use --name or -n"
    exit 1
fi

# Validate source path
if [ ! -d "$SOURCE_PATH" ]; then
    log_error "Source path does not exist: $SOURCE_PATH"
    exit 1
fi

# Check prerequisites
check_prerequisites() {
    local missing=()
    
    command -v docker &> /dev/null || missing+=("docker")
    command -v kubectl &> /dev/null || missing+=("kubectl")
    command -v aws &> /dev/null || missing+=("aws")
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing required tools: ${missing[*]}"
        log_error "Please install them before running this script"
        exit 1
    fi
    
    # Check kubectl connection
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        log_error "Run: kubectl config current-context"
        exit 1
    fi
    
    log_info "Prerequisites check passed ✓"
}

# Get AWS account ID
get_aws_account() {
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        log_error "Failed to get AWS account ID. Check AWS credentials."
        exit 1
    fi
    log_info "AWS Account: ${AWS_ACCOUNT_ID}"
}

# Build Docker image
build_image() {
    log_step "Building Docker image..."
    
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local template_dir="$(dirname "$script_dir")/kubernetes/static-website-template"
    
    # Copy Dockerfile to source directory temporarily
    if [ ! -f "${SOURCE_PATH}/Dockerfile" ]; then
        log_info "Copying Dockerfile template to ${SOURCE_PATH}"
        cp "${template_dir}/Dockerfile" "${SOURCE_PATH}/"
        cp "${template_dir}/.dockerignore" "${SOURCE_PATH}/" 2>/dev/null || true
    fi
    
    # Build from source directory
    cd "$SOURCE_PATH"
    docker build -t "${APP_NAME}:${IMAGE_TAG}" .
    
    log_info "Image built: ${APP_NAME}:${IMAGE_TAG} ✓"
}

# Push to ECR
push_to_ecr() {
    if [ "$NO_PUSH" = true ]; then
        log_warn "Skipping ECR push (--no-push)"
        return
    fi
    
    log_step "Setting up ECR repository..."
    
    ECR_REPO="${APP_NAME}"
    ECR_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
    
    # Create repository if doesn't exist
    if ! aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${AWS_REGION}" &> /dev/null; then
        log_info "Creating ECR repository: ${ECR_REPO}"
        aws ecr create-repository \
            --repository-name "${ECR_REPO}" \
            --region "${AWS_REGION}" \
            --image-scanning-configuration scanOnPush=true \
            --encryption-configuration encryptionType=AES256 \
            > /dev/null
    else
        log_info "ECR repository exists: ${ECR_REPO}"
    fi
    
    # Login to ECR
    log_info "Logging in to ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" > /dev/null
    
    # Tag and push
    log_info "Tagging image for ECR..."
    docker tag "${APP_NAME}:${IMAGE_TAG}" "${ECR_IMAGE}"
    
    log_info "Pushing to ECR (this may take a minute)..."
    docker push "${ECR_IMAGE}" > /dev/null
    
    log_info "Image pushed: ${ECR_IMAGE} ✓"
}

# Generate Kubernetes manifests
generate_manifests() {
    log_step "Generating Kubernetes manifests..."
    
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local template_file="$(dirname "$script_dir")/kubernetes/static-website-template/deployment.yaml"
    local output_file="${APP_NAME}-deployment.yaml"
    
    # Copy template
    cp "$template_file" "$output_file"
    
    # Replace placeholders
    sed -i.bak "s|<APP_NAME>|${APP_NAME}|g" "$output_file"
    sed -i.bak "s|<NAMESPACE>|${NAMESPACE}|g" "$output_file"
    sed -i.bak "s|<IMAGE_URL>|${ECR_IMAGE}|g" "$output_file"
    sed -i.bak "s|replicas: 2|replicas: ${REPLICAS}|g" "$output_file"
    
    # Handle domain
    if [ -n "$DOMAIN" ]; then
        sed -i.bak "s|<DOMAIN>|${DOMAIN}|g" "$output_file"
    else
        # Remove host line if no domain specified
        sed -i.bak '/host: <DOMAIN>/d' "$output_file"
    fi
    
    # Handle certificate
    if [ -n "$CERT_ARN" ]; then
        sed -i.bak "s|<CERT_ARN>|${CERT_ARN}|g" "$output_file"
    else
        # Remove HTTPS-related annotations if no cert
        sed -i.bak '/certificate-arn:/d' "$output_file"
        sed -i.bak '/ssl-policy:/d' "$output_file"
        sed -i.bak 's|\[{"HTTP": 80}, {"HTTPS": 443}\]|[{"HTTP": 80}]|g' "$output_file"
    fi
    
    # Handle public vs internal
    if [ "$PUBLIC" = true ]; then
        sed -i.bak 's|scheme: internal|scheme: internet-facing|g' "$output_file"
    fi
    
    # Handle ALB vs NLB
    if [ "$USE_NLB" = true ]; then
        # Comment out ALB Ingress, uncomment NLB Service
        sed -i.bak '/^apiVersion: networking.k8s.io\/v1/,/^---$/ s/^/# /' "$output_file"
        sed -i.bak '/^# apiVersion: v1$/,/^#     app: <APP_NAME>$/ s/^# //' "$output_file"
    fi
    
    rm -f "${output_file}.bak"
    
    log_info "Generated manifest: ${output_file} ✓"
    echo ""
    log_info "Manifest preview:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    head -n 20 "$output_file" | sed 's/^/  /'
    echo "  ..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Deploy to Kubernetes
deploy_to_k8s() {
    if [ "$DRY_RUN" = true ]; then
        log_warn "Dry run mode - manifests generated but not applied"
        log_info "Review ${APP_NAME}-deployment.yaml and apply with:"
        echo "  kubectl apply -f ${APP_NAME}-deployment.yaml"
        return
    fi
    
    log_step "Deploying to Kubernetes..."
    
    local manifest="${APP_NAME}-deployment.yaml"
    
    # Create namespace if doesn't exist
    if [ "$NAMESPACE" != "default" ]; then
        log_info "Ensuring namespace exists: ${NAMESPACE}"
        kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null
    fi
    
    # Apply manifest
    log_info "Applying manifest..."
    kubectl apply -f "$manifest"
    
    echo ""
    log_info "Waiting for deployment to be ready..."
    kubectl rollout status deployment/"${APP_NAME}" -n "${NAMESPACE}" --timeout=5m
    
    echo ""
    log_info "Deployment complete! ✓"
}

# Show deployment info
show_info() {
    if [ "$DRY_RUN" = true ] || [ "$NO_PUSH" = true ]; then
        return
    fi
    
    echo ""
    log_step "Deployment Information"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    echo ""
    log_info "Pods:"
    kubectl get pods -n "${NAMESPACE}" -l app="${APP_NAME}" -o wide
    
    echo ""
    log_info "Service:"
    kubectl get svc -n "${NAMESPACE}" "${APP_NAME}"
    
    if [ "$USE_NLB" = false ]; then
        echo ""
        log_info "Ingress:"
        if kubectl get ingress "${APP_NAME}-alb" -n "${NAMESPACE}" &> /dev/null; then
            kubectl get ingress "${APP_NAME}-alb" -n "${NAMESPACE}"
            
            # Try to get ALB DNS
            sleep 2
            ALB_DNS=$(kubectl get ingress "${APP_NAME}-alb" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
            if [ -n "$ALB_DNS" ]; then
                echo ""
                if [ -n "$CERT_ARN" ]; then
                    log_info "🌐 Website URL: https://${ALB_DNS}"
                    [ -n "$DOMAIN" ] && log_info "🌐 Custom Domain: https://${DOMAIN}"
                else
                    log_info "🌐 Website URL: http://${ALB_DNS}"
                    [ -n "$DOMAIN" ] && log_info "🌐 Custom Domain: http://${DOMAIN}"
                fi
            else
                log_warn "ALB is being provisioned (this takes 2-3 minutes)..."
                log_info "Check status with: kubectl get ingress ${APP_NAME}-alb -n ${NAMESPACE} -w"
            fi
        fi
    else
        # NLB service
        NLB_DNS=$(kubectl get svc "${APP_NAME}-nlb" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
        if [ -n "$NLB_DNS" ]; then
            echo ""
            log_info "🌐 Website URL: http://${NLB_DNS}"
        else
            log_warn "NLB is being provisioned (this takes 2-3 minutes)..."
            log_info "Check status with: kubectl get svc ${APP_NAME}-nlb -n ${NAMESPACE} -w"
        fi
    fi
    
    echo ""
    log_step "Next Steps"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1. Test locally:"
    echo "     kubectl port-forward svc/${APP_NAME} -n ${NAMESPACE} 8080:80"
    echo "     open http://localhost:8080"
    echo ""
    echo "  2. View logs:"
    echo "     kubectl logs -f deployment/${APP_NAME} -n ${NAMESPACE}"
    echo ""
    echo "  3. Scale replicas:"
    echo "     kubectl scale deployment/${APP_NAME} --replicas=5 -n ${NAMESPACE}"
    echo ""
    echo "  4. Update deployment:"
    echo "     ./deploy.sh --name ${APP_NAME} --tag v2.0.0"
    echo ""
    echo "  5. Delete deployment:"
    echo "     kubectl delete -f ${APP_NAME}-deployment.yaml"
    echo ""
}

# Main execution
main() {
    log_step "Static Website EKS Deployment"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    log_info "Configuration:"
    echo "  App Name:    ${APP_NAME}"
    echo "  Source:      ${SOURCE_PATH}"
    echo "  Namespace:   ${NAMESPACE}"
    echo "  Region:      ${AWS_REGION}"
    echo "  Image Tag:   ${IMAGE_TAG}"
    echo "  Replicas:    ${REPLICAS}"
    echo "  Type:        $([ "$USE_NLB" = true ] && echo "NLB" || echo "ALB")"
    echo "  Access:      $([ "$PUBLIC" = true ] && echo "Public" || echo "Internal")"
    [ -n "$DOMAIN" ] && echo "  Domain:      ${DOMAIN}"
    [ -n "$CERT_ARN" ] && echo "  HTTPS:       Enabled"
    echo ""
    
    check_prerequisites
    get_aws_account
    build_image
    push_to_ecr
    generate_manifests
    deploy_to_k8s
    show_info
    
    echo ""
    log_info "🎉 Done!"
}

main "$@"
