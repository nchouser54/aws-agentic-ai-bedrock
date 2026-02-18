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
  description = "Effective secret ARNs in use (managed by Terraform or existing)"
  value = {
    github_webhook_secret  = local.github_webhook_secret_arn
    github_app_private_key = local.github_app_private_key_secret_arn
    github_app_ids         = local.github_app_ids_secret_arn
    atlassian_credentials  = local.atlassian_credentials_secret_arn
  }
}

output "chatbot_url" {
  description = "Jira/Confluence chatbot query endpoint"
  value       = var.chatbot_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/chatbot/query" : ""
}

output "chatbot_websocket_url" {
  description = "Chatbot websocket endpoint for true streaming transport"
  value       = var.chatbot_enabled && var.chatbot_websocket_enabled ? replace(aws_apigatewayv2_stage.chatbot_ws[0].invoke_url, "https://", "wss://") : ""
}

output "teams_chatbot_url" {
  description = "Microsoft Teams adapter endpoint"
  value       = var.chatbot_enabled && var.teams_adapter_enabled ? "${aws_apigatewayv2_api.webhook.api_endpoint}/chatbot/teams" : ""
}

output "kb_sync_function_name" {
  description = "Scheduled Confluence to Knowledge Base sync Lambda function name"
  value       = var.kb_sync_enabled ? aws_lambda_function.confluence_kb_sync[0].function_name : ""
}

output "github_kb_sync_function_name" {
  description = "Scheduled GitHub docs to Knowledge Base sync Lambda function name"
  value       = var.github_kb_sync_enabled ? aws_lambda_function.github_kb_sync[0].function_name : ""
}

output "kb_sync_documents_bucket" {
  description = "S3 bucket storing normalized Confluence documents for KB ingestion"
  value       = local.kb_sync_assets_enabled ? aws_s3_bucket.kb_sync_documents[0].bucket : ""
}

output "bedrock_kb_effective" {
  description = "Effective Bedrock Knowledge Base IDs in use (managed or existing)"
  value = {
    managed_creation_enabled = local.manage_bedrock_kb_in_terraform
    managed_role_arn         = local.effective_managed_bedrock_kb_role_arn
    managed_collection_arn   = local.effective_managed_bedrock_kb_opensearch_collection_arn
    knowledge_base_id        = local.effective_bedrock_knowledge_base_id
    kb_data_source_id        = local.effective_bedrock_kb_data_source_id
    github_kb_data_source_id = local.effective_github_kb_data_source_id
  }
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

output "chatbot_observability_dashboard_name" {
  description = "CloudWatch dashboard name for chatbot observability"
  value       = var.chatbot_enabled && var.chatbot_observability_enabled ? aws_cloudwatch_dashboard.chatbot_observability[0].dashboard_name : ""
}

output "webapp_bucket_name" {
  description = "S3 bucket name hosting the static chatbot web UI"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "s3" ? aws_s3_bucket.webapp[0].bucket : ""
}

output "webapp_url" {
  description = "Public URL for the hosted static chatbot web UI (S3 website or EC2 Elastic IP)"
  value = !var.webapp_hosting_enabled ? "" : (
    var.webapp_hosting_mode == "s3" ? "http://${aws_s3_bucket_website_configuration.webapp[0].website_endpoint}" : (
      var.webapp_private_only ? "http://${local.webapp_ec2_byo ? data.aws_instance.webapp_byo[0].private_ip : aws_instance.webapp[0].private_ip}" : "http://${aws_eip.webapp[0].public_ip}"
    )
  )
}

output "webapp_hosting_mode" {
  description = "Active static webapp hosting mode"
  value       = var.webapp_hosting_enabled ? var.webapp_hosting_mode : ""
}

output "webapp_static_ip" {
  description = "Elastic IP address for EC2-hosted static chatbot web UI"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" && !var.webapp_private_only ? aws_eip.webapp[0].public_ip : ""
}

output "webapp_https_url" {
  description = "HTTPS URL for NLB-fronted static chatbot web UI when TLS is enabled"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" && var.webapp_tls_enabled ? "https://${aws_lb.webapp[0].dns_name}" : ""
}

output "webapp_instance_id" {
  description = "EC2 instance ID hosting the static chatbot web UI in ec2_eip mode"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" ? local.webapp_instance_id : ""
}

output "webapp_private_ip" {
  description = "Private IP address of the EC2-hosted static chatbot web UI in ec2_eip mode"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" ? (
    local.webapp_ec2_byo ? data.aws_instance.webapp_byo[0].private_ip : aws_instance.webapp[0].private_ip
  ) : ""
}

