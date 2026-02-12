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
