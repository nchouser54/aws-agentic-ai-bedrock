# ---------------------------------------------------------------------------
# Webhook TLS proxy EC2 (GHES over Direct Connect, port 443)
#
# When webhook_proxy_enabled=true, Terraform creates a small EC2 instance
# running Nginx that:
#   - Listens on port 443 with your internal CA cert
#   - Proxies /webhook/github to API Gateway over the private VPC endpoint
#
# Traffic path:
#   GHES :443 -> proxy EC2 (private IP) -> execute-api VPCE -> API GW -> Lambda
#
# Prerequisites:
#   - webhook_private_enabled must also be true (VPCE must exist)
#   - Store your internal CA cert PEM in Secrets Manager -> webhook_proxy_tls_cert_secret_arn
#   - Store the matching private key PEM in Secrets Manager -> webhook_proxy_tls_key_secret_arn
#
# Usage:
#   terraform apply
#   terraform output webhook_proxy_private_ip   -> give this IP to GHES
#   terraform output webhook_proxy_url          -> GHES webhook URL
#
# In GHES webhook settings:
#   URL:    https://<webhook_proxy_private_ip>/webhook/github
#   Secret: <your webhook HMAC secret>
#   SSL:    Enabled (cert issued by your internal CA which GHES already trusts)
# ---------------------------------------------------------------------------

# Latest Amazon Linux 2 AMI (same approach as webapp EC2)
data "aws_ssm_parameter" "webhook_proxy_ami" {
  count = var.webhook_proxy_enabled && trimspace(var.webhook_proxy_ami_id) == "" ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2"
}

# Get VPC ID from subnet (needed for SG)
data "aws_subnet" "webhook_proxy" {
  count = var.webhook_proxy_enabled ? 1 : 0
  id    = var.webhook_proxy_subnet_id
}

# Security group: inbound 443 from GHES CIDRs, outbound to VPCE on 443
resource "aws_security_group" "webhook_proxy" {
  count       = var.webhook_proxy_enabled ? 1 : 0
  name        = "${local.name_prefix}-webhook-proxy-sg"
  description = "Nginx webhook proxy: inbound HTTPS from GHES, outbound to execute-api VPCE"
  vpc_id      = data.aws_subnet.webhook_proxy[0].vpc_id

  ingress {
    description = "HTTPS from GHES over Direct Connect"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.webhook_proxy_allowed_cidrs
  }

  egress {
    description = "HTTPS outbound to API Gateway VPC endpoint"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-webhook-proxy-sg"
  })
}

# IAM role: EC2 needs to read the TLS cert and key from Secrets Manager
resource "aws_iam_role" "webhook_proxy" {
  count = var.webhook_proxy_enabled ? 1 : 0
  name  = "${local.name_prefix}-webhook-proxy-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "webhook_proxy_secrets" {
  count = var.webhook_proxy_enabled ? 1 : 0
  name  = "read-tls-secrets"
  role  = aws_iam_role.webhook_proxy[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        var.webhook_proxy_tls_cert_secret_arn,
        var.webhook_proxy_tls_key_secret_arn,
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "webhook_proxy" {
  count = var.webhook_proxy_enabled ? 1 : 0
  name  = "${local.name_prefix}-webhook-proxy-ec2"
  role  = aws_iam_role.webhook_proxy[0].name
}

# Proxy EC2 — t3.micro, private subnet, no public IP
resource "aws_instance" "webhook_proxy" {
  count         = var.webhook_proxy_enabled ? 1 : 0
  ami           = trimspace(var.webhook_proxy_ami_id) != "" ? trimspace(var.webhook_proxy_ami_id) : data.aws_ssm_parameter.webhook_proxy_ami[0].value
  instance_type = var.webhook_proxy_instance_type
  subnet_id     = var.webhook_proxy_subnet_id
  private_ip    = trimspace(var.webhook_proxy_private_ip) != "" ? trimspace(var.webhook_proxy_private_ip) : null
  key_name      = trimspace(var.webhook_proxy_key_name) != "" ? trimspace(var.webhook_proxy_key_name) : null

  iam_instance_profile        = aws_iam_instance_profile.webhook_proxy[0].name
  vpc_security_group_ids      = [aws_security_group.webhook_proxy[0].id]
  associate_public_ip_address = false

  # Computes the API GW hostname once at plan time; stable after first deploy.
  user_data = <<-EOT
    #!/bin/bash
    set -euxo pipefail

    REGION="${data.aws_region.current.name}"
    APIGW_HOST="${aws_apigatewayv2_api.webhook.id}.execute-api.${data.aws_region.current.name}.amazonaws.com"
    CERT_ARN="${var.webhook_proxy_tls_cert_secret_arn}"
    KEY_ARN="${var.webhook_proxy_tls_key_secret_arn}"

    yum update -y
    amazon-linux-extras install nginx1 -y || yum install -y nginx
    yum install -y awscli jq

    mkdir -p /etc/nginx/ssl
    chmod 700 /etc/nginx/ssl

    # Pull cert and key from Secrets Manager
    aws secretsmanager get-secret-value \
      --region "$REGION" \
      --secret-id "$CERT_ARN" \
      --query SecretString \
      --output text > /etc/nginx/ssl/webhook-proxy.crt

    aws secretsmanager get-secret-value \
      --region "$REGION" \
      --secret-id "$KEY_ARN" \
      --query SecretString \
      --output text > /etc/nginx/ssl/webhook-proxy.key

    chmod 644 /etc/nginx/ssl/webhook-proxy.crt
    chmod 600 /etc/nginx/ssl/webhook-proxy.key

    # Write Nginx reverse proxy config
    cat > /etc/nginx/conf.d/webhook-proxy.conf <<NGINX
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/webhook-proxy.crt;
    ssl_certificate_key /etc/nginx/ssl/webhook-proxy.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /webhook/github {
        proxy_pass          https://$APIGW_HOST/webhook/github;
        proxy_set_header    Host $APIGW_HOST;
        proxy_set_header    X-Forwarded-For \$remote_addr;
        proxy_set_header    X-Real-IP       \$remote_addr;
        proxy_ssl_verify    on;
        proxy_ssl_server_name on;
        proxy_read_timeout  30s;
        proxy_connect_timeout 10s;
        proxy_send_timeout  30s;
    }

    # Reject all other paths
    location / {
        return 404;
    }
}
NGINX

    # Remove default server block
    rm -f /etc/nginx/conf.d/default.conf /etc/nginx/default.d/*.conf

    # Test config before starting
    nginx -t

    systemctl enable nginx
    systemctl restart nginx
  EOT

  lifecycle {
    ignore_changes = [user_data]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-webhook-proxy"
  })

  depends_on = [
    aws_iam_instance_profile.webhook_proxy,
    aws_vpc_endpoint.webhook_execute_api,
  ]
}
