# CloudFormation Quickstart (Existing VPC Only)

This stack deploys a **private-only** chatbot webapp EC2 instance into your **existing VPC/subnet**.

- Does **not** create VPC/subnets/IGW/NAT
- Does **not** allocate public IP or EIP
- Can optionally attach to an existing internal ALB/NLB target group

## Template path

- `infra/cloudformation/private-webapp-existing-vpc.yaml`

## 1) Copy/paste deploy command

Run from repo root and replace placeholder values:

```bash
aws cloudformation deploy \
  --stack-name ai-pr-reviewer-private-webapp \
  --template-file infra/cloudformation/private-webapp-existing-vpc.yaml \
  --parameter-overrides \
    EnvironmentName=nonprod \
    VpcId=vpc-REPLACE \
    SubnetId=subnet-PRIVATE-REPLACE \
    AllowedCidr1=10.0.0.0/8 \
    AllowedCidr2=172.16.0.0/12 \
    AllowedCidr3=192.168.0.0/16 \
    InstanceType=t3.micro \
    KeyName= \
    ExistingTargetGroupArn=
```

If you have an existing internal target group, set `ExistingTargetGroupArn`.

## 2) Copy/paste outputs command

```bash
aws cloudformation describe-stacks \
  --stack-name ai-pr-reviewer-private-webapp \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
```

## 3) Expected outputs

- `WebappInstanceId`
- `WebappPrivateIp`
- `WebappSecurityGroupId`
- `ExistingTargetGroupAttached` (`true`/`false`)

## 4) Validate private-only requirements

- Instance has no public IP
- Instance is in your existing private subnet
- Security group ingress is internal CIDRs only
- No public load balancer created by this stack

## 5) Optional: update stack (copy/paste)

```bash
aws cloudformation deploy \
  --stack-name ai-pr-reviewer-private-webapp \
  --template-file infra/cloudformation/private-webapp-existing-vpc.yaml \
  --parameter-overrides \
    EnvironmentName=nonprod \
    VpcId=vpc-REPLACE \
    SubnetId=subnet-PRIVATE-REPLACE \
    AllowedCidr1=10.0.0.0/8 \
    AllowedCidr2= \
    AllowedCidr3= \
    InstanceType=t3.small \
    KeyName= \
    ExistingTargetGroupArn=arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:123456789012:targetgroup/internal-webapp/aaaaaaaaaaaaaaaa
```

## 6) Optional: delete stack (copy/paste)

```bash
aws cloudformation delete-stack --stack-name ai-pr-reviewer-private-webapp
```
