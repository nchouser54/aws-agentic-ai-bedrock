# Keycloak Integration for EKS Chatbot Deployment

This guide shows how to integrate Keycloak authentication with your chatbot webapp running in EKS.

## 🎯 Integration Options

### Option 1: OAuth2 Proxy (Recommended)
Use OAuth2 Proxy to authenticate all requests before they reach the chatbot webapp.

**Pros:**
- ✅ Zero code changes to webapp
- ✅ Centralized authentication
- ✅ Works with any OAuth2 provider
- ✅ Automatic token refresh

### Option 2: Bearer JWT Tokens
Use Keycloak JWT tokens directly with the webapp's "bearer" auth mode.

**Pros:**
- ✅ Simpler architecture
- ✅ Native webapp support
- ✅ Fine-grained control

### Option 3: Keycloak Gatekeeper (Deprecated but still works)
Use Keycloak's own proxy.

---

## 🚀 Quick Start - Option 1: OAuth2 Proxy (Recommended)

This is the easiest approach - it adds authentication in front of your chatbot without modifying the webapp.

### Architecture

```
User → ALB/Ingress → OAuth2 Proxy → Chatbot Webapp → Backend API
                           ↓
                      Keycloak
```

### Step 1: Deploy Keycloak (Optional if you already have one)

Create `keycloak-deployment.yaml`:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: keycloak

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
  namespace: keycloak
spec:
  replicas: 1
  selector:
    matchLabels:
      app: keycloak
  template:
    metadata:
      labels:
        app: keycloak
    spec:
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:23.0
        args:
        - start-dev
        - --http-relative-path=/auth
        env:
        - name: KEYCLOAK_ADMIN
          value: admin
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-admin
              key: password
        - name: KC_PROXY
          value: edge
        - name: KC_HOSTNAME_STRICT
          value: "false"
        - name: KC_HTTP_ENABLED
          value: "true"
        ports:
        - containerPort: 8080
          name: http
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
        readinessProbe:
          httpGet:
            path: /auth/health/ready
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10

---
apiVersion: v1
kind: Service
metadata:
  name: keycloak
  namespace: keycloak
spec:
  type: ClusterIP
  ports:
  - port: 8080
    targetPort: 8080
    name: http
  selector:
    app: keycloak

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak
  namespace: keycloak
  annotations:
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    alb.ingress.kubernetes.io/certificate-arn: <YOUR_CERT_ARN>
spec:
  ingressClassName: alb
  rules:
  - host: keycloak.your-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: keycloak
            port:
              number: 8080

---
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-admin
  namespace: keycloak
type: Opaque
stringData:
  password: "ChangeMe123!"  # CHANGE THIS!
```

Deploy:

```bash
kubectl apply -f keycloak-deployment.yaml

# Wait for Keycloak to be ready
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=300s

# Get Keycloak URL
kubectl get ingress keycloak -n keycloak
```

### Step 2: Configure Keycloak

Access Keycloak admin console and create:

1. **Create Realm:**
   - Name: `chatbot` (or your company name)

2. **Create Client:**
   - Client ID: `chatbot-webapp`
   - Client Protocol: `openid-connect`
   - Access Type: `confidential`
   - Valid Redirect URIs: `https://chatbot.your-domain.com/oauth2/callback`
   - Web Origins: `https://chatbot.your-domain.com`

3. **Save and get Client Secret** from Credentials tab

4. **Create Roles** (optional):
   - `chatbot-user`
   - `chatbot-admin`

5. **Create Users** and assign roles

### Step 3: Deploy OAuth2 Proxy

Create `oauth2-proxy-deployment.yaml`:

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: oauth2-proxy-secret
  namespace: default
type: Opaque
stringData:
  # Generate with: openssl rand -base64 32
  cookie-secret: "<REPLACE_WITH_RANDOM_32_BYTES>"
  # From Keycloak client credentials tab
  client-id: "chatbot-webapp"
  client-secret: "<KEYCLOAK_CLIENT_SECRET>"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oauth2-proxy
  namespace: default
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
        - --client-id=$(CLIENT_ID)
        - --client-secret=$(CLIENT_SECRET)
        - --cookie-secret=$(COOKIE_SECRET)
        - --email-domain=*
        - --upstream=http://chatbot-webapp:80
        - --http-address=0.0.0.0:4180
        - --redirect-url=https://chatbot.your-domain.com/oauth2/callback
        - --oidc-issuer-url=https://keycloak.your-domain.com/auth/realms/chatbot
        - --cookie-secure=true
        - --cookie-httponly=true
        - --cookie-samesite=lax
        - --pass-authorization-header=true
        - --pass-access-token=true
        - --set-authorization-header=true
        - --skip-provider-button=false
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
        livenessProbe:
          httpGet:
            path: /ping
            port: 4180
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ping
            port: 4180
          initialDelaySeconds: 5
          periodSeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: oauth2-proxy
  namespace: default
