#!/usr/bin/env bash
#
# Deploy Chatbot Webapp with Keycloak OAuth2 Proxy Authentication
#
# This script deploys:
#   1. Keycloak (optional, if you don't have one)
#   2. OAuth2 Proxy for authentication
#   3. Chatbot Webapp
#
# Usage:
#   ./deploy_with_keycloak.sh [options]
#
# Options:
#   --skip-keycloak         Skip Keycloak deployment (use existing)
#   --keycloak-url URL      Existing Keycloak URL
#   --realm REALM           Keycloak realm name (default: chatbot)
#   --client-id ID          Keycloak client ID (default: chatbot-webapp)
#   --client-secret SECRET  Keycloak client secret
#   --domain DOMAIN         Chatbot domain (required)
#   --cert-arn ARN          ACM certificate ARN (required)
#   --namespace NS          Kubernetes namespace (default: default)
#   -h, --help              Show this help

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}==>${NC} $*"; }

# Defaults
SKIP_KEYCLOAK=false
KEYCLOAK_URL=""
REALM="chatbot"
CLIENT_ID="chatbot-webapp"
CLIENT_SECRET=""
DOMAIN=""
CERT_ARN=""
NAMESPACE="default"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-keycloak) SKIP_KEYCLOAK=true; shift ;;
        --keycloak-url) KEYCLOAK_URL="$2"; shift 2 ;;
        --realm) REALM="$2"; shift 2 ;;
        --client-id) CLIENT_ID="$2"; shift 2 ;;
        --client-secret) CLIENT_SECRET="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --cert-arn) CERT_ARN="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        -h|--help) grep '^#' "$0" | grep -v '#!/usr/bin/env' | sed 's/^# \?//'; exit 0 ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate
if [ -z "$DOMAIN" ]; then
    log_error "Domain is required. Use --domain chatbot.your-domain.com"
    exit 1
fi

if [ -z "$CERT_ARN" ]; then
    log_error "Certificate ARN is required. Use --cert-arn arn:aws:acm:..."
    exit 1
fi

log_step "Deploying Chatbot with Keycloak Authentication"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_info "Configuration:"
echo "  Domain:          ${DOMAIN}"
echo "  Namespace:       ${NAMESPACE}"
echo "  Keycloak Realm:  ${REALM}"
echo "  Client ID:       ${CLIENT_ID}"
echo "  Skip Keycloak:   ${SKIP_KEYCLOAK}"
echo ""

# Deploy Keycloak if needed
if [ "$SKIP_KEYCLOAK" = false ]; then
    log_step "Step 1: Deploying Keycloak"
    
    if [ -z "$KEYCLOAK_URL" ]; then
        log_error "If not skipping Keycloak, you need to provide --keycloak-url"
        log_info "Or deploy Keycloak manually first, then use --skip-keycloak"
        exit 1
    fi
    
    log_warn "Keycloak deployment requires manual setup"
    log_info "See docs/keycloak_integration.md for Keycloak deployment YAML"
    echo ""
    read -p "Have you deployed Keycloak to $(echo $KEYCLOAK_URL | sed 's|https://||;s|/.*||')? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Please deploy Keycloak first"
        exit 1
    fi
else
    log_info "Step 1: Skipping Keycloak deployment (using existing)"
fi

# Generate OAuth2 Proxy secrets
log_step "Step 2: Generating OAuth2 Proxy secrets"

if [ -z "$CLIENT_SECRET" ]; then
    log_error "Client secret is required. Get it from Keycloak client credentials."
    log_info "1. Login to Keycloak admin console"
    log_info "2. Go to Clients → ${CLIENT_ID} → Credentials"
    log_info "3. Copy the Secret"
    echo ""
    read -p "Enter Keycloak client secret: " CLIENT_SECRET
fi

COOKIE_SECRET=$(openssl rand -base64 32 | tr -d '\n')
log_info "Generated cookie secret: ${COOKIE_SECRET:0:20}..."

# Create OAuth2 Proxy deployment
log_step "Step 3: Creating OAuth2 Proxy configuration"

