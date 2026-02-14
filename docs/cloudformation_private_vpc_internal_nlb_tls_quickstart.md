# CloudFormation Quickstart (Existing VPC + Internal NLB TLS)

This stack deploys a private webapp endpoint with **internal NLB + TLS** using only existing VPC/subnets.

- No VPC creation
- No public IPs
- No public EIPs
- Private HTTPS endpoint only

## Template path

- `infra/cloudformation/private-webapp-internal-nlb-tls-existing-vpc.yaml`

## 1) Copy/paste deploy command

Run from repo root and replace placeholders:

```bash
aws cloudformation deploy \
  --stack-name ai-pr-reviewer-private-webapp-internal-tls \
  --template-file infra/cloudformation/private-webapp-internal-nlb-tls-existing-vpc.yaml \
  --parameter-overrides \
    EnvironmentName=nonprod \
    VpcId=vpc-REPLACE \
    InstanceSubnetId=subnet-PRIVATE-INSTANCE \
    NlbSubnetIdA=subnet-PRIVATE-NLB-A \
    NlbSubnetIdB=subnet-PRIVATE-NLB-B \
    AcmCertificateArn=arn:aws-us-gov:acm:us-gov-west-1:123456789012:certificate/REPLACE \
    AllowedCidr1=10.0.0.0/8 \
    AllowedCidr2=172.16.0.0/12 \
    AllowedCidr3=192.168.0.0/16 \
    InstanceType=t3.micro \
    KeyName=
```

## 2) Copy/paste outputs command

```bash
aws cloudformation describe-stacks \
  --stack-name ai-pr-reviewer-private-webapp-internal-tls \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
```

## 3) Expected outputs

- `WebappInstanceId`
- `WebappPrivateIp`
- `InternalNlbDnsName`
- `InternalHttpsUrl`
- `TargetGroupArn`

## 4) Private DNS mapping (recommended)

Map private DNS to the internal NLB name, for example:

- `chatbot-ui.internal.example.com` -> `InternalNlbDnsName`

## 5) Validate private-only requirements

- EC2 has no public IP
- NLB is internal
- Endpoint reachable only over private network path (VPN/DX/TGW/etc.)

## 6) Optional: update stack (copy/paste)

```bash
aws cloudformation deploy \
  --stack-name ai-pr-reviewer-private-webapp-internal-tls \
  --template-file infra/cloudformation/private-webapp-internal-nlb-tls-existing-vpc.yaml \
  --parameter-overrides \
    EnvironmentName=nonprod \
    VpcId=vpc-REPLACE \
    InstanceSubnetId=subnet-PRIVATE-INSTANCE \
    NlbSubnetIdA=subnet-PRIVATE-NLB-A \
    NlbSubnetIdB=subnet-PRIVATE-NLB-B \
    AcmCertificateArn=arn:aws-us-gov:acm:us-gov-west-1:123456789012:certificate/REPLACE \
    AllowedCidr1=10.0.0.0/8 \
    AllowedCidr2= \
    AllowedCidr3= \
    InstanceType=t3.small \
    KeyName=
```

## 7) Optional: delete stack (copy/paste)

```bash
aws cloudformation delete-stack --stack-name ai-pr-reviewer-private-webapp-internal-tls
```
