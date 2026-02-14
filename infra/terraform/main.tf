locals {
  name_prefix                       = "${var.project_name}-${var.environment}"
  chatbot_auth_jwt_enabled          = var.chatbot_enabled && var.chatbot_auth_mode == "jwt"
  chatbot_auth_github_oauth_enabled = var.chatbot_enabled && var.chatbot_auth_mode == "github_oauth"
  chatbot_memory_enabled            = var.chatbot_enabled && var.chatbot_memory_enabled
  chatbot_websocket_enabled         = var.chatbot_enabled && var.chatbot_websocket_enabled
  webapp_hosting_enabled            = var.webapp_hosting_enabled
  webapp_hosting_mode               = trimspace(var.webapp_hosting_mode)
  webapp_s3_enabled                 = local.webapp_hosting_enabled && local.webapp_hosting_mode == "s3"
  webapp_ec2_enabled                = local.webapp_hosting_enabled && local.webapp_hosting_mode == "ec2_eip"
  webapp_private_only               = local.webapp_ec2_enabled && var.webapp_private_only
  webapp_tls_enabled                = local.webapp_ec2_enabled && var.webapp_tls_enabled
  webapp_bucket_name                = trimspace(var.webapp_bucket_name) != "" ? trimspace(var.webapp_bucket_name) : "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-chatbot-webapp"
  webapp_files = {
    "index.html" = {
      source       = "${path.module}/../../webapp/index.html"
      content_type = "text/html"
    }
    "config.js" = {
      source       = "${path.module}/../../webapp/config.js"
      content_type = "application/javascript"
    }
    "app.js" = {
      source       = "${path.module}/../../webapp/app.js"
      content_type = "application/javascript"
    }
    "styles.css" = {
      source       = "${path.module}/../../webapp/styles.css"
      content_type = "text/css"
    }
  }
  chatbot_metrics_namespace = trimspace(var.chatbot_metrics_namespace) != "" ? trimspace(var.chatbot_metrics_namespace) : "${var.project_name}/${var.environment}"
  chatbot_route_auth_type   = local.chatbot_auth_jwt_enabled ? "JWT" : local.chatbot_auth_github_oauth_enabled ? "CUSTOM" : "NONE"
  kb_sync_any_enabled       = var.kb_sync_enabled || var.github_kb_sync_enabled
  webapp_default_config = {
    chatbotUrl         = trimspace(var.webapp_default_chatbot_url) != "" ? trimspace(var.webapp_default_chatbot_url) : "${aws_apigatewayv2_api.webhook.api_endpoint}/chatbot/query"
    authMode           = var.webapp_default_auth_mode
    retrievalMode      = "hybrid"
    assistantMode      = "contextual"
    llmProvider        = "bedrock"
    streamMode         = "true"
    githubOauthBaseUrl = trimspace(var.webapp_default_github_oauth_base_url)
    githubClientId     = trimspace(var.webapp_default_github_client_id)
    githubScope        = trimspace(var.webapp_default_github_scope)
    githubAllowedOrgs  = var.github_oauth_allowed_orgs
  }
}