spec:
  type: ClusterIP
  ports:
  - port: 4180
    targetPort: 4180
    name: http
  selector:
    app: oauth2-proxy

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: chatbot-webapp-keycloak
  namespace: default
  annotations:
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    alb.ingress.kubernetes.io/certificate-arn: <YOUR_CERT_ARN>
spec:
  ingressClassName: alb
  rules:
  - host: chatbot.your-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: oauth2-proxy  # Routes to proxy, not directly to webapp
            port:
              number: 4180
```

Deploy:

```bash
# Generate cookie secret
COOKIE_SECRET=$(openssl rand -base64 32)
echo "Cookie Secret: $COOKIE_SECRET"

# Update the secret in oauth2-proxy-deployment.yaml
# Then deploy:
kubectl apply -f oauth2-proxy-deployment.yaml

# Check status
kubectl get pods -l app=oauth2-proxy
kubectl logs -f deployment/oauth2-proxy
```

### Step 4: Test

```bash
# Get the chatbot URL
kubectl get ingress chatbot-webapp-keycloak

# Access in browser
open https://chatbot.your-domain.com
```

You should be redirected to Keycloak for login, then back to the chatbot webapp!

---

## 🔐 Option 2: Bearer JWT Tokens (Direct Integration)

Use Keycloak JWT tokens directly with the chatbot webapp.

### Step 1: Deploy Keycloak (same as Option 1)

### Step 2: Configure Keycloak Client

Create client with:
- Client ID: `chatbot-api`
- Access Type: `public` (for frontend apps)
- Direct Access Grants: `Enabled`

### Step 3: Update Webapp ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: chatbot-webapp-config
  namespace: default
data:
  config.js: |
    window.WEBAPP_DEFAULTS = {
      chatbotUrl: "https://api.your-domain.com/chatbot/query",
      authMode: "bearer",  // Use bearer mode
      authValue: "",       // User will login and get JWT
      retrievalMode: "hybrid",
      assistantMode: "contextual",
      llmProvider: "bedrock",
      modelId: "anthropic.claude-3-5-sonnet-20240620-v1:0",
      streamMode: "sse",
      
      // Keycloak configuration
      keycloakUrl: "https://keycloak.your-domain.com/auth",
      keycloakRealm: "chatbot",
      keycloakClientId: "chatbot-api"
    };
```

### Step 4: Add Keycloak Login to Webapp

Create `keycloak-init.js`:

```javascript
// Add to webapp/keycloak-init.js
window.initKeycloak = function() {
  const keycloak = new Keycloak({
    url: window.WEBAPP_DEFAULTS.keycloakUrl,
    realm: window.WEBAPP_DEFAULTS.keycloakRealm,
    clientId: window.WEBAPP_DEFAULTS.keycloakClientId
  });

  keycloak.init({
    onLoad: 'check-sso',
    checkLoginIframe: false
  }).then(authenticated => {
    if (authenticated) {
      // Set bearer token
      document.getElementById('authMode').value = 'bearer';
      document.getElementById('authValue').value = keycloak.token;
      
      // Refresh token before expiry
      setInterval(() => {
        keycloak.updateToken(70).then(refreshed => {
          if (refreshed) {
            document.getElementById('authValue').value = keycloak.token;
          }
        });
      }, 60000);
    } else {
      // Show login button
      document.getElementById('keycloak-login-btn').style.display = 'block';
    }
  });

  // Login button handler
  document.getElementById('keycloak-login-btn').onclick = () => {
    keycloak.login();
  };

  // Logout button handler
  document.getElementById('keycloak-logout-btn').onclick = () => {
    keycloak.logout();
  };
};
```

Update `index.html`:

```html
<head>
  ...
  <script src="https://keycloak.your-domain.com/auth/js/keycloak.js"></script>
  <script src="keycloak-init.js"></script>
</head>
<body onload="initKeycloak()">
  ...
  <button id="keycloak-login-btn" style="display:none">Login with Keycloak</button>
  <button id="keycloak-logout-btn">Logout</button>
  ...
</body>
```

### Step 5: Rebuild and Deploy

```bash
# Rebuild webapp with Keycloak integration
cd webapp
docker build -t chatbot-webapp:keycloak .

# Push and deploy (use your deploy script)
./deploy.sh --name chatbot-webapp --tag keycloak
```