cat > /tmp/oauth2-proxy-values.yaml <<EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: oauth2-proxy-secret
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  cookie-secret: "${COOKIE_SECRET}"
  client-id: "${CLIENT_ID}"
  client-secret: "${CLIENT_SECRET}"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oauth2-proxy
  namespace: ${NAMESPACE}
  labels:
    app: oauth2-proxy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: oauth2-proxy
  template:
    metadata:
      labels:
        app: oauth2-proxy
    spec:
      containers:
      - name: oauth2-proxy
        image: quay.io/oauth2-proxy/oauth2-proxy:v7.6.0
        args:
        - --provider=keycloak-oidc
        - --client-id=\$(CLIENT_ID)
        - --client-secret=\$(CLIENT_SECRET)
        - --cookie-secret=\$(COOKIE_SECRET)
        - --email-domain=*
        - --upstream=http://chatbot-webapp:80
        - --http-address=0.0.0.0:4180
        - --redirect-url=https://${DOMAIN}/oauth2/callback
        - --oidc-issuer-url=${KEYCLOAK_URL}/realms/${REALM}
        - --cookie-secure=true
        - --cookie-httponly=true
        - --pass-authorization-header=true
        - --pass-access-token=true
        - --set-authorization-header=true
        env:
        - name: CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: oauth2-proxy-secret
              key: client-id
        - name: CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: oauth2-proxy-secret
              key: client-secret
        - name: COOKIE_SECRET
          valueFrom:
            secretKeyRef:
              name: oauth2-proxy-secret
              key: cookie-secret
        ports:
        - containerPort: 4180
          name: http
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi

---
apiVersion: v1
kind: Service
metadata:
  name: oauth2-proxy
  namespace: ${NAMESPACE}
spec:
  type: ClusterIP
  ports:
  - port: 4180
    targetPort: 4180
  selector:
    app: oauth2-proxy

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: chatbot-webapp-keycloak
  namespace: ${NAMESPACE}
  annotations:
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    alb.ingress.kubernetes.io/certificate-arn: ${CERT_ARN}
spec:
  ingressClassName: alb
  rules:
  - host: ${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: oauth2-proxy
            port:
              number: 4180
EOF

log_info "OAuth2 Proxy configuration ready"

# Apply OAuth2 Proxy
log_step "Step 4: Deploying OAuth2 Proxy"
kubectl apply -f /tmp/oauth2-proxy-values.yaml

log_info "Waiting for OAuth2 Proxy to be ready..."
kubectl rollout status deployment/oauth2-proxy -n ${NAMESPACE} --timeout=3m

# Deploy chatbot webapp if not exists
log_step "Step 5: Checking chatbot webapp deployment"

if ! kubectl get deployment chatbot-webapp -n ${NAMESPACE} &>/dev/null; then
    log_info "Chatbot webapp not found, deploying..."
    
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "${SCRIPT_DIR}/deploy_webapp_eks.sh" ]; then
        ${SCRIPT_DIR}/deploy_webapp_eks.sh ${NAMESPACE}
    else
        log_warn "deploy_webapp_eks.sh not found"
        log_info "Please deploy chatbot webapp manually"
    fi
else
    log_info "Chatbot webapp already deployed ✓"
fi

# Summary
echo ""
log_step "Deployment Complete! 🎉"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

log_info "Services deployed:"
kubectl get pods -n ${NAMESPACE} -l app=oauth2-proxy
kubectl get pods -n ${NAMESPACE} -l app=chatbot-webapp
echo ""

log_info "Ingress:"
kubectl get ingress chatbot-webapp-keycloak -n ${NAMESPACE}
echo ""

# Get ALB DNS
sleep 5
ALB_DNS=$(kubectl get ingress chatbot-webapp-keycloak -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")

if [ "$ALB_DNS" != "pending" ] && [ -n "$ALB_DNS" ]; then
    log_info "🌐 Chatbot URL: https://${DOMAIN}"
    echo ""
    log_info "Next steps:"
    echo "  1. Ensure DNS points ${DOMAIN} → ${ALB_DNS}"
    echo "  2. Access https://${DOMAIN} in browser"
    echo "  3. You'll be redirected to Keycloak for authentication"
    echo "  4. After login, you'll access the chatbot webapp"
else
    log_warn "ALB is being provisioned (takes 2-3 minutes)"
    log_info "Check status with: kubectl get ingress chatbot-webapp-keycloak -n ${NAMESPACE} -w"
fi

echo ""
log_info "Configuration saved to: /tmp/oauth2-proxy-values.yaml"
log_info "Documentation: docs/keycloak_integration.md"
echo ""

# Cleanup
rm -f /tmp/oauth2-proxy-values.yaml

log_info "Done! 🚀"
