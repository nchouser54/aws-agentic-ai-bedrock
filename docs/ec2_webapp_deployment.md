# Running Chatbot Webapp on EC2

Complete guide to deploy your chatbot webapp on a single EC2 instance.

---

## Overview

This deploys your chatbot UI on EC2 with:
- ✅ Nginx serving static files
- ✅ systemd service for auto-restart
- ✅ HTTPS with Let's Encrypt (optional)
- ✅ Auto-start on reboot
- ✅ Logging and monitoring

**Time to deploy:** 15-20 minutes

---

## Prerequisites

- [ ] AWS account with EC2 access
- [ ] Domain name (for HTTPS) or use HTTP
- [ ] API Gateway URL (from your Lambda backend)
- [ ] SSH key pair for EC2 access

---

## Step 1: Launch EC2 Instance

### Via AWS Console

1. **Go to EC2 Dashboard** → Launch Instance

2. **Configure:**
   - **Name:** `chatbot-webapp`
   - **AMI:** Amazon Linux 2023 (or Ubuntu 22.04)
   - **Instance type:** `t3.micro` (1 vCPU, 1GB RAM - $7/month)
   - **Key pair:** Select or create new
   - **Network:**
     - VPC: Your VPC
     - Subnet: Public subnet
     - Auto-assign public IP: **Enable**
   - **Security group:**
     - Allow SSH (22) from your IP
     - Allow HTTP (80) from 0.0.0.0/0
     - Allow HTTPS (443) from 0.0.0.0/0 (if using SSL)

3. **Storage:** 8GB gp3 (default)

4. **Launch**

### Via AWS CLI

```bash
# Create security group
aws ec2 create-security-group \
  --group-name chatbot-webapp-sg \
  --description "Chatbot webapp security group" \
  --vpc-id vpc-xxxxx

# Get security group ID
SG_ID=$(aws ec2 describe-security-groups \
  --group-names chatbot-webapp-sg \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

# Allow SSH from your IP
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32

# Allow HTTP
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

# Allow HTTPS
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

# Launch instance
aws ec2 run-instances \
  --image-id ami-xxxxx \
  --instance-type t3.micro \
  --key-name your-key \
  --security-group-ids $SG_ID \
  --subnet-id subnet-xxxxx \
  --associate-public-ip-address \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=chatbot-webapp}]'
```

---

## Step 2: Connect to EC2

```bash
# Get public IP
INSTANCE_IP=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=chatbot-webapp" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

# SSH connect
ssh -i your-key.pem ec2-user@$INSTANCE_IP

# Or for Ubuntu:
ssh -i your-key.pem ubuntu@$INSTANCE_IP
```

---

## Step 3: Install Dependencies

### For Amazon Linux 2023

```bash
# Update system
sudo dnf update -y

# Install nginx, git
sudo dnf install -y nginx git

# Start and enable nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Verify
curl http://localhost
# Should see nginx welcome page
```

### For Ubuntu 22.04

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install nginx, git
sudo apt install -y nginx git

# Start and enable nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Verify
curl http://localhost
```

---

## Step 4: Deploy Webapp Files

### Option A: Clone from Git

```bash
# Clone your repo
cd /tmp
git clone https://github.com/nchouser54/aws-agentic-ai-bedrock.git
cd aws-agentic-ai-bedrock

