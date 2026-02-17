# Making the Chatbot a GitHub App

## Overview

Your chatbot webapp can be integrated as a **GitHub App**, allowing users to:
- ✅ Install it in their repositories
- ✅ Authenticate via GitHub OAuth
- ✅ Access it directly from GitHub's UI
- ✅ Get automatic access based on repo permissions

---

## Option A: GitHub App with External Link (Recommended)

This turns your chatbot into an installable GitHub App that links to your webapp.

### Architecture

```
User → GitHub UI → "Open Chatbot" → Your Webapp (EKS/ArgoCD)
                      ↓
             GitHub OAuth → Authenticated
```

### Step 1: Create GitHub App Manifest

**File: `.github/github-app-manifest.json`**

```json
{
  "name": "AI PR Reviewer Chatbot",
  "url": "https://chatbot.your-domain.com",
  "hook_attributes": {
    "url": "https://api-chatbot.your-domain.com/webhook"
  },
  "redirect_url": "https://chatbot.your-domain.com/auth/callback",
  "description": "Interactive AI chatbot for PR reviews and codebase questions",
  "public": false,
  "default_permissions": {
    "contents": "read",
    "pull_requests": "read",
    "issues": "read",
    "metadata": "read"
  },
  "default_events": [],
  "request_oauth_on_install": true
}
```

### Step 2: Register the GitHub App

```bash
# Method 1: Via GitHub UI
# 1. Go to: https://github.com/settings/apps/new
# 2. Fill in:
#    - Name: "AI PR Reviewer Chatbot"
#    - Homepage URL: https://chatbot.your-domain.com
#    - Callback URL: https://chatbot.your-domain.com/auth/callback
#    - Webhook URL: https://api-chatbot.your-domain.com/webhook
#    - Webhook secret: (generate strong secret)
# 3. Permissions:
#    - Repository contents: Read
#    - Pull requests: Read
#    - Issues: Read
# 4. Create app

# Method 2: Via manifest (faster)
# 1. Go to: https://github.com/settings/apps/new?state=xyz
# 2. Paste manifest from github-app-manifest.json
# 3. Click "Create GitHub App from manifest"
```

**Save these values:**
- App ID
- Client ID
- Client Secret
- Private Key (PEM)

### Step 3: Update Webapp for GitHub OAuth

**File: `webapp/app.js` - Add GitHub OAuth support**

```javascript
// Add at the top of app.js
const GITHUB_APP_CLIENT_ID = 'Iv1.xxxxxxxxx';  // From GitHub App
const GITHUB_OAUTH_REDIRECT = '/auth/callback';

// Add GitHub OAuth login function
async function loginWithGitHub() {
    const redirectUri = window.location.origin + GITHUB_OAUTH_REDIRECT;
    const state = generateRandomState();
    localStorage.setItem('oauth_state', state);
    
    const authUrl = `https://github.com/login/oauth/authorize?` +
        `client_id=${GITHUB_APP_CLIENT_ID}&` +
        `redirect_uri=${encodeURIComponent(redirectUri)}&` +
        `scope=read:user,repo&` +
        `state=${state}`;
    
    window.location.href = authUrl;
}

// Handle OAuth callback
async function handleOAuthCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    const state = urlParams.get('state');
    
    // Verify state
    const savedState = localStorage.getItem('oauth_state');
    if (state !== savedState) {
        showError('OAuth state mismatch');
        return;
    }
    
    // Exchange code for token via your backend
    const response = await fetch('/api/auth/github', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code })
    });
    
    const { access_token } = await response.json();
    localStorage.setItem('github_token', access_token);
    
    // Redirect to main app
    window.location.href = '/';
}

