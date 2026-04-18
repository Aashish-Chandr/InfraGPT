#!/usr/bin/env bash
# Vault setup script — configures Kubernetes auth and creates initial secrets
# Run after vault-init: make vault-setup

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-$(cat vault/vault-keys.json | jq -r '.root_token')}"

export VAULT_ADDR VAULT_TOKEN

echo "==> Enabling KV secrets engine v2"
vault secrets enable -path=secret kv-v2 2>/dev/null || echo "KV already enabled"

echo "==> Writing application policies"
vault policy write infragpt-app vault/policies/app-policy.hcl

echo "==> Enabling Kubernetes auth method"
vault auth enable kubernetes 2>/dev/null || echo "Kubernetes auth already enabled"

echo "==> Configuring Kubernetes auth"
KUBE_HOST=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.server}')
KUBE_CA=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.certificate-authority-data}' | base64 -d)
SA_JWT=$(kubectl create token vault-auth -n vault --duration=8760h 2>/dev/null || \
         kubectl get secret -n vault -o jsonpath='{.items[?(@.metadata.annotations.kubernetes\.io/service-account\.name=="vault-auth")].data.token}' | base64 -d)

vault write auth/kubernetes/config \
  kubernetes_host="${KUBE_HOST}" \
  kubernetes_ca_cert="${KUBE_CA}" \
  token_reviewer_jwt="${SA_JWT}"

echo "==> Creating Kubernetes auth roles"
vault write auth/kubernetes/role/infragpt-backend \
  bound_service_account_names=backend \
  bound_service_account_namespaces=production,staging \
  policies=infragpt-app \
  ttl=1h

vault write auth/kubernetes/role/infragpt-ai-engine \
  bound_service_account_names=ai-engine \
  bound_service_account_namespaces=ai-engine \
  policies=infragpt-app \
  ttl=1h

echo "==> Writing initial secrets (CHANGE THESE IN PRODUCTION)"
vault kv put secret/infragpt/database \
  host="infragpt-production.xxxx.us-east-1.rds.amazonaws.com" \
  username="infragpt_admin" \
  password="CHANGE_ME_IN_PRODUCTION" \
  port="5432" \
  name="infragpt"

vault kv put secret/infragpt/redis \
  url="redis://redis.production:6379/0"

vault kv put secret/infragpt/slack \
  webhook_url="https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"

vault kv put secret/infragpt/anthropic \
  api_key="sk-ant-CHANGE_ME"

echo "==> Vault setup complete!"
echo ""
echo "Verify with:"
echo "  vault kv get secret/infragpt/database"
echo "  vault read auth/kubernetes/role/infragpt-backend"
