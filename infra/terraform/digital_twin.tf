# ---------------------------------------------------------------------------
# Digital Twin — Phase 2, 3, 4 resources
#
# Phase 3: POST /test-gen/file  (re-uses existing test_gen Lambda)
# Phase 2: Coverage ingestion Lambda  (POST /coverage/ingest)
# Phase 4: Impact analysis Lambda     (POST /impact-analysis)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 3 — /test-gen/file route (new API GW route on existing test_gen Lambda)
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_route" "test_gen_file" {
  count     = var.test_gen_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /test-gen/file"
  target    = "integrations/${aws_apigatewayv2_integration.test_gen_lambda[0].id}"
}

# ---------------------------------------------------------------------------
# Phase 2 — Coverage ingestion Lambda (POST /coverage/ingest)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "coverage_ingest_lambda" {
  count = var.coverage_ingest_enabled ? 1 : 0
  name  = "${local.name_prefix}-coverage-ingest"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "coverage_ingest_policy" {
  count = var.coverage_ingest_enabled ? 1 : 0
  name  = "${local.name_prefix}-coverage-ingest-policy"

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
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"
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
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "coverage_ingest_policy" {
  count      = var.coverage_ingest_enabled ? 1 : 0
  role       = aws_iam_role.coverage_ingest_lambda[0].name
  policy_arn = aws_iam_policy.coverage_ingest_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_coverage_ingest" {
  count      = var.lambda_tracing_enabled && var.coverage_ingest_enabled ? 1 : 0
  role       = aws_iam_role.coverage_ingest_lambda[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_lambda_function" "coverage_ingest" {
  count            = var.coverage_ingest_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-coverage-ingest"
  role             = aws_iam_role.coverage_ingest_lambda[0].arn
  runtime          = "python3.12"
  handler          = "coverage_ingest.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 60
  memory_size      = 512

  environment {
    variables = {
      BEDROCK_KNOWLEDGE_BASE_ID         = local.effective_bedrock_knowledge_base_id
      BEDROCK_KB_DATA_SOURCE_ID         = local.effective_bedrock_kb_data_source_id
      GITHUB_KB_DATA_SOURCE_ID          = local.effective_github_kb_data_source_id
      KB_SYNC_BUCKET                    = aws_s3_bucket.kb_sync_documents[0].bucket
      GITHUB_KB_SYNC_PREFIX             = var.github_kb_sync_s3_prefix
      GITHUB_API_BASE                   = var.github_api_base
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "coverage_ingest" {
  count             = var.coverage_ingest_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.coverage_ingest[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_integration" "coverage_ingest_lambda" {
  count                  = var.coverage_ingest_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.coverage_ingest[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "coverage_ingest" {
  count     = var.coverage_ingest_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /coverage/ingest"
  target    = "integrations/${aws_apigatewayv2_integration.coverage_ingest_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_coverage_ingest" {
  count         = var.coverage_ingest_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayCoverageIngest"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.coverage_ingest[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Phase 4 — Impact analysis Lambda (POST /impact-analysis)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "impact_analysis_lambda" {
  count = var.impact_analysis_enabled ? 1 : 0
  name  = "${local.name_prefix}-impact-analysis"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "impact_analysis_policy" {
  count = var.impact_analysis_enabled ? 1 : 0
  name  = "${local.name_prefix}-impact-analysis-policy"

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
        Resource = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agent-runtime:Retrieve"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          local.github_app_private_key_secret_arn,
          local.github_app_ids_secret_arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.app.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "impact_analysis_policy" {
  count      = var.impact_analysis_enabled ? 1 : 0
  role       = aws_iam_role.impact_analysis_lambda[0].name
  policy_arn = aws_iam_policy.impact_analysis_policy[0].arn
}

resource "aws_iam_role_policy_attachment" "xray_impact_analysis" {
  count      = var.lambda_tracing_enabled && var.impact_analysis_enabled ? 1 : 0
  role       = aws_iam_role.impact_analysis_lambda[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_lambda_function" "impact_analysis" {
  count            = var.impact_analysis_enabled ? 1 : 0
  function_name    = "${local.name_prefix}-impact-analysis"
  role             = aws_iam_role.impact_analysis_lambda[0].arn
  runtime          = "python3.12"
  handler          = "impact_analysis.app.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  timeout          = 120
  memory_size      = 1024

  environment {
    variables = {
      BEDROCK_MODEL_ID                  = var.bedrock_model_id
      IMPACT_ANALYSIS_MODEL_ID          = var.impact_analysis_model_id
      BEDROCK_KNOWLEDGE_BASE_ID         = local.effective_bedrock_knowledge_base_id
      IMPACT_ANALYSIS_KB_TOP_K          = tostring(var.impact_analysis_kb_top_k)
      GITHUB_API_BASE                   = var.github_api_base
      GITHUB_APP_PRIVATE_KEY_SECRET_ARN = local.github_app_private_key_secret_arn
      GITHUB_APP_IDS_SECRET_ARN         = local.github_app_ids_secret_arn
    }
  }

  tracing_config {
    mode = local.lambda_tracing_mode
  }
}

resource "aws_cloudwatch_log_group" "impact_analysis" {
  count             = var.impact_analysis_enabled ? 1 : 0
  name              = "/aws/lambda/${aws_lambda_function.impact_analysis[0].function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_integration" "impact_analysis_lambda" {
  count                  = var.impact_analysis_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.impact_analysis[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "impact_analysis" {
  count     = var.impact_analysis_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /impact-analysis"
  target    = "integrations/${aws_apigatewayv2_integration.impact_analysis_lambda[0].id}"
}

resource "aws_lambda_permission" "allow_apigw_impact_analysis" {
  count         = var.impact_analysis_enabled ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGatewayImpactAnalysis"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.impact_analysis[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}
