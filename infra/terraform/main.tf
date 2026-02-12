locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

data "aws_caller_identity" "current" {}

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
        Resource = "arn:aws-us-gov:logs:us-gov-west-1:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.pr_review_queue.arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.github_webhook_secret.arn
      },
      {
        Effect = "Allow"
        Action = ["kms:Decrypt"]
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
        Resource = "arn:aws-us-gov:logs:us-gov-west-1:${data.aws_caller_identity.current.account_id}:*"
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
          aws_secretsmanager_secret.github_app_ids.arn
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
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricData"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
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
      QUEUE_URL            = aws_sqs_queue.pr_review_queue.id
      WEBHOOK_SECRET_ARN   = aws_secretsmanager_secret.github_webhook_secret.arn
      GITHUB_ALLOWED_REPOS = join(",", var.github_allowed_repos)
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
      AWS_REGION                         = "us-gov-west-1"
      BEDROCK_AGENT_ID                  = var.bedrock_agent_id
      BEDROCK_AGENT_ALIAS_ID            = var.bedrock_agent_alias_id
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      GITHUB_API_BASE                   = "https://api.github.com"
      DRY_RUN                           = tostring(var.dry_run)
      IDEMPOTENCY_TABLE                 = aws_dynamodb_table.idempotency.name
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = aws_secretsmanager_secret.github_app_private_key_pem.arn
      GITHUB_APP_IDS_SECRET_ARN         = aws_secretsmanager_secret.github_app_ids.arn
      METRICS_NAMESPACE                 = "${var.project_name}/${var.environment}"
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

resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn        = aws_sqs_queue.pr_review_queue.arn
  function_name           = aws_lambda_function.pr_review_worker.arn
  batch_size              = 5
  maximum_batching_window_in_seconds = 1
  function_response_types = ["ReportBatchItemFailures"]
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
