# Chatbot Webapp - Example Values

This directory contains example values files for different deployment scenarios.

## Files

- `values.yaml` - Default values with all options documented
- `values-simple.yaml` - Simple deployment without authentication
- `values-keycloak.yaml` - Full deployment with Keycloak
- `values-production.yaml` - Production-ready configuration
- `values-dev.yaml` - Development environment configuration

## Usage

Choose the appropriate values file for your scenario:

```bash
# Simple deployment
helm install chatbot ./helm/chatbot-webapp -f helm/chatbot-webapp/examples/values-simple.yaml

# With Keycloak
helm install chatbot ./helm/chatbot-webapp -f helm/chatbot-webapp/examples/values-keycloak.yaml

# Production
helm install chatbot ./helm/chatbot-webapp -f helm/chatbot-webapp/examples/values-production.yaml
```

## Customization

1. Copy the example file that matches your scenario
2. Modify the values (image repository, domains, etc.)
3. Install or upgrade the chart with your custom values

```bash
cp helm/chatbot-webapp/examples/values-simple.yaml my-values.yaml
# Edit my-values.yaml
helm install chatbot ./helm/chatbot-webapp -f my-values.yaml
```
