output "webhook_url" {
  description = "GitHub App webhook URL"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/github"
}

output "queue_name" {
  description = "SQS queue name for PR reviews"
  value       = aws_sqs_queue.pr_review_queue.name
}

output "idempotency_table_name" {
  description = "DynamoDB idempotency table"
  value       = aws_dynamodb_table.idempotency.name
}

output "secret_arns" {
  description = "Secret ARNs to populate after deploy"
  value = {
    github_webhook_secret  = aws_secretsmanager_secret.github_webhook_secret.arn
    github_app_private_key = aws_secretsmanager_secret.github_app_private_key_pem.arn
    github_app_ids         = aws_secretsmanager_secret.github_app_ids.arn
    atlassian_credentials  = aws_secretsmanager_secret.atlassian_credentials.arn
  }
}

output "chatbot_url" {
  description = "Jira/Confluence chatbot query endpoint"
  value       = var.chatbot_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/chatbot/query" : ""
}

output "teams_chatbot_url" {
  description = "Microsoft Teams adapter endpoint"
  value       = var.chatbot_enabled && var.teams_adapter_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/chatbot/teams" : ""
}

output "kb_sync_function_name" {
  description = "Scheduled Confluence to Knowledge Base sync Lambda function name"
  value       = var.kb_sync_enabled ? aws_lambda_function.confluence_kb_sync[0].function_name : ""
}

output "kb_sync_documents_bucket" {
  description = "S3 bucket storing normalized Confluence documents for KB ingestion"
  value       = var.kb_sync_enabled ? aws_s3_bucket.kb_sync_documents[0].bucket : ""
}

output "release_notes_url" {
  description = "Release notes generator endpoint"
  value       = var.release_notes_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/release-notes/generate" : ""
}

output "sprint_report_url" {
  description = "Sprint report generator endpoint"
  value       = var.sprint_report_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/reports/sprint" : ""
}

output "test_gen_url" {
  description = "Test generation agent endpoint"
  value       = var.test_gen_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/test-gen/generate" : ""
}

output "pr_description_url" {
  description = "PR description generator endpoint"
  value       = var.pr_description_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/pr-description/generate" : ""
}
