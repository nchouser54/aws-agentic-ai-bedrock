# ---------------------------------------------------------------------------
# Private webhook endpoint: execute-api VPC endpoint (GHES over Direct Connect)
#
# Enables GHES to deliver webhooks to a PRIVATE IP with no public internet path.
# All traffic stays on Direct Connect -> VPC endpoint ENI -> API Gateway -> Lambda.
#
# How to use:
#   1. Add to terraform.tfvars:
#        webhook_private_enabled       = true
#        webhook_private_vpc_id        = "vpc-xxxxxxxx"
#        webhook_private_subnet_ids    = ["subnet-xxxxxxxx"]   # single subnet = single stable IP
#        webhook_private_allowed_cidrs = ["10.x.x.x/32"]       # your GHES host IP
#
#   2. terraform apply
#
#   3. Get the private IP:
#        terraform output webhook_vpce_private_ips
#      e.g. ["10.1.2.50"]
#
#   4. Open a firewall hole: GHES host -> 10.1.2.50 : 443 / TCP
#
#   5. On the GHES server, map the hostname to that private IP in /etc/hosts:
#        10.1.2.50  <api_id>.execute-api.us-gov-west-1.amazonaws.com
#      (exact hostname is in: terraform output webhook_private_url)
#
#   6. Set GHES webhook URL to:
#        terraform output webhook_private_url
#      e.g. https://<api_id>.execute-api.us-gov-west-1.amazonaws.com/webhook/github
#
# NOTE: The API Gateway still has a public endpoint — GHES just routes to the
# private IP via /etc/hosts. The existing HMAC signature validation in the Lambda
# ensures only GitHub-signed payloads are processed.
# ---------------------------------------------------------------------------

resource "aws_security_group" "webhook_vpce" {
  count       = var.webhook_private_enabled ? 1 : 0
  name        = "${local.name_prefix}-webhook-vpce-sg"
  description = "Allow GHES to reach the execute-api VPC endpoint over Direct Connect"
  vpc_id      = var.webhook_private_vpc_id

  ingress {
    description = "GHES webhook delivery over Direct Connect"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.webhook_private_allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-webhook-vpce-sg"
  })
}

resource "aws_vpc_endpoint" "webhook_execute_api" {
  count              = var.webhook_private_enabled ? 1 : 0
  vpc_id             = var.webhook_private_vpc_id
  service_name       = "com.amazonaws.${data.aws_region.current.name}.execute-api"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = var.webhook_private_subnet_ids
  security_group_ids = [aws_security_group.webhook_vpce[0].id]

  # private_dns_enabled=false: GHES is on a different network (other side of DX),
  # so VPC-internal DNS override won't help it. We use /etc/hosts on GHES instead.
  private_dns_enabled = false

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-webhook-vpce"
  })
}

# Resolve the VPC endpoint ENI IDs -> private IPs for firewall rules and /etc/hosts.
data "aws_network_interfaces" "webhook_vpce" {
  count = var.webhook_private_enabled ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [var.webhook_private_vpc_id]
  }
  filter {
    name   = "description"
    values = ["VPC Endpoint Interface ${aws_vpc_endpoint.webhook_execute_api[0].id}"]
  }

  depends_on = [aws_vpc_endpoint.webhook_execute_api]
}

data "aws_network_interface" "webhook_vpce_enis" {
  for_each = var.webhook_private_enabled ? toset(data.aws_network_interfaces.webhook_vpce[0].ids) : toset([])
  id       = each.value
}
