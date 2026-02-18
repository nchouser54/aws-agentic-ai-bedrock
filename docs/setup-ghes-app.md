# Setting Up the GitHub App on GHES

This guide walks through creating a GitHub App on GitHub Enterprise Server (GHES)
and configuring it to receive pull_request webhooks for the AI PR Reviewer.

---

## Prerequisites

- Admin access to your GHES instance
- The API Gateway webhook URL from Terraform output: `webhook_url`
- A webhook secret (generate one with `openssl rand -hex 32`)

---

## Step 1: Create the GitHub App

1. Navigate to `https://<ghes-hostname>/settings/apps/new` (personal app)
   or `https://<ghes-hostname>/organizations/<org>/settings/apps/new` (org app).

2. Fill in the fields:
   - **GitHub App name:** `ai-pr-reviewer` (must be unique on your GHES instance)
   - **Homepage URL:** your internal documentation URL or `https://example.com`
   - **Webhook URL:** the value of Terraform output `webhook_url`
     (e.g., `https://<api-gw-id>.execute-api.us-gov-west-1.amazonaws.com/webhook/github`)
   - **Webhook secret:** the secret you generated above

3. Under **Permissions → Repository permissions**, set:
   | Permission | Level |
   |---|---|
   | Checks | Read & write |
   | Contents | Read-only |
   | Pull requests | Read & write |
   | Metadata | Read-only (mandatory) |

4. Under **Subscribe to events**, check:
   - `Pull request`

5. Set **Where can this GitHub App be installed?** → **Any account** (or limit to your org).

6. Click **Create GitHub App**.

---

## Step 2: Generate the Private Key

1. On the App settings page, scroll to **Private keys**.
2. Click **Generate a private key**. A `.pem` file will be downloaded.
3. Store the PEM content in AWS Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --secret-id <github_app_private_key_secret_arn from outputs> \
  --secret-string "$(cat ~/Downloads/ai-pr-reviewer.YYYY-MM-DD.private-key.pem)" \
  --region us-gov-west-1
```

---

## Step 3: Store the App ID and Client ID

1. On the App settings page, copy the **App ID** (integer).
2. Store it along with any other App IDs in the IDs secret:

```bash
aws secretsmanager put-secret-value \
  --secret-id <github_app_ids_secret_arn from outputs> \
  --secret-string '{"app_id": "<APP_ID>"}' \
  --region us-gov-west-1
```

---

## Step 4: Store the Webhook Secret

```bash
aws secretsmanager put-secret-value \
  --secret-id <github_webhook_secret_arn from outputs> \
  --secret-string '{"secret": "<WEBHOOK_SECRET>"}' \
  --region us-gov-west-1
```

---

## Step 5: Install the App

1. From the App settings page, click **Install App**.
2. Select the account or organization where you want to install it.
3. Choose **All repositories** or select specific repositories.
4. Click **Install**.
5. After installation, note the **Installation ID** from the URL:
   `https://<ghes>/settings/installations/<INSTALLATION_ID>`
6. Make sure your GHES network allows outbound HTTPS to your API Gateway endpoint.

---

## Step 6: Verify Connectivity

Open a test PR and look for the `AI PR Reviewer` check in the **Checks** tab.
The check should appear within 1–3 minutes.

---

## Firewall Rules

Your GHES instance must be able to reach:
- `https://<api-gw-id>.execute-api.us-gov-west-1.amazonaws.com` (API Gateway)

Your Lambda VPC (if in a VPC) must allow egress to:
- `api.github.com` or `<ghes-hostname>/api/v3` on port 443
- `bedrock-runtime.us-gov-west-1.amazonaws.com` on port 443
- `sqs.us-gov-west-1.amazonaws.com` on port 443
- `secretsmanager.us-gov-west-1.amazonaws.com` on port 443
- `dynamodb.us-gov-west-1.amazonaws.com` on port 443

See also: [private_vpc_operator_quick_card.md](private_vpc_operator_quick_card.md) for VPC endpoint setup.
