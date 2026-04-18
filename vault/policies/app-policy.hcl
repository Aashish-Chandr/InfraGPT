# InfraGPT application policy
# Grants read access to all secrets under secret/infragpt/*

path "secret/data/infragpt/*" {
  capabilities = ["read"]
}

path "secret/metadata/infragpt/*" {
  capabilities = ["list", "read"]
}

# Allow applications to renew their own tokens
path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
