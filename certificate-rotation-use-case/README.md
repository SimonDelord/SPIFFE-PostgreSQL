# Certificate Rotation Use Case: SPIRE with Upstream Authority

This document describes our **implemented solution** for SPIRE CA rotation when non-SPIFFE applications need to trust SPIFFE certificates.

**Status: ✅ IMPLEMENTED AND TESTED**

---

## Table of Contents

1. [The Problem](#the-problem)
2. [The Solution](#the-solution)
3. [What We Implemented](#what-we-implemented)
4. [Step-by-Step Implementation](#step-by-step-implementation)
5. [Verification](#verification)
6. [Demo Results](#demo-results)

---

## The Problem

When SPIRE acts as a root CA with short validity (24h-1 year), non-SPIFFE applications like PostgreSQL must be updated every time the CA rotates. This creates operational burden and risk of outages.

---

## The Solution

Configure SPIRE to use a **long-lived root CA** (10 years) via the **UpstreamAuthority** plugin. Applications trust the root CA once, and SPIRE's intermediate CA can rotate transparently.

```
Root CA (10 years) → Signs → SPIRE Intermediate CA (1 year) → Signs → X.509-SVIDs (1 hour)
       ↑
  Apps trust this (set once!)
```

---

## What We Implemented

| Component | Details |
|-----------|---------|
| **Root CA** | 10-year validity, stored in Kubernetes Secret |
| **Plugin** | `UpstreamAuthority` with `disk` backend |
| **ConfigMap** | Set to `immutable: true` to prevent operator overwrites |
| **StatefulSet** | Patched to mount the root CA secret |

### Root CA Certificate

```
Subject: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
Validity:
    Not Before: Apr 21 23:49:25 2026 GMT
    Not After : Apr 18 23:49:25 2036 GMT
```

---

## Step-by-Step Implementation

### 1. Create Root CA (10-year validity)

```bash
mkdir -p certs && cd certs

# Generate 4096-bit RSA key
openssl genrsa -out root-ca.key 4096

# Create self-signed root CA certificate
openssl req -x509 -new -nodes -key root-ca.key -sha256 -days 3650 \
  -out root-ca.crt \
  -subj "/C=US/ST=State/L=City/O=My Organization/OU=SPIFFE Root CA/CN=SPIFFE Root CA"
```

### 2. Create Kubernetes Secret

```bash
oc create secret generic spire-upstream-ca \
  --from-file=ca.crt=root-ca.crt \
  --from-file=ca.key=root-ca.key \
  -n zero-trust-workload-identity-manager
```

### 3. Patch SPIRE ConfigMap (with immutable flag)

```bash
# Get current config
CONFIG=$(oc get configmap spire-server -n zero-trust-workload-identity-manager -o jsonpath='{.data.server\.conf}')

# Add UpstreamAuthority plugin
NEW_CONFIG=$(echo "$CONFIG" | jq '.plugins.UpstreamAuthority = [{"disk": {"plugin_data": {"cert_file_path": "/run/spire/upstream-ca/ca.crt", "key_file_path": "/run/spire/upstream-ca/ca.key"}}}]')

# Patch ConfigMap AND set immutable: true
oc patch configmap spire-server -n zero-trust-workload-identity-manager \
  --type='merge' \
  -p="{\"immutable\": true, \"data\": {\"server.conf\": $(echo "$NEW_CONFIG" | jq -c . | jq -Rs .)}}"
```

**Why `immutable: true`?** The Zero Trust Workload Identity Manager operator continuously reconciles the ConfigMap. Setting it as immutable prevents the operator from overwriting our UpstreamAuthority configuration.

### 4. Patch StatefulSet to Mount Secret

```bash
oc patch statefulset spire-server -n zero-trust-workload-identity-manager --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/volumes/-", "value": {"name": "upstream-ca", "secret": {"secretName": "spire-upstream-ca"}}},
  {"op": "add", "path": "/spec/template/spec/containers/0/volumeMounts/-", "value": {"name": "upstream-ca", "mountPath": "/run/spire/upstream-ca", "readOnly": true}}
]'
```

### 5. Restart SPIRE Server

```bash
oc delete pod spire-server-0 -n zero-trust-workload-identity-manager
```

---

## Verification

### Check UpstreamAuthority Plugin Loaded

```bash
oc logs spire-server-0 -n zero-trust-workload-identity-manager -c spire-server | grep -i upstream
```

**Expected output:**
```
level=info msg="Configured plugin" external=false plugin_name=disk plugin_type=UpstreamAuthority
level=info msg="Plugin loaded" external=false plugin_name=disk plugin_type=UpstreamAuthority
```

### Check CA Files Mounted

```bash
oc exec spire-server-0 -n zero-trust-workload-identity-manager -c spire-server -- ls -la /run/spire/upstream-ca/
```

**Expected output:**
```
ca.crt -> ..data/ca.crt
ca.key -> ..data/ca.key
```

### Check ConfigMap is Immutable

```bash
oc get configmap spire-server -n zero-trust-workload-identity-manager -o jsonpath='{.immutable}'
```

**Expected output:** `true`

---

## Demo Results

Both demos working after implementing the upstream authority:

### X.509 Demo (PostgreSQL with SPIFFE certificates)

```bash
curl -sk https://db-client-app-spiffe-edb-demo.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/api/db/test
```

```json
{
  "authentication": "X.509 Certificate (SPIFFE SVID)",
  "current_user": "app_readonly",
  "database": "appdb",
  "status": "connected"
}
```

### JWT-SVID Demo (Entra ID integration)

```bash
curl -sk https://jwt-client-app-oidc-postgres-demo.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/api/full-demo
```

```json
{
  "overall_status": "success",
  "summary": {
    "spiffe_id": "spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/ns/oidc-postgres-demo/sa/jwt-client-app-sa",
    "token_validated_by": "PostgreSQL (pgjwt)",
    "authorization_method": "Row-Level Security",
    "products_retrieved": 5
  }
}
```

---

## Files

| File | Description |
|------|-------------|
| `certs/root-ca.crt` | Root CA certificate (10-year validity) |
| `certs/root-ca.key` | Root CA private key (**KEEP SECURE**) |