output "webapp_configured_private_ip" {
  description = "Configured fixed private IP for EC2 webapp instance (empty when auto-assigned or BYO)"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" && !local.webapp_ec2_byo ? trimspace(var.webapp_ec2_private_ip) : ""
}

output "webapp_setup_script" {
  description = "One-time setup script to run on a BYO EC2 instance (only populated when webapp_ec2_instance_id is set)"
  sensitive   = false
  value = !local.webapp_ec2_byo ? "" : <<-SCRIPT
    #!/bin/bash
    # Run this once on your EC2 instance (Amazon Linux 2 / RHEL) as root or via sudo.
    set -euxo pipefail
    yum update -y
    amazon-linux-extras install nginx1 -y || yum install -y nginx
    yum install -y awscli || true
    mkdir -p /usr/share/nginx/html
    aws s3 sync "s3://${local.webapp_ec2_byo ? aws_s3_bucket.webapp[0].bucket : ""}" /usr/share/nginx/html \
      --delete --exclude "*" --include "*.html" --include "*.js" --include "*.css"
    chown -R nginx:nginx /usr/share/nginx/html
    systemctl enable nginx && systemctl restart nginx
    # Optional: auto-sync every 5 minutes
    cat > /etc/cron.d/webapp-sync <<'CRON'
    SHELL=/bin/bash
    PATH=/usr/local/bin:/usr/bin:/bin
    */5 * * * * root aws s3 sync "s3://${local.webapp_ec2_byo ? aws_s3_bucket.webapp[0].bucket : ""}" /usr/share/nginx/html --delete --exclude "*" --include "*.html" --include "*.js" --include "*.css" && chown -R nginx:nginx /usr/share/nginx/html 2>&1 | logger -t webapp-sync
    CRON
    chmod 0644 /etc/cron.d/webapp-sync
  SCRIPT
}

output "webapp_https_private_ips" {
  description = "Configured internal NLB private IPs for HTTPS/443 access (when webapp_private_only=true and webapp_tls_private_ips provided)"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" && var.webapp_private_only && var.webapp_tls_enabled ? var.webapp_tls_private_ips : []
}

output "webapp_tls_static_ips" {
  description = "Static Elastic IPs attached to the HTTPS NLB (use for firewall allowlists)"
  value       = var.webapp_hosting_enabled && var.webapp_hosting_mode == "ec2_eip" && var.webapp_tls_enabled && !var.webapp_private_only ? [for ip in aws_eip.webapp_tls : ip.public_ip] : []
}

# ---------------------------------------------------------------------------
# 2-stage Bedrock + Check Run outputs
# ---------------------------------------------------------------------------

output "bedrock_model_light_effective" {
  description = "Effective stage-1 (planner) Bedrock model ID in use."
  value       = coalesce(var.bedrock_model_light, var.bedrock_model_id)
}

output "bedrock_model_heavy_effective" {
  description = "Effective stage-2 (reviewer) Bedrock model ID in use."
  value       = coalesce(var.bedrock_model_heavy, var.bedrock_model_id)
}

output "check_run_name" {
  description = "GitHub Check Run name created by the AI reviewer."
  value       = var.check_run_name
}

output "webhook_receiver_runtime" {
  description = "Lambda runtime selected for the webhook receiver."
  value       = var.webhook_receiver_runtime
}