// Update sendMessage to include GitHub token
async function sendMessage() {
    const message = document.getElementById('user-input').value.trim();
    if (!message) return;
    
    const githubToken = localStorage.getItem('github_token');
    
    const response = await fetch(`${CONFIG.chatbotUrl}/chat`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${githubToken}`  // GitHub token
        },
        body: JSON.stringify({
            message: message,
            mode: currentMode
        })
    });
    
    // ... rest of your code
}

// Add login button handler
function checkAuth() {
    const token = localStorage.getItem('github_token');
    if (!token) {
        // Show login button
        showLoginPrompt();
    }
}

// Run on page load
if (window.location.pathname === GITHUB_OAUTH_REDIRECT) {
    handleOAuthCallback();
} else {
    checkAuth();
}
```

**File: `webapp/index.html` - Add login UI**

```html
<!-- Add before the chat container -->
<div id="login-container" class="hidden">
    <div class="login-card">
        <h1>🤖 AI PR Reviewer Chatbot</h1>
        <p>Sign in with GitHub to access the chatbot</p>
        <button onclick="loginWithGitHub()" class="github-login-btn">
            <svg height="20" width="20" viewBox="0 0 16 16">
                <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
            </svg>
            Sign in with GitHub
        </button>
        <p class="privacy-note">
            This app needs access to read your repositories and pull requests.
        </p>
    </div>
</div>

<div id="chat-container" class="hidden">
    <!-- Your existing chat UI -->
</div>
```

**File: `webapp/styles.css` - Add login styles**

```css
.login-card {
    max-width: 400px;
    margin: 100px auto;
    padding: 40px;
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    text-align: center;
}

.github-login-btn {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 12px 24px;
    background: #24292e;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    cursor: pointer;
    transition: background 0.2s;
}

.github-login-btn:hover {
    background: #2f363d;
}

.privacy-note {
    margin-top: 20px;
    font-size: 12px;
    color: #666;
}

.hidden {
    display: none !important;
}
```

### Step 4: Add OAuth Backend (Lambda)

**File: `src/chatbot/github_oauth.py`**

```python
"""
GitHub OAuth handler for chatbot GitHub App integration.
"""

import json
import os
import requests
from typing import Dict, Any

GITHUB_APP_CLIENT_ID = os.environ['GITHUB_APP_CLIENT_ID']
GITHUB_APP_CLIENT_SECRET = os.environ['GITHUB_APP_CLIENT_SECRET']

def exchange_code_for_token(code: str) -> Dict[str, Any]:
    """
    Exchange OAuth code for access token.
    
    Args:
        code: OAuth authorization code from GitHub
        
    Returns:
        Dict with access_token and other OAuth response data
    """
    response = requests.post(
        'https://api.github.com/login/oauth/access_token',
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        json={
            'client_id': GITHUB_APP_CLIENT_ID,
            'client_secret': GITHUB_APP_CLIENT_SECRET,
            'code': code
        }
    )
    
    response.raise_for_status()
    return response.json()


def get_user_info(access_token: str) -> Dict[str, Any]:
    """
    Get GitHub user information.
    
    Args:
        access_token: GitHub OAuth token
        
    Returns:
        Dict with user information
    """
    response = requests.get(
        'https://api.github.com/user',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
    )
    
    response.raise_for_status()
    return response.json()


def verify_token(access_token: str) -> bool:
    """
    Verify GitHub OAuth token is valid.
    
    Args:
        access_token: Token to verify
        
    Returns:
        True if valid, False otherwise
    """
    try:
        response = requests.get(
            'https://api.github.com/user',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
        )
        return response.status_code == 200
    except Exception:
        return False


def lambda_handler(event, context):
    """
    Lambda handler for GitHub OAuth flow.
    
    Routes:
    - POST /api/auth/github - Exchange code for token
    - GET /api/auth/verify - Verify token
    """
    http_method = event['requestContext']['http']['method']
    path = event['requestContext']['http']['path']
    
    if http_method == 'POST' and path == '/api/auth/github':
        # Exchange code for token
        body = json.loads(event['body'])
        code = body.get('code')
        
        if not code:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing code'})
            }
        
        try:
            token_response = exchange_code_for_token(code)
            user_info = get_user_info(token_response['access_token'])
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'access_token': token_response['access_token'],
                    'user': {
                        'login': user_info['login'],
                        'name': user_info.get('name'),
                        'avatar_url': user_info['avatar_url']
                    }
                })
            }
        except Exception as e:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
    
    elif http_method == 'GET' and path == '/api/auth/verify':
        # Verify token
        auth_header = event['headers'].get('authorization', '')
        token = auth_header.replace('Bearer ', '')
        
        if not token:
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'No token provided'})
            }
        
        is_valid = verify_token(token)
        
        return {
            'statusCode': 200 if is_valid else 401,
            'body': json.dumps({'valid': is_valid})
        }
    
    return {
        'statusCode': 404,
        'body': json.dumps({'error': 'Not found'})
    }
```

### Step 5: Update Terraform to Add OAuth Lambda

**File: `infra/terraform/main.tf`**

```hcl
# Add to existing Lambda configurations

resource "aws_lambda_function" "github_oauth" {
  function_name    = "${local.name_prefix}-github-oauth"
  role             = aws_iam_role.chatbot_lambda.arn
  runtime          = "python3.12"
  handler          = "github_oauth.lambda_handler"
  filename         = "${path.module}/../../src/chatbot/github_oauth.zip"
  source_code_hash = filebase64sha256("${path.module}/../../src/chatbot/github_oauth.zip")
  timeout          = 30
  
  environment {
    variables = {
      GITHUB_APP_CLIENT_ID     = var.github_app_client_id
      GITHUB_APP_CLIENT_SECRET = data.aws_secretsmanager_secret_version.github_app_client_secret.secret_string
    }
  }
}

# API Gateway route for OAuth
resource "aws_apigatewayv2_route" "github_oauth" {
  api_id    = aws_apigatewayv2_api.chatbot.id
  route_key = "POST /api/auth/github"
  target    = "integrations/${aws_apigatewayv2_integration.github_oauth.id}"
}

resource "aws_apigatewayv2_integration" "github_oauth" {
  api_id           = aws_apigatewayv2_api.chatbot.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.github_oauth.invoke_arn
}
```

### Step 6: Update Helm Chart for GitHub App

**File: `helm/chatbot-webapp/values.yaml`**

```yaml
# Add GitHub App configuration
githubApp:
  enabled: true
  clientId: ""  # Set via --set or in environment values
  # Client secret stored in Kubernetes secret

# Update ConfigMap
config:
  chatbotUrl: "https://api-chatbot.your-domain.com"
  githubAppEnabled: true
  githubClientId: "{{ .Values.githubApp.clientId }}"
```

### Step 7: Deploy

```bash
# 1. Store GitHub App secrets
kubectl create secret generic github-app-secrets \
  --from-literal=client-id=Iv1.xxxxxxxxx \
  --from-literal=client-secret=your-secret \
  -n chatbot-webapp

# 2. Deploy with Helm
helm upgrade --install chatbot ./helm/chatbot-webapp \
  --set githubApp.enabled=true \
  --set githubApp.clientId=Iv1.xxxxxxxxx

# 3. Or with ArgoCD
kubectl apply -f argocd/environments/production.yaml
```

---

## Option B: GitHub Marketplace App (Public)

To list your chatbot on GitHub Marketplace:

### Requirements
1. GitHub App (from Option A)
2. Pricing tiers defined
3. Terms of service
4. Privacy policy
5. Support documentation

### Steps

```bash
# 1. Complete Option A setup

# 2. Add marketplace manifest
# File: .github/marketplace.yml
---
name: AI PR Reviewer Chatbot
tagline: Interactive AI assistant for code reviews
categories:
  - Code review
  - Productivity
pricing:
  - Free
    description: Up to 100 chats/month
  - Starter ($9/month)
    description: Up to 1,000 chats/month
  - Pro ($49/month)
    description: Unlimited chats

# 3. Submit for review
# GitHub Settings → Apps → Your App → Marketplace → Submit
```

---

## Option C: GitHub Codespaces Integration

Run chatbot inside Codespaces (for developers):

**File: `.devcontainer/devcontainer.json`**

```json
{
  "name": "PR Reviewer with Chatbot",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "forwardPorts": [8080],
  "postCreateCommand": "pip install -r requirements.txt && python scripts/run_chatbot_webapp.py",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python"
      ]
    }
  }
}
```

---

## Summary: GitHub App Integration Options

| Option | Effort | User Experience | SSO | Best For |
|--------|--------|-----------------|-----|----------|
| **A: External Link** | Low | Opens webapp in new tab | ✅ Yes | Quick integration |
| **B: Marketplace** | Medium | Listed publicly | ✅ Yes | Public SaaS |
| **C: Codespaces** | Low | Embedded in IDE | ✅ Yes | Developers |

**Recommendation:** Start with **Option A** - it's the fastest way to make your chatbot a GitHub App with SSO.

---

## Next Steps

1. Register GitHub App (10 minutes)
2. Add OAuth code to webapp (30 minutes)
3. Deploy OAuth Lambda (15 minutes)
4. Update Helm/ArgoCD config (10 minutes)
5. Test installation (5 minutes)

**Total time:** ~1-2 hours to have a working GitHub App! 🚀