locals {
  webapp_tls_subnet_map = local.webapp_tls_enabled ? { for idx, subnet_id in var.webapp_tls_subnet_ids : tostring(idx) => subnet_id } : {}
  lambda_tracing_mode   = var.lambda_tracing_enabled ? "Active" : "PassThrough"
  worker_concurrency    = var.lambda_reserved_concurrency_worker >= 0 ? var.lambda_reserved_concurrency_worker : null
  chatbot_concurrency   = var.lambda_reserved_concurrency_chatbot >= 0 ? var.lambda_reserved_concurrency_chatbot : null
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

# Managed policy for X-Ray tracing — attached to all Lambda roles
data "aws_iam_policy" "xray_write" {
  count = var.lambda_tracing_enabled ? 1 : 0
  name  = "AWSXRayDaemonWriteAccess"
}

data "aws_subnet" "webapp" {
  count = local.webapp_ec2_enabled ? 1 : 0
  id    = var.webapp_ec2_subnet_id
}

data "aws_ssm_parameter" "webapp_ami" {
  count = local.webapp_ec2_enabled && trimspace(var.webapp_ec2_ami_id) == "" ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2"
}

check "chatbot_jwt_settings" {
  assert {
    condition = (
      var.chatbot_auth_mode != "jwt" ||
      (
        length(trimspace(var.chatbot_jwt_issuer)) > 0 &&
        length(var.chatbot_jwt_audience) > 0
      )
    )
    error_message = "When chatbot_auth_mode is jwt, set both chatbot_jwt_issuer and chatbot_jwt_audience."
  }
}

check "github_kb_sync_settings" {
  assert {
    condition = (
      !var.github_kb_sync_enabled ||
      (
        length(var.github_kb_repos) > 0 &&
        (
          length(trimspace(var.github_kb_data_source_id)) > 0 ||
          length(trimspace(var.bedrock_kb_data_source_id)) > 0
        )
      )
    )
    error_message = "When github_kb_sync_enabled is true, set github_kb_repos and at least one data source id (github_kb_data_source_id or bedrock_kb_data_source_id)."
  }
}

check "webapp_ec2_settings" {
  assert {
    condition = (
      !local.webapp_ec2_enabled ||
      length(trimspace(var.webapp_ec2_subnet_id)) > 0
    )
    error_message = "When webapp_hosting_enabled=true and webapp_hosting_mode=ec2_eip, set webapp_ec2_subnet_id."
  }
}

check "webapp_private_only_settings" {
  assert {
    condition = (
      !var.webapp_private_only ||
      var.webapp_hosting_enabled && trimspace(var.webapp_hosting_mode) == "ec2_eip"
    )
    error_message = "webapp_private_only requires webapp_hosting_enabled=true and webapp_hosting_mode=ec2_eip."
  }
}

check "webapp_tls_settings" {
  assert {
    condition = (
      !local.webapp_tls_enabled ||
      (
        length(trimspace(var.webapp_tls_acm_certificate_arn)) > 0 &&
        length(var.webapp_tls_subnet_ids) > 0
      )
    )
    error_message = "When webapp_tls_enabled=true, set webapp_tls_acm_certificate_arn and at least one webapp_tls_subnet_ids entry."
  }
}

check "webapp_s3_not_private_only" {
  assert {
    condition = (
      !var.webapp_private_only ||
      trimspace(var.webapp_hosting_mode) != "s3"
    )
    error_message = "webapp_private_only is incompatible with webapp_hosting_mode=s3. S3 website hosting uses a public endpoint. Use webapp_hosting_mode=ec2_eip for private deployments."
  }
}

resource "aws_kms_key" "app" {
  description             = "KMS key for ${local.name_prefix} secrets and data"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "app" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.app.key_id
}

resource "aws_secretsmanager_secret" "github_webhook_secret" {
  name                    = "${local.name_prefix}/github_webhook_secret"
  description             = "GitHub webhook signing secret"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "github_webhook_secret" {
  secret_id     = aws_secretsmanager_secret.github_webhook_secret.id
  secret_string = "REPLACE_ME_WITH_GITHUB_WEBHOOK_SECRET"
}

resource "aws_secretsmanager_secret" "github_app_private_key_pem" {
  name                    = "${local.name_prefix}/github_app_private_key_pem"
  description             = "GitHub App private key PEM"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "github_app_private_key_pem" {
  secret_id     = aws_secretsmanager_secret.github_app_private_key_pem.id
  secret_string = "-----BEGIN PRIVATE KEY-----\nREPLACE_ME\n-----END PRIVATE KEY-----"
}

resource "aws_secretsmanager_secret" "github_app_ids" {
  name                    = "${local.name_prefix}/github_app_ids"
  description             = "GitHub App IDs JSON: { app_id, installation_id }"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "github_app_ids" {
  secret_id     = aws_secretsmanager_secret.github_app_ids.id
  secret_string = jsonencode({ app_id = "REPLACE_ME", installation_id = "REPLACE_ME" })
}

resource "aws_secretsmanager_secret" "atlassian_credentials" {
  name                    = "${local.name_prefix}/atlassian_credentials"
  description             = "Atlassian API credentials JSON"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "atlassian_credentials" {
  secret_id = aws_secretsmanager_secret.atlassian_credentials.id
  secret_string = jsonencode({
    jira_base_url       = "https://jira.example.com"
    confluence_base_url = "https://confluence.example.com"
    email               = "bot@example.com"
    api_token           = "REPLACE_ME"
    platform            = "datacenter"
  })
}

resource "aws_secretsmanager_secret" "chatbot_api_token" {
  count                   = var.chatbot_enabled ? 1 : 0
  name                    = "${local.name_prefix}/chatbot_api_token"
  description             = "Shared API token for chatbot endpoint authentication"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "chatbot_api_token" {
  count         = var.chatbot_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.chatbot_api_token[0].id
  secret_string = var.chatbot_api_token
}

resource "aws_secretsmanager_secret" "teams_adapter_token" {
  count                   = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  name                    = "${local.name_prefix}/teams_adapter_token"
  description             = "Microsoft Teams adapter auth token"
  kms_key_id              = aws_kms_key.app.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "teams_adapter_token" {
  count         = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.teams_adapter_token[0].id
  secret_string = var.teams_adapter_token
}

resource "aws_sqs_queue" "pr_review_dlq" {
  name              = "${local.name_prefix}-pr-review-dlq"
  kms_master_key_id = aws_kms_key.app.arn
}

resource "aws_sqs_queue" "pr_review_queue" {
  name                       = "${local.name_prefix}-pr-review"
  visibility_timeout_seconds = 1080
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.app.arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.pr_review_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.name_prefix}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"

  attribute {
    name = "idempotency_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app.arn
  }
}

resource "aws_dynamodb_table" "chatbot_memory" {
  count        = local.chatbot_memory_enabled ? 1 : 0
  name         = "${local.name_prefix}-chatbot-memory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "conversation_id"
  range_key    = "timestamp_ms"

  attribute {
    name = "conversation_id"
    type = "S"
  }

  attribute {
    name = "timestamp_ms"
    type = "N"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app.arn
  }
}

resource "aws_s3_bucket" "kb_sync_documents" {
  count  = local.kb_sync_any_enabled ? 1 : 0
  bucket = "${local.name_prefix}-kb-sync-docs"
}

resource "aws_s3_bucket" "webapp" {
  count         = local.webapp_s3_enabled ? 1 : 0
  bucket        = local.webapp_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "webapp" {
  count  = local.webapp_s3_enabled ? 1 : 0
  bucket = aws_s3_bucket.webapp[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "webapp" {
  count                   = local.webapp_s3_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.webapp[0].id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "webapp" {
  count  = local.webapp_s3_enabled ? 1 : 0
  bucket = aws_s3_bucket.webapp[0].id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_policy" "webapp_public_read" {
  count  = local.webapp_s3_enabled ? 1 : 0
  bucket = aws_s3_bucket.webapp[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject"]
        Resource  = ["${aws_s3_bucket.webapp[0].arn}/*"]
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.webapp]
}

resource "aws_s3_object" "webapp_files" {
  for_each = local.webapp_s3_enabled ? local.webapp_files : {}

  bucket       = aws_s3_bucket.webapp[0].id
  key          = each.key
  source       = each.value.source
  etag         = filemd5(each.value.source)
  content_type = each.value.content_type
}

resource "aws_security_group" "webapp_ec2" {
  count       = local.webapp_ec2_enabled ? 1 : 0
  name        = "${local.name_prefix}-webapp-ec2-sg"
  description = "Allow HTTP access to EC2-hosted static chatbot webapp"
  vpc_id      = data.aws_subnet.webapp[0].vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.webapp_ec2_allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "webapp" {
  count                       = local.webapp_ec2_enabled ? 1 : 0
  ami                         = trimspace(var.webapp_ec2_ami_id) != "" ? trimspace(var.webapp_ec2_ami_id) : data.aws_ssm_parameter.webapp_ami[0].value
  instance_type               = var.webapp_ec2_instance_type
  subnet_id                   = var.webapp_ec2_subnet_id
  key_name                    = trimspace(var.webapp_ec2_key_name) != "" ? trimspace(var.webapp_ec2_key_name) : null
  vpc_security_group_ids      = [aws_security_group.webapp_ec2[0].id]
  associate_public_ip_address = !local.webapp_private_only

  user_data = <<-EOT
    #!/bin/bash
    set -euxo pipefail
    yum update -y
    amazon-linux-extras install nginx1 -y || yum install -y nginx
    mkdir -p /usr/share/nginx/html
    echo '${base64encode(file("${path.module}/../../webapp/index.html"))}' | base64 -d > /usr/share/nginx/html/index.html
    echo '${base64encode(format("window.WEBAPP_DEFAULTS = %s;\n", jsonencode(local.webapp_default_config)))}' | base64 -d > /usr/share/nginx/html/config.js
    echo '${base64encode(file("${path.module}/../../webapp/app.js"))}' | base64 -d > /usr/share/nginx/html/app.js
    echo '${base64encode(file("${path.module}/../../webapp/styles.css"))}' | base64 -d > /usr/share/nginx/html/styles.css
    chown -R nginx:nginx /usr/share/nginx/html
    chmod 0644 /usr/share/nginx/html/index.html /usr/share/nginx/html/config.js /usr/share/nginx/html/app.js /usr/share/nginx/html/styles.css
    systemctl enable nginx
    systemctl restart nginx
  EOT

  user_data_replace_on_change = true

  tags = {
    Name = "${local.name_prefix}-chatbot-webapp"
  }
}

resource "aws_eip" "webapp" {
  count    = local.webapp_ec2_enabled && !local.webapp_private_only ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.webapp[0].id

  depends_on = [aws_instance.webapp]
}

resource "aws_eip" "webapp_tls" {
  for_each = local.webapp_tls_enabled && !local.webapp_private_only ? local.webapp_tls_subnet_map : {}
  domain   = "vpc"
}

resource "aws_lb" "webapp" {
  count              = local.webapp_tls_enabled ? 1 : 0
  name               = "${local.name_prefix}-webapp-nlb"
  load_balancer_type = "network"
  internal           = local.webapp_private_only
  subnets            = local.webapp_private_only ? var.webapp_tls_subnet_ids : null

  dynamic "subnet_mapping" {
    for_each = local.webapp_private_only ? {} : local.webapp_tls_subnet_map
    content {
      subnet_id     = subnet_mapping.value
      allocation_id = aws_eip.webapp_tls[subnet_mapping.key].id
    }
  }
}

resource "aws_lb_target_group" "webapp" {
  count       = local.webapp_tls_enabled ? 1 : 0
  name        = "${local.name_prefix}-webapp-tg"
  port        = 80
  protocol    = "TCP"
  target_type = "instance"
  vpc_id      = data.aws_subnet.webapp[0].vpc_id

  health_check {
    protocol = "HTTP"
    path     = "/"
    matcher  = "200-399"
  }
}

resource "aws_lb_target_group_attachment" "webapp" {
  count            = local.webapp_tls_enabled ? 1 : 0
  target_group_arn = aws_lb_target_group.webapp[0].arn
  target_id        = aws_instance.webapp[0].id
  port             = 80
}

resource "aws_lb_listener" "webapp_https" {
  count             = local.webapp_tls_enabled ? 1 : 0
  load_balancer_arn = aws_lb.webapp[0].arn
  port              = 443
  protocol          = "TLS"
  certificate_arn   = var.webapp_tls_acm_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.webapp[0].arn
  }
}

resource "aws_dynamodb_table" "kb_sync_state" {
  count        = local.kb_sync_any_enabled ? 1 : 0
  name         = "${local.name_prefix}-kb-sync-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sync_key"

  attribute {
    name = "sync_key"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app.arn
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "kb_sync_documents" {
  count  = local.kb_sync_any_enabled ? 1 : 0
  bucket = aws_s3_bucket.kb_sync_documents[0].id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.app.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "kb_sync_documents" {
  count                   = local.kb_sync_any_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.kb_sync_documents[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "kb_sync_documents" {
  count  = local.kb_sync_any_enabled ? 1 : 0
  bucket = aws_s3_bucket.kb_sync_documents[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "kb_sync_documents" {
  count  = local.kb_sync_any_enabled ? 1 : 0
  bucket = aws_s3_bucket.kb_sync_documents[0].id

  rule {
    id     = "noncurrent-expiry"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "intelligent-tiering"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}

data "archive_file" "lambda_bundle" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/lambda_bundle.zip"
}

resource "aws_iam_role" "webhook_lambda" {
  name = "${local.name_prefix}-webhook-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "worker_lambda" {
  name = "${local.name_prefix}-worker-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "chatbot_lambda" {
  count = var.chatbot_enabled ? 1 : 0
  name  = "${local.name_prefix}-chatbot-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "chatbot_github_oauth_authorizer_lambda" {
  count = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  name  = "${local.name_prefix}-chatbot-github-oauth-authorizer-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "kb_sync_lambda" {
  count = local.kb_sync_any_enabled ? 1 : 0
  name  = "${local.name_prefix}-kb-sync-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "webhook_policy" {
  name = "${local.name_prefix}-webhook-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["sqs:SendMessage"]
        Resource = compact([
          aws_sqs_queue.pr_review_queue.arn,
          var.pr_description_enabled ? aws_sqs_queue.pr_description_queue[0].arn : "",
        ])
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.github_webhook_secret.arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_policy" "worker_policy" {
  name = "${local.name_prefix}-worker-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.pr_review_queue.arn
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = try(aws_sqs_queue.test_gen_queue[0].arn, aws_sqs_queue.pr_review_queue.arn)
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.idempotency.arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app_private_key_pem.arn,
          aws_secretsmanager_secret.github_app_ids.arn,
          aws_secretsmanager_secret.atlassian_credentials.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeAgent"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_policy" "chatbot_policy" {
  count = var.chatbot_enabled ? 1 : 0
  name  = "${local.name_prefix}-chatbot-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = compact([
          aws_secretsmanager_secret.atlassian_credentials.arn,
          var.chatbot_enabled ? aws_secretsmanager_secret.chatbot_api_token[0].arn : "",
          var.chatbot_enabled && var.teams_adapter_enabled ? aws_secretsmanager_secret.teams_adapter_token[0].arn : "",
          var.chatbot_enabled && var.chatbot_github_live_enabled ? aws_secretsmanager_secret.github_app_private_key_pem.arn : "",
          var.chatbot_enabled && var.chatbot_github_live_enabled ? aws_secretsmanager_secret.github_app_ids.arn : "",
          var.chatbot_enabled && var.chatbot_enable_anthropic_direct && length(trimspace(var.chatbot_anthropic_api_key_secret_arn)) > 0 ? var.chatbot_anthropic_api_key_secret_arn : "",
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "bedrock:InvokeModel",
          "bedrock:ListFoundationModels",
          "bedrock:Retrieve",
          "bedrock:RetrieveAndGenerate"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
      ], local.chatbot_websocket_enabled ? [
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:execute-api:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:${aws_apigatewayv2_api.chatbot_ws[0].id}/${var.chatbot_websocket_stage}/POST/@connections/*"
      }
      ] : [], local.chatbot_memory_enabled ? [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = aws_dynamodb_table.chatbot_memory[0].arn
      }
    ] : [])
  })
}

resource "aws_iam_policy" "chatbot_github_oauth_authorizer_policy" {
  count = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  name  = "${local.name_prefix}-chatbot-github-oauth-authorizer-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}

resource "aws_iam_policy" "kb_sync_policy" {
  count = local.kb_sync_any_enabled ? 1 : 0
  name  = "${local.name_prefix}-kb-sync-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = compact([
          var.kb_sync_enabled ? aws_secretsmanager_secret.atlassian_credentials.arn : "",
          var.github_kb_sync_enabled ? aws_secretsmanager_secret.github_app_private_key_pem.arn : "",
          var.github_kb_sync_enabled ? aws_secretsmanager_secret.github_app_ids.arn : "",
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.kb_sync_documents[0].arn,
          "${aws_s3_bucket.kb_sync_documents[0].arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:StartIngestionJob",
          "bedrock:GetIngestionJob"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.app.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.kb_sync_state[0].arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "webhook_policy" {
  role       = aws_iam_role.webhook_lambda.name
  policy_arn = aws_iam_policy.webhook_policy.arn
}

resource "aws_iam_role_policy_attachment" "worker_policy" {
  role       = aws_iam_role.worker_lambda.name
  policy_arn = aws_iam_policy.worker_policy.arn
}

resource "aws_iam_role_policy_attachment" "chatbot_policy" {
  count      = var.chatbot_enabled ? 1 : 0
  role       = aws_iam_role.chatbot_lambda[0].name
  policy_arn = aws_iam_policy.chatbot_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "chatbot_github_oauth_authorizer_policy" {
  count      = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  role       = aws_iam_role.chatbot_github_oauth_authorizer_lambda[0].name
  policy_arn = aws_iam_policy.chatbot_github_oauth_authorizer_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "kb_sync_policy" {
  count      = local.kb_sync_any_enabled ? 1 : 0
  role       = aws_iam_role.kb_sync_lambda[0].name
  policy_arn = aws_iam_policy.kb_sync_policy[0].arn
}

# ---------------------------------------------------------------------------
# X-Ray tracing IAM — attach managed policy to all Lambda roles
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy_attachment" "xray_webhook" {
  count      = var.lambda_tracing_enabled ? 1 : 0
  role       = aws_iam_role.webhook_lambda.name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_worker" {
  count      = var.lambda_tracing_enabled ? 1 : 0
  role       = aws_iam_role.worker_lambda.name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_chatbot" {
  count      = var.lambda_tracing_enabled && var.chatbot_enabled ? 1 : 0
  role       = aws_iam_role.chatbot_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_chatbot_authorizer" {
  count      = var.lambda_tracing_enabled && local.chatbot_auth_github_oauth_enabled ? 1 : 0
  role       = aws_iam_role.chatbot_github_oauth_authorizer_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_kb_sync" {
  count      = var.lambda_tracing_enabled && local.kb_sync_any_enabled ? 1 : 0
  role       = aws_iam_role.kb_sync_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_lambda_function" "webhook_receiver" {
  function_name    = "${local.name_prefix}-webhook-receiver"
  role             = aws_iam_role.webhook_lambda.arn
  runtime          = "python3.12"
  handler          = "webhook_receiver.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      QUEUE_URL                = aws_sqs_queue.pr_review_queue.id
      WEBHOOK_SECRET_ARN       = aws_secretsmanager_secret.github_webhook_secret.arn
      GITHUB_ALLOWED_REPOS     = join(",", var.github_allowed_repos)
      PR_DESCRIPTION_QUEUE_URL = var.pr_description_enabled ? aws_sqs_queue.pr_description_queue[0].id : ""
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_lambda_function" "pr_review_worker" {
  function_name    = "${local.name_prefix}-pr-review-worker"
  role             = aws_iam_role.worker_lambda.arn
  runtime          = "python3.12"
  handler          = "worker.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 180
  memory_size      = 1024

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      BEDROCK_AGENT_ID                  = var.bedrock_agent_id
      BEDROCK_AGENT_ALIAS_ID            = var.bedrock_agent_alias_id
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      GITHUB_API_BASE                   = var.github_api_base
      DRY_RUN                           = tostring(var.dry_run)
      IDEMPOTENCY_TABLE                 = aws_dynamodb_table.idempotency.name
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      METRICS_NAMESPACE                 = "${var.project_name}/${var.environment}"
      AUTO_PR_ENABLED                   = tostring(var.auto_pr_enabled)
      AUTO_PR_MAX_FILES                 = tostring(var.auto_pr_max_files)
      AUTO_PR_BRANCH_PREFIX             = var.auto_pr_branch_prefix
      REVIEW_COMMENT_MODE               = var.review_comment_mode
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      TEST_GEN_QUEUE_URL                = var.test_gen_enabled ? aws_sqs_queue.test_gen_queue[0].id : ""
    }
  }

  reserved_concurrent_executions = local.worker_concurrency

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "webhook" {
  name              = "/aws/lambda/${aws_lambda_function.webhook_receiver.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${aws_lambda_function.pr_review_worker.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "jira_confluence_chatbot" {
  count            = var.chatbot_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-jira-confluence-chatbot"
  role             = aws_iam_role.chatbot_lambda[0].arn
  runtime          = "python3.12"
  handler          = "chatbot.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                                     = data.aws_region.current.name
      CHATBOT_MODEL_ID                               = var.chatbot_model_id
      BEDROCK_MODEL_ID                               = var.bedrock_model_id
      CHATBOT_RETRIEVAL_MODE                         = var.chatbot_retrieval_mode
      CHATBOT_DEFAULT_ASSISTANT_MODE                 = var.chatbot_default_assistant_mode
      CHATBOT_LLM_PROVIDER                           = var.chatbot_llm_provider
      CHATBOT_ALLOWED_MODEL_IDS                      = join(",", var.chatbot_allowed_model_ids)
      CHATBOT_ENABLE_ANTHROPIC_DIRECT                = tostring(var.chatbot_enable_anthropic_direct)
      CHATBOT_ANTHROPIC_API_KEY_SECRET_ARN           = var.chatbot_anthropic_api_key_secret_arn
      CHATBOT_ANTHROPIC_API_BASE                     = var.chatbot_anthropic_api_base
      CHATBOT_ANTHROPIC_MODEL_ID                     = var.chatbot_anthropic_model_id
      CHATBOT_IMAGE_MODEL_ID                         = var.chatbot_image_model_id
      CHATBOT_IMAGE_SIZE                             = var.chatbot_image_default_size
      CHATBOT_IMAGE_SAFETY_ENABLED                   = tostring(var.chatbot_image_safety_enabled)
      CHATBOT_IMAGE_BANNED_TERMS                     = join(",", var.chatbot_image_banned_terms)
      CHATBOT_IMAGE_USER_REQUESTS_PER_MINUTE         = tostring(var.chatbot_image_user_requests_per_minute)
      CHATBOT_IMAGE_CONVERSATION_REQUESTS_PER_MINUTE = tostring(var.chatbot_image_conversation_requests_per_minute)
      CHATBOT_MEMORY_ENABLED                         = tostring(var.chatbot_memory_enabled)
      CHATBOT_MEMORY_TABLE                           = local.chatbot_memory_enabled ? aws_dynamodb_table.chatbot_memory[0].name : ""
      CHATBOT_MEMORY_MAX_TURNS                       = tostring(var.chatbot_memory_max_turns)
      CHATBOT_MEMORY_TTL_DAYS                        = tostring(var.chatbot_memory_ttl_days)
      CHATBOT_MEMORY_COMPACTION_CHARS                = tostring(var.chatbot_memory_compaction_chars)
      CHATBOT_USER_REQUESTS_PER_MINUTE               = tostring(var.chatbot_user_requests_per_minute)
      CHATBOT_CONVERSATION_REQUESTS_PER_MINUTE       = tostring(var.chatbot_conversation_requests_per_minute)
      CHATBOT_WEBSOCKET_DEFAULT_CHUNK_CHARS          = tostring(var.chatbot_websocket_default_chunk_chars)
      CHATBOT_METRICS_ENABLED                        = tostring(var.chatbot_observability_enabled)
      METRICS_NAMESPACE                              = local.chatbot_metrics_namespace
      BEDROCK_KNOWLEDGE_BASE_ID                      = var.bedrock_knowledge_base_id
      BEDROCK_KB_TOP_K                               = tostring(var.bedrock_kb_top_k)
      ATLASSIAN_CREDENTIALS_SECRET_ARN               = aws_secretsmanager_secret.atlassian_credentials.arn
      CHATBOT_API_TOKEN_SECRET_ARN                   = var.chatbot_enabled ? aws_secretsmanager_secret.chatbot_api_token[0].arn : ""
      GITHUB_CHAT_LIVE_ENABLED                       = tostring(var.chatbot_github_live_enabled)
      GITHUB_CHAT_REPOS                              = join(",", var.chatbot_github_live_repos)
      GITHUB_CHAT_MAX_RESULTS                        = tostring(var.chatbot_github_live_max_results)
      GITHUB_API_BASE                                = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN              = var.chatbot_github_live_enabled ? aws_secretsmanager_secret.github_app_private_key_pem.arn : ""
      GITHUB_APP_IDS_SECRET_ARN                      = var.chatbot_github_live_enabled ? aws_secretsmanager_secret.github_app_ids.arn : ""
    }
  }

  reserved_concurrent_executions = local.chatbot_concurrency

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_lambda_function" "chatbot_github_oauth_authorizer" {
  count            = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-chatbot-github-oauth-authorizer"
  role             = aws_iam_role.chatbot_github_oauth_authorizer_lambda[0].arn
  runtime          = "python3.12"
  handler          = "chatbot.github_oauth_authorizer.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      AWS_REGION                = data.aws_region.current.name
      GITHUB_API_BASE           = var.github_api_base
      GITHUB_OAUTH_ALLOWED_ORGS = join(",", var.github_oauth_allowed_orgs)
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_lambda_function" "teams_chatbot_adapter" {
  count            = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-teams-chatbot-adapter"
  role             = aws_iam_role.chatbot_lambda[0].arn
  runtime          = "python3.12"
  handler          = "chatbot.teams_adapter.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                       = data.aws_region.current.name
      CHATBOT_MODEL_ID                 = var.chatbot_model_id
      BEDROCK_MODEL_ID                 = var.bedrock_model_id
      CHATBOT_RETRIEVAL_MODE           = var.chatbot_retrieval_mode
      BEDROCK_KNOWLEDGE_BASE_ID        = var.bedrock_knowledge_base_id
      BEDROCK_KB_TOP_K                 = tostring(var.bedrock_kb_top_k)
      ATLASSIAN_CREDENTIALS_SECRET_ARN = aws_secretsmanager_secret.atlassian_credentials.arn
      TEAMS_ADAPTER_TOKEN_SECRET_ARN   = var.chatbot_enabled && var.teams_adapter_enabled ? aws_secretsmanager_secret.teams_adapter_token[0].arn : ""
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_lambda_function" "confluence_kb_sync" {
  count            = var.kb_sync_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-confluence-kb-sync"
  role             = aws_iam_role.kb_sync_lambda[0].arn
  runtime          = "python3.12"
  handler          = "kb_sync.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                       = data.aws_region.current.name
      ATLASSIAN_CREDENTIALS_SECRET_ARN = aws_secretsmanager_secret.atlassian_credentials.arn
      BEDROCK_KNOWLEDGE_BASE_ID        = var.bedrock_knowledge_base_id
      BEDROCK_KB_DATA_SOURCE_ID        = var.bedrock_kb_data_source_id
      KB_SYNC_BUCKET                   = aws_s3_bucket.kb_sync_documents[0].bucket
      KB_SYNC_PREFIX                   = var.kb_sync_s3_prefix
      CONFLUENCE_SYNC_CQL              = var.confluence_sync_cql
      CONFLUENCE_SYNC_LIMIT            = tostring(var.confluence_sync_limit)
      KB_SYNC_STATE_TABLE              = aws_dynamodb_table.kb_sync_state[0].name
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_lambda_function" "github_kb_sync" {
  count            = var.github_kb_sync_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-github-kb-sync"
  role             = aws_iam_role.kb_sync_lambda[0].arn
  runtime          = "python3.12"
  handler          = "github_kb_sync.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 180
  memory_size      = 1024

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      BEDROCK_KNOWLEDGE_BASE_ID         = var.bedrock_knowledge_base_id
      BEDROCK_KB_DATA_SOURCE_ID         = var.bedrock_kb_data_source_id
      GITHUB_KB_DATA_SOURCE_ID          = var.github_kb_data_source_id
      KB_SYNC_BUCKET                    = aws_s3_bucket.kb_sync_documents[0].bucket
      GITHUB_KB_SYNC_PREFIX             = var.github_kb_sync_s3_prefix
      GITHUB_KB_REPOS                   = join(",", var.github_kb_repos)
      GITHUB_KB_INCLUDE_PATTERNS        = join(",", var.github_kb_include_patterns)
      GITHUB_KB_MAX_FILES_PER_REPO      = tostring(var.github_kb_max_files_per_repo)
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "chatbot" {
  count             = var.chatbot_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.jira_confluence_chatbot[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "teams_chatbot" {
  count             = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.teams_chatbot_adapter[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "kb_sync" {
  count             = var.kb_sync_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.confluence_kb_sync[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "github_kb_sync" {
  count             = var.github_kb_sync_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.github_kb_sync[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_event_rule" "kb_sync" {
  count               = var.kb_sync_enabled ? 1 : 0
  name                = "${local.name_prefix}-kb-sync"
  schedule_expression = var.kb_sync_schedule_expression
}

resource "aws_cloudwatch_event_target" "kb_sync" {
  count     = var.kb_sync_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.kb_sync[0].name
  target_id = "confluence-kb-sync-lambda"
  arn       = aws_lambda_function.confluence_kb_sync[0].arn
}

resource "aws_cloudwatch_event_rule" "github_kb_sync" {
  count               = var.github_kb_sync_enabled ? 1 : 0
  name                = "${local.name_prefix}-github-kb-sync"
  schedule_expression = var.github_kb_sync_schedule_expression
}

resource "aws_cloudwatch_event_target" "github_kb_sync" {
  count     = var.github_kb_sync_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.github_kb_sync[0].name
  target_id = "github-kb-sync-lambda"
  arn       = aws_lambda_function.github_kb_sync[0].arn
}

resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn                   = aws_sqs_queue.pr_review_queue.arn
  function_name                      = aws_lambda_function.pr_review_worker.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 1
  function_response_types            = ["ReportBatchItemFailures"]
}

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name_prefix}-webhook-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "webhook_lambda" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.webhook_receiver.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/github"
  target    = "integrations/${aws_apigatewayv2_integration.webhook_lambda.id}"
}

resource "aws_apigatewayv2_authorizer" "chatbot_jwt" {
  count            = local.chatbot_auth_jwt_enabled ? 1 : 0
  api_id           = aws_apigatewayv2_api.webhook.id
  name             = "${local.name_prefix}-chatbot-jwt"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = var.chatbot_jwt_issuer
    audience = var.chatbot_jwt_audience
  }
}

resource "aws_apigatewayv2_authorizer" "chatbot_github_oauth" {
  count                             = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  api_id                            = aws_apigatewayv2_api.webhook.id
  name                              = "${local.name_prefix}-chatbot-github-oauth"
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = "arn:${data.aws_partition.current.partition}:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.chatbot_github_oauth_authorizer[0].arn}/invocations"
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Authorization"]
}

resource "aws_apigatewayv2_integration" "chatbot_lambda" {
  count                  = var.chatbot_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.jira_confluence_chatbot[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "chatbot" {
  count              = var.chatbot_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /chatbot/query"
  target             = "integrations/${aws_apigatewayv2_integration.chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_route" "chatbot_models" {
  count              = var.chatbot_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "GET /chatbot/models"
  target             = "integrations/${aws_apigatewayv2_integration.chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_route" "chatbot_image" {
  count              = var.chatbot_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /chatbot/image"
  target             = "integrations/${aws_apigatewayv2_integration.chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_route" "chatbot_memory_clear" {
  count              = var.chatbot_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /chatbot/memory/clear"
  target             = "integrations/${aws_apigatewayv2_integration.chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_route" "chatbot_memory_clear_all" {
  count              = var.chatbot_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /chatbot/memory/clear-all"
  target             = "integrations/${aws_apigatewayv2_integration.chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_integration" "teams_chatbot_lambda" {
  count                  = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.teams_chatbot_adapter[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "teams_chatbot" {
  count              = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /chatbot/teams"
  target             = "integrations/${aws_apigatewayv2_integration.teams_chatbot_lambda[0].id}"
  authorization_type = local.chatbot_route_auth_type
  authorizer_id = local.chatbot_auth_jwt_enabled ? aws_apigatewayv2_authorizer.chatbot_jwt[0].id : (
    local.chatbot_auth_github_oauth_enabled ? aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id : null
  )
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 200
    throttling_rate_limit  = 100
  }
}

resource "aws_apigatewayv2_api" "chatbot_ws" {
  count                      = local.chatbot_websocket_enabled ? 1 : 0
  name                       = "${local.name_prefix}-chatbot-ws-api"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_integration" "chatbot_ws_lambda" {
  count            = local.chatbot_websocket_enabled ? 1 : 0
  api_id           = aws_apigatewayv2_api.chatbot_ws[0].id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.jira_confluence_chatbot[0].invoke_arn
}

resource "aws_apigatewayv2_route" "chatbot_ws_connect" {
  count     = local.chatbot_websocket_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.chatbot_ws[0].id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.chatbot_ws_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "chatbot_ws_disconnect" {
  count     = local.chatbot_websocket_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.chatbot_ws[0].id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.chatbot_ws_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "chatbot_ws_query" {
  count     = local.chatbot_websocket_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.chatbot_ws[0].id
  route_key = "query"
  target    = "integrations/${aws_apigatewayv2_integration.chatbot_ws_lambda[0].id}"
}

resource "aws_apigatewayv2_stage" "chatbot_ws" {
  count       = local.chatbot_websocket_enabled ? 1 : 0
  api_id      = aws_apigatewayv2_api.chatbot_ws[0].id
  name        = var.chatbot_websocket_stage
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_receiver.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

resource "aws_lambda_permission" "allow_apigw_chatbot" {
  count         = var.chatbot_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayChatbot"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.jira_confluence_chatbot[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

resource "aws_lambda_permission" "allow_apigw_chatbot_ws" {
  count         = local.chatbot_websocket_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayChatbotWebsocket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.jira_confluence_chatbot[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.chatbot_ws[0].execution_arn}/*"
}

resource "aws_lambda_permission" "allow_apigw_teams_chatbot" {
  count         = var.chatbot_enabled && var.teams_adapter_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayTeamsChatbot"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.teams_chatbot_adapter[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

resource "aws_lambda_permission" "allow_apigw_chatbot_github_oauth_authorizer" {
  count         = local.chatbot_auth_github_oauth_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayChatbotGithubOAuthAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.chatbot_github_oauth_authorizer[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.chatbot_github_oauth[0].id}"
}

resource "aws_lambda_permission" "allow_eventbridge_kb_sync" {
  count         = var.kb_sync_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridgeKbSync"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.confluence_kb_sync[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.kb_sync[0].arn
}

resource "aws_lambda_permission" "allow_eventbridge_github_kb_sync" {
  count         = var.github_kb_sync_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridgeGithubKbSync"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.github_kb_sync[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.github_kb_sync[0].arn
}

# ---------------------------------------------------------------------------
# Release Notes Generator
# ---------------------------------------------------------------------------

resource "aws_iam_role" "release_notes_lambda" {
  count = var.release_notes_enabled ? 1 : 0
  name  = "${local.name_prefix}-release-notes-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "release_notes_policy" {
  count = var.release_notes_enabled ? 1 : 0
  name  = "${local.name_prefix}-release-notes-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app_private_key_pem.arn,
          aws_secretsmanager_secret.github_app_ids.arn,
          aws_secretsmanager_secret.atlassian_credentials.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "release_notes_policy" {
  count      = var.release_notes_enabled ? 1 : 0
  role       = aws_iam_role.release_notes_lambda[0].name
  policy_arn = aws_iam_policy.release_notes_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_release_notes" {
  count      = var.lambda_tracing_enabled && var.release_notes_enabled ? 1 : 0
  role       = aws_iam_role.release_notes_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_lambda_function" "release_notes" {
  count            = var.release_notes_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-release-notes"
  role             = aws_iam_role.release_notes_lambda[0].arn
  runtime          = "python3.12"
  handler          = "release_notes.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 60
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      RELEASE_NOTES_MODEL_ID            = var.release_notes_model_id
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      DRY_RUN                           = tostring(var.dry_run)
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "release_notes" {
  count             = var.release_notes_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.release_notes[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_integration" "release_notes_lambda" {
  count                  = var.release_notes_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.release_notes[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "release_notes" {
  count     = var.release_notes_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /release-notes/generate"
  target    = "integrations/${aws_apigatewayv2_integration.release_notes_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_release_notes" {
  count         = var.release_notes_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayReleaseNotes"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.release_notes[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Sprint Report Agent
# ---------------------------------------------------------------------------

resource "aws_iam_role" "sprint_report_lambda" {
  count = var.sprint_report_enabled ? 1 : 0
  name  = "${local.name_prefix}-sprint-report-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "sprint_report_policy" {
  count = var.sprint_report_enabled ? 1 : 0
  name  = "${local.name_prefix}-sprint-report-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app_private_key_pem.arn,
          aws_secretsmanager_secret.github_app_ids.arn,
          aws_secretsmanager_secret.atlassian_credentials.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sprint_report_policy" {
  count      = var.sprint_report_enabled ? 1 : 0
  role       = aws_iam_role.sprint_report_lambda[0].name
  policy_arn = aws_iam_policy.sprint_report_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_sprint_report" {
  count      = var.lambda_tracing_enabled && var.sprint_report_enabled ? 1 : 0
  role       = aws_iam_role.sprint_report_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_lambda_function" "sprint_report" {
  count            = var.sprint_report_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-sprint-report"
  role             = aws_iam_role.sprint_report_lambda[0].arn
  runtime          = "python3.12"
  handler          = "sprint_report.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 60
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      SPRINT_REPORT_MODEL_ID            = var.sprint_report_model_id
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      SPRINT_REPORT_REPO                = var.sprint_report_repo
      SPRINT_REPORT_JIRA_PROJECT        = var.sprint_report_jira_project
      SPRINT_REPORT_JQL                 = var.sprint_report_jql
      SPRINT_REPORT_TYPE                = var.sprint_report_type
      SPRINT_REPORT_DAYS_BACK           = tostring(var.sprint_report_days_back)
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "sprint_report" {
  count             = var.sprint_report_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.sprint_report[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_integration" "sprint_report_lambda" {
  count                  = var.sprint_report_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.sprint_report[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "sprint_report" {
  count     = var.sprint_report_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /reports/sprint"
  target    = "integrations/${aws_apigatewayv2_integration.sprint_report_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_sprint_report" {
  count         = var.sprint_report_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewaySprintReport"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sprint_report[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# EventBridge schedule for sprint report
resource "aws_cloudwatch_event_rule" "sprint_report" {
  count               = var.sprint_report_enabled && var.sprint_report_schedule_enabled ? 1 : 0
  name                = "${local.name_prefix}-sprint-report"
  schedule_expression = var.sprint_report_schedule_expression
}

resource "aws_cloudwatch_event_target" "sprint_report" {
  count     = var.sprint_report_enabled && var.sprint_report_schedule_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.sprint_report[0].name
  target_id = "sprint-report-lambda"
  arn       = aws_lambda_function.sprint_report[0].arn
}

resource "aws_lambda_permission" "allow_eventbridge_sprint_report" {
  count         = var.sprint_report_enabled && var.sprint_report_schedule_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromEventBridgeSprintReport"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sprint_report[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sprint_report[0].arn
}

# ---------------------------------------------------------------------------
# Test Generation Agent
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "test_gen_dlq" {
  count             = var.test_gen_enabled ? 1 : 0
  name              = "${local.name_prefix}-test-gen-dlq"
  kms_master_key_id = aws_kms_key.app.arn
}

resource "aws_sqs_queue" "test_gen_queue" {
  count                      = var.test_gen_enabled ? 1 : 0
  name                       = "${local.name_prefix}-test-gen"
  visibility_timeout_seconds = 1800
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.app.arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.test_gen_dlq[0].arn
    maxReceiveCount     = 3
  })
}

resource "aws_iam_role" "test_gen_lambda" {
  count = var.test_gen_enabled ? 1 : 0
  name  = "${local.name_prefix}-test-gen-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "test_gen_policy" {
  count = var.test_gen_enabled ? 1 : 0
  name  = "${local.name_prefix}-test-gen-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.test_gen_queue[0].arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app_private_key_pem.arn,
          aws_secretsmanager_secret.github_app_ids.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "test_gen_policy" {
  count      = var.test_gen_enabled ? 1 : 0
  role       = aws_iam_role.test_gen_lambda[0].name
  policy_arn = aws_iam_policy.test_gen_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_test_gen" {
  count      = var.lambda_tracing_enabled && var.test_gen_enabled ? 1 : 0
  role       = aws_iam_role.test_gen_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_lambda_function" "test_gen" {
  count            = var.test_gen_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-test-gen"
  role             = aws_iam_role.test_gen_lambda[0].arn
  runtime          = "python3.12"
  handler          = "test_gen.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 300
  memory_size      = 1024

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      TEST_GEN_MODEL_ID                 = var.test_gen_model_id
      TEST_GEN_DELIVERY_MODE            = var.test_gen_delivery_mode
      TEST_GEN_MAX_FILES                = tostring(var.test_gen_max_files)
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      DRY_RUN                           = tostring(var.dry_run)
    }
  }

  reserved_concurrent_executions = local.worker_concurrency

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "test_gen" {
  count             = var.test_gen_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.test_gen[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_event_source_mapping" "test_gen_sqs" {
  count                              = var.test_gen_enabled ? 1 : 0
  event_source_arn                   = aws_sqs_queue.test_gen_queue[0].arn
  function_name                      = aws_lambda_function.test_gen[0].arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}

resource "aws_apigatewayv2_integration" "test_gen_lambda" {
  count                  = var.test_gen_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.test_gen[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "test_gen" {
  count     = var.test_gen_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /test-gen/generate"
  target    = "integrations/${aws_apigatewayv2_integration.test_gen_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_test_gen" {
  count         = var.test_gen_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayTestGen"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.test_gen[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# PR Description Generator
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "pr_description_dlq" {
  count             = var.pr_description_enabled ? 1 : 0
  name              = "${local.name_prefix}-pr-description-dlq"
  kms_master_key_id = aws_kms_key.app.arn
}

resource "aws_sqs_queue" "pr_description_queue" {
  count                      = var.pr_description_enabled ? 1 : 0
  name                       = "${local.name_prefix}-pr-description"
  visibility_timeout_seconds = 720
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.app.arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.pr_description_dlq[0].arn
    maxReceiveCount     = 3
  })
}

resource "aws_iam_role" "pr_description_lambda" {
  count = var.pr_description_enabled ? 1 : 0
  name  = "${local.name_prefix}-pr-description-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "pr_description_policy" {
  count = var.pr_description_enabled ? 1 : 0
  name  = "${local.name_prefix}-pr-description-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.pr_description_queue[0].arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app_private_key_pem.arn,
          aws_secretsmanager_secret.github_app_ids.arn,
          aws_secretsmanager_secret.atlassian_credentials.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "pr_description_policy" {
  count      = var.pr_description_enabled ? 1 : 0
  role       = aws_iam_role.pr_description_lambda[0].name
  policy_arn = aws_iam_policy.pr_description_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_pr_description" {
  count      = var.lambda_tracing_enabled && var.pr_description_enabled ? 1 : 0
  role       = aws_iam_role.pr_description_lambda[0].name
  policy_arn = data.aws_iam_policy.xray_write[0].arn
}

resource "aws_lambda_function" "pr_description" {
  count            = var.pr_description_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-pr-description"
  role             = aws_iam_role.pr_description_lambda[0].arn
  runtime          = "python3.12"
  handler          = "pr_description.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      AWS_REGION                        = data.aws_region.current.name
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      PR_DESCRIPTION_MODEL_ID           = var.pr_description_model_id
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      DRY_RUN                           = tostring(var.dry_run)
    }
  }

  reserved_concurrent_executions = local.worker_concurrency

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "pr_description" {
  count             = var.pr_description_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.pr_description[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_event_source_mapping" "pr_description_sqs" {
  count                              = var.pr_description_enabled ? 1 : 0
  event_source_arn                   = aws_sqs_queue.pr_description_queue[0].arn
  function_name                      = aws_lambda_function.pr_description[0].arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}

resource "aws_apigatewayv2_integration" "pr_description_lambda" {
  count                  = var.pr_description_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.pr_description[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "pr_description" {
  count     = var.pr_description_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /pr-description/generate"
  target    = "integrations/${aws_apigatewayv2_integration.pr_description_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_pr_description" {
  count         = var.pr_description_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayPRDescription"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pr_description[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "kb_sync_errors" {
  count               = var.kb_sync_enabled && var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-kb-sync-errors"
  alarm_description   = "KB sync Lambda errors detected"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.confluence_kb_sync[0].function_name
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "github_kb_sync_errors" {
  count               = var.github_kb_sync_enabled && var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-github-kb-sync-errors"
  alarm_description   = "GitHub KB sync Lambda errors detected"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.github_kb_sync[0].function_name
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  count               = var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-dlq-messages"
  alarm_description   = "Dead letter queue has visible messages"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.pr_review_dlq.name
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "chatbot_duration" {
  count               = var.chatbot_enabled && var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-chatbot-high-duration"
  alarm_description   = "Chatbot Lambda duration approaching timeout"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 25000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.jira_confluence_chatbot[0].function_name
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "chatbot_query_server_errors" {
  count               = var.chatbot_enabled && var.chatbot_observability_enabled && var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-chatbot-query-server-errors"
  alarm_description   = "Chatbot query endpoint has server errors"
  namespace           = local.chatbot_metrics_namespace
  metric_name         = "ChatbotServerErrorCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Route  = "query"
    Method = "POST"
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "chatbot_image_server_errors" {
  count               = var.chatbot_enabled && var.chatbot_observability_enabled && var.alarm_sns_topic_arn != "" ? 1 : 0
  alarm_name          = "${local.name_prefix}-chatbot-image-server-errors"
  alarm_description   = "Chatbot image endpoint has server errors"
  namespace           = local.chatbot_metrics_namespace
  metric_name         = "ChatbotServerErrorCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Route  = "image"
    Method = "POST"
  }

  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_dashboard" "chatbot_observability" {
  count          = var.chatbot_enabled && var.chatbot_observability_enabled ? 1 : 0
  dashboard_name = "${local.name_prefix}-chatbot-observability"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Chatbot Lambda Duration/Errors"
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.jira_confluence_chatbot[0].function_name, { stat = "p95", label = "Duration p95" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.jira_confluence_chatbot[0].function_name, { stat = "Sum", label = "Lambda Errors" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Chatbot Request Count by Route"
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          metrics = [
            [local.chatbot_metrics_namespace, "ChatbotRequestCount", "Route", "query", "Method", "POST", { stat = "Sum", label = "Query Requests" }],
            [local.chatbot_metrics_namespace, "ChatbotRequestCount", "Route", "image", "Method", "POST", { stat = "Sum", label = "Image Requests" }],
            [local.chatbot_metrics_namespace, "ChatbotRequestCount", "Route", "models", "Method", "GET", { stat = "Sum", label = "Model List Requests" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Chatbot Latency (ms)"
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          metrics = [
            [local.chatbot_metrics_namespace, "ChatbotLatencyMs", "Route", "query", "Method", "POST", { stat = "p95", label = "Query p95" }],
            [local.chatbot_metrics_namespace, "ChatbotLatencyMs", "Route", "image", "Method", "POST", { stat = "p95", label = "Image p95" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Chatbot Server Error Counts"
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          metrics = [
            [local.chatbot_metrics_namespace, "ChatbotServerErrorCount", "Route", "query", "Method", "POST", { stat = "Sum", label = "Query 5xx" }],
            [local.chatbot_metrics_namespace, "ChatbotServerErrorCount", "Route", "image", "Method", "POST", { stat = "Sum", label = "Image 5xx" }],
            [local.chatbot_metrics_namespace, "ChatbotErrorCount", "Route", "query", "Method", "POST", { stat = "Sum", label = "Query 4xx/5xx" }],
            [local.chatbot_metrics_namespace, "ChatbotErrorCount", "Route", "image", "Method", "POST", { stat = "Sum", label = "Image 4xx/5xx" }],
          ]
        }
      }
    ]
  })
}
