# Chatbot Webapp Helm Chart - Quick Reference

## Installation

### Prerequisites
```bash
# Verify prerequisites
kubectl version --short
helm version --short
kubectl get nodes
```

### Quick Install (Simple)
```bash
# 1. Create values file
cat > my-values.yaml <<EOF
webapp:
  image:
    repository: "123456789012.dkr.ecr.us-east-1.amazonaws.com/chatbot-webapp"
    tag: "latest"

config:
  chatbotUrl: "https://your-api-gateway.execute-api.us-east-1.amazonaws.com/prod/chatbot/query"

ingress:
  hosts:
    - host: "chatbot.your-domain.com"
      paths:
        - path: /
          pathType: Prefix
  tls:
    certificateArn: "arn:aws:acm:us-east-1:123456789012:certificate/YOUR_CERT"
EOF

# 2. Install
helm install chatbot ./helm/chatbot-webapp -f my-values.yaml

# 3. Check status
kubectl get pods -l app.kubernetes.io/name=chatbot-webapp
kubectl get ingress
```

### Quick Install (with Keycloak)
```bash
# Use the example file
helm install chatbot ./helm/chatbot-webapp \
  -f helm/chatbot-webapp/examples/values-keycloak.yaml \
  --set webapp.image.repository="YOUR_ECR_URL/chatbot-webapp" \
  --set config.chatbotUrl="YOUR_API_GATEWAY_URL" \
  --set ingress.hosts[0].host="chatbot.your-domain.com" \
  --set ingress.tls.certificateArn="YOUR_ACM_CERT_ARN" \
  --set keycloak.ingress.host="keycloak.your-domain.com" \
  --set oauth2Proxy.config.clientSecret="YOUR_CLIENT_SECRET"
```

## Common Commands

```bash
# List releases
helm list

# Get values
helm get values chatbot

# Upgrade
helm upgrade chatbot ./helm/chatbot-webapp -f my-values.yaml

# Rollback
helm rollback chatbot

# Uninstall
helm uninstall chatbot

# Check status
kubectl get all -l app.kubernetes.io/instance=chatbot
kubectl get ingress chatbot-webapp

# View logs
kubectl logs -l app.kubernetes.io/name=chatbot-webapp -f
kubectl logs -l app.kubernetes.io/component=oauth2-proxy -f
kubectl logs -l app.kubernetes.io/component=keycloak -f

# Debug
kubectl describe pod -l app.kubernetes.io/name=chatbot-webapp
kubectl get events --sort-by='.lastTimestamp'
```

## Configuration Examples

### Set Backend URL
```bash
helm upgrade chatbot ./helm/chatbot-webapp \
  --reuse-values \
  --set config.chatbotUrl="https://new-api-url.com/chatbot/query"
```

### Enable Autoscaling
```bash
helm upgrade chatbot ./helm/chatbot-webapp \
  --reuse-values \
  --set webapp.autoscaling.enabled=true \
  --set webapp.autoscaling.maxReplicas=10
```

### Change Image Tag
```bash
helm upgrade chatbot ./helm/chatbot-webapp \
  --reuse-values \
  --set webapp.image.tag="v1.2.3"
```

### Make ALB Public
```bash
helm upgrade chatbot ./helm/chatbot-webapp \
  --reuse-values \
  --set ingress.public=true
```

## Troubleshooting

### Pods Not Running
```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=chatbot-webapp
kubectl describe pod <pod-name>
kubectl logs <pod-name>

# Check image pull
kubectl get events | grep -i "pull"
```

### Can't Access via Ingress
```bash
# Check ingress
kubectl get ingress chatbot-webapp -o yaml
kubectl describe ingress chatbot-webapp

# Check ALB controller
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller

# Get ALB DNS
kubectl get ingress chatbot-webapp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

### Keycloak Admin Password
```bash
kubectl get secret chatbot-webapp-keycloak \
  -o jsonpath='{.data.admin-password}' | base64 -d && echo
```

### OAuth2 Proxy Not Working
```bash
# Check logs
kubectl logs -l app.kubernetes.io/component=oauth2-proxy

# Verify secret
kubectl get secret chatbot-webapp-oauth2-proxy -o yaml

# Check OIDC discovery
curl https://keycloak.your-domain.com/auth/realms/chatbot/.well-known/openid-configuration
```

## Development Workflow

```bash
# 1. Build image
docker build -t your-ecr/chatbot-webapp:dev ./webapp

# 2. Push to registry
docker push your-ecr/chatbot-webapp:dev

# 3. Deploy/update
helm upgrade --install chatbot-dev ./helm/chatbot-webapp \
  -f helm/chatbot-webapp/examples/values-dev.yaml \
  --namespace dev --create-namespace

# 4. Port forward for testing
kubectl port-forward -n dev svc/chatbot-dev-chatbot-webapp 8080:80

# 5. Test
open http://localhost:8080
```

## Package and Share

```bash
# Package chart
helm package ./helm/chatbot-webapp

# Install from package
helm install chatbot chatbot-webapp-1.0.0.tgz -f my-values.yaml

# Generate manifests (without installing)
helm template chatbot ./helm/chatbot-webapp -f my-values.yaml > manifests.yaml
```

## Further Reading

- Full README: [helm/chatbot-webapp/README.md](README.md)
- Examples: [helm/chatbot-webapp/examples/](examples/)
- Keycloak Integration: [docs/keycloak_integration.md](../../docs/keycloak_integration.md)