---

## 📋 Complete Example - All-in-One Deployment

Deploy everything at once:

```bash
# 1. Deploy Keycloak
kubectl apply -f keycloak-deployment.yaml

# 2. Wait for Keycloak
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=300s

# 3. Configure Keycloak (manual step - see above)
# - Create realm
# - Create client
# - Create users

# 4. Deploy OAuth2 Proxy
kubectl apply -f oauth2-proxy-deployment.yaml

# 5. Deploy chatbot webapp (if not already deployed)
./scripts/deploy_webapp_eks.sh

# 6. Test
echo "Keycloak: https://$(kubectl get ingress keycloak -n keycloak -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/auth"
echo "Chatbot: https://$(kubectl get ingress chatbot-webapp-keycloak -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
```

---

## 🔧 Configuration Options

### OAuth2 Proxy Additional Args

```yaml
# Restrict to specific email domains
- --email-domain=yourcompany.com

# Require specific groups/roles
- --allowed-group=chatbot-users

# Custom scope
- --scope=openid email profile groups

# Session duration
- --cookie-expire=12h

# Skip certain paths (health checks, static assets)
- --skip-auth-route=^/health$
- --skip-auth-route=^/static/

# Whitelist IPs (internal services)
- --whitelist-domain=.svc.cluster.local
```

### Keycloak Production Settings

For production, use:

1. **External Database** (PostgreSQL):
   ```yaml
   env:
   - name: KC_DB
     value: postgres
   - name: KC_DB_URL
     value: jdbc:postgresql://postgres:5432/keycloak
   - name: KC_DB_USERNAME
     valueFrom:
       secretKeyRef:
         name: keycloak-db
         key: username
   - name: KC_DB_PASSWORD
     valueFrom:
       secretKeyRef:
         name: keycloak-db
         key: password
   ```

2. **Replicas** (min 2 for HA):
   ```yaml
   spec:
     replicas: 2
   ```

3. **Persistent Storage** (if using H2):
   ```yaml
   volumeMounts:
   - name: keycloak-data
     mountPath: /opt/keycloak/data
   volumes:
   - name: keycloak-data
     persistentVolumeClaim:
       claimName: keycloak-pvc
   ```

---

## 🧪 Testing

### Test OAuth2 Proxy

```bash
# Port forward OAuth2 Proxy
kubectl port-forward svc/oauth2-proxy 4180:4180

# Access in browser
open http://localhost:4180

# Should redirect to Keycloak login
```

### Test JWT Token

```bash
# Get token from Keycloak
TOKEN=$(curl -X POST "https://keycloak.your-domain.com/auth/realms/chatbot/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser" \
  -d "password=testpass" \
  -d "grant_type=password" \
  -d "client_id=chatbot-api" \
  | jq -r '.access_token')

# Test chatbot with bearer token
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-domain.com/chatbot/query \
  -d '{"query": "test"}'
```

---

## 🐛 Troubleshooting

### OAuth2 Proxy Logs

```bash
kubectl logs -f deployment/oauth2-proxy

# Common issues:
# - Invalid redirect URI → Check Keycloak client settings
# - Invalid cookie secret → Must be 16, 24, or 32 bytes
# - OIDC discovery failed → Check issuer URL
```

### Keycloak Logs

```bash
kubectl logs -f deployment/keycloak -n keycloak

# Common issues:
# - Database connection → Check KC_DB_URL
# - Memory issues → Increase limits
# - Slow startup → Normal first time (theme compilation)
```

### Webapp Not Receiving Token

```bash
# Check OAuth2 Proxy is passing headers
kubectl exec -it deployment/oauth2-proxy -- env | grep PASS

# Should see:
# PASS_AUTHORIZATION_HEADER=true
# PASS_ACCESS_TOKEN=true
```

---

## 📚 Additional Resources

- [OAuth2 Proxy Documentation](https://oauth2-proxy.github.io/oauth2-proxy/)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Keycloak on Kubernetes](https://www.keycloak.org/getting-started/getting-started-kube)

---

## 🎯 Summary

**Option 1 (OAuth2 Proxy)** is recommended because:
- ✅ No webapp code changes
- ✅ Centralized authentication
- ✅ Easy to add/remove
- ✅ Works with any OAuth2 provider (not just Keycloak)

**Option 2 (Direct JWT)** if you need:
- ✅ Fine-grained control in webapp
- ✅ Token introspection
- ✅ Custom claims handling

Choose based on your needs!