# Copy webapp files
sudo cp -r webapp/* /usr/share/nginx/html/

# Set permissions
sudo chown -R nginx:nginx /usr/share/nginx/html/
sudo chmod -R 755 /usr/share/nginx/html/
```

### Option B: Upload Files Directly

```bash
# From your local machine
cd /path/to/aws-agentic-ai-pr-reviewer

# Upload webapp files
scp -i your-key.pem -r webapp/* ec2-user@$INSTANCE_IP:/tmp/

# On EC2
sudo mv /tmp/* /usr/share/nginx/html/
sudo chown -R nginx:nginx /usr/share/nginx/html/
sudo chmod -R 755 /usr/share/nginx/html/
```

---

## Step 5: Configure Webapp

### Update config.js with your API Gateway URL

```bash
# On EC2
sudo nano /usr/share/nginx/html/config.js
```

**Replace with your values:**
```javascript
const CONFIG = {
    chatbotUrl: 'https://YOUR-API-ID.execute-api.us-gov-west-1.amazonaws.com',
    environment: 'production'
};
```

**Save:** `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Step 6: Configure Nginx

### HTTP Only (Simple)

```bash
# Backup default config
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup

# Edit nginx config
sudo nano /etc/nginx/conf.d/chatbot.conf
```

**Add this configuration:**
```nginx
server {
    listen 80;
    server_name _;

    # Root directory
    root /usr/share/nginx/html;
    index index.html;

    # Logging
    access_log /var/log/nginx/chatbot-access.log;
    error_log /var/log/nginx/chatbot-error.log;

    # Main location
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Static file caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

**Test and reload:**
```bash
sudo nginx -t
sudo systemctl reload nginx
```

### HTTPS with Let's Encrypt (Recommended)

```bash
# Install certbot
# Amazon Linux 2023:
sudo dnf install -y certbot python3-certbot-nginx

# Ubuntu:
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (replace with your domain)
sudo certbot --nginx -d chatbot.your-domain.com

# Follow prompts:
# - Enter email
# - Agree to terms
# - Redirect HTTP to HTTPS: Yes

# Test auto-renewal
sudo certbot renew --dry-run
```

**Certbot will automatically update nginx config for HTTPS!**

### HTTPS with Existing Certificate

```bash
# Upload your certificates
scp -i your-key.pem cert.crt ec2-user@$INSTANCE_IP:/tmp/
scp -i your-key.pem cert.key ec2-user@$INSTANCE_IP:/tmp/

# On EC2
sudo mkdir -p /etc/nginx/ssl
sudo mv /tmp/cert.crt /etc/nginx/ssl/
sudo mv /tmp/cert.key /etc/nginx/ssl/
sudo chmod 600 /etc/nginx/ssl/cert.key

# Update nginx config
sudo nano /etc/nginx/conf.d/chatbot.conf
```

**HTTPS configuration:**
```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name chatbot.your-domain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name chatbot.your-domain.com;

    # SSL certificates
    ssl_certificate /etc/nginx/ssl/cert.crt;
    ssl_certificate_key /etc/nginx/ssl/cert.key;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Root directory
    root /usr/share/nginx/html;
    index index.html;

    # Logging
    access_log /var/log/nginx/chatbot-access.log;
    error_log /var/log/nginx/chatbot-error.log;

    # Main location
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Health check
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Static file caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

**Test and reload:**
```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Step 7: Configure DNS (If Using Domain)

### Update DNS A Record

Point your domain to EC2 public IP:

```
Type: A
Name: chatbot (or @)
Value: YOUR-EC2-PUBLIC-IP
TTL: 300
```

### Verify DNS

```bash
# Wait a few minutes, then test
dig chatbot.your-domain.com

# Or
nslookup chatbot.your-domain.com
```

---

## Step 8: Test Deployment

```bash
# From EC2
curl http://localhost
curl http://localhost/health

# From your local machine
curl http://YOUR-EC2-IP
curl http://YOUR-EC2-IP/health

# With domain
curl https://chatbot.your-domain.com
```

**Open in browser:**
- `http://YOUR-EC2-IP` (HTTP)
- `https://chatbot.your-domain.com` (HTTPS)

---

## Step 9: Setup Auto-Deployment (Optional)

### Create deployment script

```bash
sudo nano /usr/local/bin/deploy-chatbot.sh
```

**Script content:**
```bash
#!/bin/bash
set -e

echo "Deploying chatbot webapp..."

# Backup current files
BACKUP_DIR="/var/backups/chatbot-$(date +%Y%m%d-%H%M%S)"
mkdir -p $BACKUP_DIR
cp -r /usr/share/nginx/html/* $BACKUP_DIR/

# Clone latest code
cd /tmp
rm -rf aws-agentic-ai-bedrock
git clone https://github.com/nchouser54/aws-agentic-ai-bedrock.git
cd aws-agentic-ai-bedrock

# Copy files
cp -r webapp/* /usr/share/nginx/html/

# Set permissions
chown -R nginx:nginx /usr/share/nginx/html/
chmod -R 755 /usr/share/nginx/html/

# Reload nginx
nginx -t && systemctl reload nginx

echo "Deployment complete!"
```

**Make executable:**
```bash
sudo chmod +x /usr/local/bin/deploy-chatbot.sh
```

**Deploy updates:**
```bash
sudo /usr/local/bin/deploy-chatbot.sh
```

---

## Step 10: Monitoring and Logs

### View Nginx Logs

```bash
# Access logs
sudo tail -f /var/log/nginx/chatbot-access.log

# Error logs
sudo tail -f /var/log/nginx/chatbot-error.log

# All nginx logs
sudo tail -f /var/log/nginx/*.log
```

### System Monitoring

```bash
# Check nginx status
sudo systemctl status nginx

# Check CPU/Memory
top

# Or use htop (install first)
sudo dnf install -y htop  # Amazon Linux
sudo apt install -y htop  # Ubuntu
htop

# Disk usage
df -h
```

### Setup CloudWatch Logs (Optional)

```bash
# Install CloudWatch agent
# Amazon Linux:
sudo dnf install -y amazon-cloudwatch-agent

# Ubuntu:
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
sudo dpkg -i -E ./amazon-cloudwatch-agent.deb

# Configure
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard

# When prompted:
# - Logs to monitor: /var/log/nginx/*.log
# - Log group: /ec2/chatbot-webapp
```

---

## Maintenance

### Update Webapp Files

```bash
# Pull latest changes
cd /tmp/aws-agentic-ai-bedrock
git pull origin main

# Copy updates
sudo cp -r webapp/* /usr/share/nginx/html/

# Reload nginx
sudo systemctl reload nginx
```

### Update System

```bash
# Amazon Linux
sudo dnf update -y

# Ubuntu
sudo apt update && sudo apt upgrade -y

# Reboot if kernel updated
sudo reboot
```

### SSL Certificate Renewal

```bash
# Let's Encrypt auto-renews, but you can manually test:
sudo certbot renew --dry-run

# Check expiration
sudo certbot certificates
```

---

## Backup and Recovery

### Backup Webapp Files

```bash
# Create backup
sudo tar -czf /tmp/chatbot-backup-$(date +%Y%m%d).tar.gz \
  -C /usr/share/nginx/html .

# Download to local machine
scp -i your-key.pem ec2-user@$INSTANCE_IP:/tmp/chatbot-backup-*.tar.gz .
```

### Restore from Backup

```bash
# Upload backup
scp -i your-key.pem chatbot-backup-*.tar.gz ec2-user@$INSTANCE_IP:/tmp/

# On EC2
sudo tar -xzf /tmp/chatbot-backup-*.tar.gz -C /usr/share/nginx/html/
sudo chown -R nginx:nginx /usr/share/nginx/html/
sudo systemctl reload nginx
```

### Create AMI Snapshot

```bash
# From local machine
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=chatbot-webapp" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)

aws ec2 create-image \
  --instance-id $INSTANCE_ID \
  --name "chatbot-webapp-backup-$(date +%Y%m%d)" \
  --description "Chatbot webapp AMI snapshot"
```

---

## Scaling Up

### Upgrade Instance Type

```bash
# Stop instance
aws ec2 stop-instances --instance-ids $INSTANCE_ID

# Wait for stopped
aws ec2 wait instance-stopped --instance-ids $INSTANCE_ID

# Change instance type
aws ec2 modify-instance-attribute \
  --instance-id $INSTANCE_ID \
  --instance-type t3.small

# Start instance
aws ec2 start-instances --instance-ids $INSTANCE_ID
```

### Add Load Balancer (For HA)

See [EKS Deployment Guide](eks_deployment.md) for multi-instance setup with ALB.

---

## Troubleshooting

### Website Not Loading

```bash
# Check nginx is running
sudo systemctl status nginx

# Restart nginx
sudo systemctl restart nginx

# Check nginx config
sudo nginx -t

# Check logs
sudo tail -50 /var/log/nginx/error.log
```

### 502 Bad Gateway

```bash
# Check if nginx can access files
ls -la /usr/share/nginx/html/

# Fix permissions
sudo chown -R nginx:nginx /usr/share/nginx/html/
sudo chmod -R 755 /usr/share/nginx/html/
```

### SSL Certificate Issues

```bash
# Check certificate
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Test SSL
curl -v https://chatbot.your-domain.com
```

### High CPU/Memory Usage

```bash
# Check processes
top

# Check nginx connections
sudo netstat -plant | grep nginx

# Increase instance size if needed
```

### Can't Connect via SSH

```bash
# Check security group allows SSH from your IP
aws ec2 describe-security-groups --group-ids $SG_ID

# Update if needed
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_NEW_IP/32
```

---

## Cost Estimate

| Resource | Specification | Monthly Cost |
|----------|--------------|--------------|
| EC2 t3.micro | 1 vCPU, 1GB RAM | $7 |
| EBS gp3 | 8GB | $0.64 |
| Data transfer | ~10GB egress | $0.90 |
| Elastic IP | (if using) | $3.60 |
| **Total** | | **~$8-12/month** |

**Notes:**
- GovCloud pricing ~10-20% higher
- Free tier eligible for first 12 months (t2.micro)
- Use Reserved Instance for production (~40% discount)

---

## Security Hardening

### 1. Restrict SSH Access

```bash
# Only allow your IP
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32 \
  --description "SSH from office"
```

### 2. Install fail2ban

```bash
# Amazon Linux
sudo dnf install -y fail2ban

# Ubuntu
sudo apt install -y fail2ban

# Start and enable
sudo systemctl start fail2ban
sudo systemctl enable fail2ban
```

### 3. Setup Automatic Updates

```bash
# Amazon Linux
sudo dnf install -y dnf-automatic
sudo systemctl enable --now dnf-automatic.timer

# Ubuntu
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 4. Enable CloudTrail Logging

```bash
# Log all EC2 API calls
aws cloudtrail create-trail \
  --name ec2-chatbot-trail \
  --s3-bucket-name your-cloudtrail-bucket
```

---

## Summary

You now have a production-ready chatbot webapp running on EC2!

**What you have:**
- ✅ Nginx serving your webapp
- ✅ HTTPS with automatic certificate renewal
- ✅ Auto-start on reboot
- ✅ Logging and monitoring
- ✅ Backup strategy
- ✅ Update process

**Next steps:**
- Monitor logs: `sudo tail -f /var/log/nginx/*.log`
- Access chatbot: `https://chatbot.your-domain.com`
- Deploy updates: `sudo /usr/local/bin/deploy-chatbot.sh`

**For high availability:**
- See [EKS Deployment Guide](eks_deployment.md) for Kubernetes
- See [ArgoCD Guide](argocd_deployment.md) for GitOps
