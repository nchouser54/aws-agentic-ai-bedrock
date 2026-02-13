locals {
  name_prefix                       = "${var.project_name}-${var.environment}"
  chatbot_auth_jwt_enabled          = var.chatbot_enabled && var.chatbot_auth_mode == "jwt"
  chatbot_auth_github_oauth_enabled = var.chatbot_enabled && var.chatbot_auth_mode == "github_oauth"
  chatbot_route_auth_type           = local.chatbot_auth_jwt_enabled ? "JWT" : local.chatbot_auth_github_oauth_enabled ? "CUSTOM" : "NONE"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

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
  visibility_timeout_seconds = 180
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

resource "aws_s3_bucket" "kb_sync_documents" {
  count  = var.kb_sync_enabled ? 1 : 0
  bucket = "${local.name_prefix}-kb-sync-docs"
}

resource "aws_dynamodb_table" "kb_sync_state" {
  count        = var.kb_sync_enabled ? 1 : 0
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
  count  = var.kb_sync_enabled ? 1 : 0
  bucket = aws_s3_bucket.kb_sync_documents[0].id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.app.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "kb_sync_documents" {
  count                   = var.kb_sync_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.kb_sync_documents[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "kb_sync_documents" {
  count  = var.kb_sync_enabled ? 1 : 0
  bucket = aws_s3_bucket.kb_sync_documents[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "kb_sync_documents" {
  count  = var.kb_sync_enabled ? 1 : 0
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
  count = var.kb_sync_enabled ? 1 : 0
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
          aws_secretsmanager_secret.atlassian_credentials.arn,
          var.chatbot_enabled ? aws_secretsmanager_secret.chatbot_api_token[0].arn : "",
          var.chatbot_enabled && var.teams_adapter_enabled ? aws_secretsmanager_secret.teams_adapter_token[0].arn : "",
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
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
    ]
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
  count = var.kb_sync_enabled ? 1 : 0
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
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.atlassian_credentials.arn
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
  count      = var.kb_sync_enabled ? 1 : 0
  role       = aws_iam_role.kb_sync_lambda[0].name
  policy_arn = aws_iam_policy.kb_sync_policy[0].arn
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
      AWS_REGION                        = "us-gov-west-1"
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
      AWS_REGION                       = "us-gov-west-1"
      CHATBOT_MODEL_ID                 = var.chatbot_model_id
      BEDROCK_MODEL_ID                 = var.bedrock_model_id
      CHATBOT_RETRIEVAL_MODE           = var.chatbot_retrieval_mode
      BEDROCK_KNOWLEDGE_BASE_ID        = var.bedrock_knowledge_base_id
      BEDROCK_KB_TOP_K                 = tostring(var.bedrock_kb_top_k)
      ATLASSIAN_CREDENTIALS_SECRET_ARN = aws_secretsmanager_secret.atlassian_credentials.arn
      CHATBOT_API_TOKEN_SECRET_ARN     = var.chatbot_enabled ? aws_secretsmanager_secret.chatbot_api_token[0].arn : ""
    }
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
      AWS_REGION                = "us-gov-west-1"
      GITHUB_API_BASE           = var.github_api_base
      GITHUB_OAUTH_ALLOWED_ORGS = join(",", var.github_oauth_allowed_orgs)
    }
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
      AWS_REGION                       = "us-gov-west-1"
      CHATBOT_MODEL_ID                 = var.chatbot_model_id
      BEDROCK_MODEL_ID                 = var.bedrock_model_id
      CHATBOT_RETRIEVAL_MODE           = var.chatbot_retrieval_mode
      BEDROCK_KNOWLEDGE_BASE_ID        = var.bedrock_knowledge_base_id
      BEDROCK_KB_TOP_K                 = tostring(var.bedrock_kb_top_k)
      ATLASSIAN_CREDENTIALS_SECRET_ARN = aws_secretsmanager_secret.atlassian_credentials.arn
      TEAMS_ADAPTER_TOKEN_SECRET_ARN   = var.chatbot_enabled && var.teams_adapter_enabled ? aws_secretsmanager_secret.teams_adapter_token[0].arn : ""
    }
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
      AWS_REGION                       = "us-gov-west-1"
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
      AWS_REGION                        = "us-gov-west-1"
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      RELEASE_NOTES_MODEL_ID            = var.release_notes_model_id
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      DRY_RUN                           = tostring(var.dry_run)
    }
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
      AWS_REGION                        = "us-gov-west-1"
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
  visibility_timeout_seconds = 300
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
      AWS_REGION                        = "us-gov-west-1"
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
  visibility_timeout_seconds = 180
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
      AWS_REGION                        = "us-gov-west-1"
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      PR_DESCRIPTION_MODEL_ID           = var.pr_description_model_id
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      ATLASSIAN_CREDENTIALS_SECRET_ARN  = aws_secretsmanager_secret.atlassian_credentials.arn
      DRY_RUN                           = tostring(var.dry_run)
    }
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
