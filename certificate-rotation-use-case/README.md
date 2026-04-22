# Certificate Rotation Use Case: SPIRE with Upstream Authority

This document describes our **implemented solution** for SPIRE CA rotation when non-SPIFFE applications need to trust SPIFFE certificates.

**Status: ✅ IMPLEMENTED AND TESTED**

---

## Table of Contents

1. [Overview](#overview)
2. [Step 1: Root CA (10-year validity)](#step-1-root-ca-10-year-validity)
3. [Step 2: SPIRE UpstreamAuthority Configuration](#step-2-spire-upstreamauthority-configuration)
4. [Step 3: SPIRE Intermediate CA (Signed by Root CA)](#step-3-spire-intermediate-ca-signed-by-root-ca)
5. [Step 4: Workload SVID (Signed by Intermediate CA)](#step-4-workload-svid-signed-by-intermediate-ca)
6. [Step 5: PostgreSQL Trusts Root CA](#step-5-postgresql-trusts-root-ca)
7. [Implementation Commands](#implementation-commands)

---

## Overview

The certificate chain we implemented:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CERTIFICATE CHAIN                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. ROOT CA (10-year validity)                                             │
│      Subject: CN=SPIFFE Root CA                                             │
│      Validity: Apr 21, 2026 → Apr 18, 2036                                  │
│      PostgreSQL trusts THIS                                                  │
│                                  │                                           │
│                                  │ Signs                                     │
│                                  ▼                                           │
│   2. SPIRE INTERMEDIATE CA (1-year validity)                                │
│      Subject: CN=SPIRE Server CA                                            │
│      Signed by: Root CA (via UpstreamAuthority plugin)                      │
│                                  │                                           │
│                                  │ Signs                                     │
│                                  ▼                                           │
│   3. WORKLOAD SVID (1-hour validity)                                        │
│      Subject: CN=app_readonly                                               │
│      SPIFFE ID: spiffe://trust-domain/ns/spiffe-edb-demo/sa/db-client-app   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Root CA (10-year validity)

The Root CA is the trust anchor. It has a 10-year validity and is stored in a Kubernetes Secret.

### View the Root CA certificate

```bash
$ openssl x509 -in root-ca.crt -text -noout | grep -E 'Subject:|Issuer:|Not Before|Not After'
```

**Output:**
```
        Issuer: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
            Not Before: Apr 21 23:49:25 2026 GMT
            Not After : Apr 18 23:49:25 2036 GMT
        Subject: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
```

### Verify Root CA is stored in Kubernetes Secret

```bash
$ oc get secret spire-upstream-ca -n zero-trust-workload-identity-manager
```

**Output:**
```
NAME                TYPE     DATA   AGE
spire-upstream-ca   Opaque   2      72m
```

---

## Step 2: SPIRE UpstreamAuthority Configuration

SPIRE is configured with the `UpstreamAuthority` plugin pointing to the Root CA. The ConfigMap is set to `immutable: true` to prevent the operator from overwriting our configuration.

### Verify UpstreamAuthority plugin in SPIRE ConfigMap

```bash
$ oc get configmap spire-server -n zero-trust-workload-identity-manager -o jsonpath='{.data.server\.conf}' | jq '.plugins.UpstreamAuthority'
```

**Output:**
```json
[
  {
    "disk": {
      "plugin_data": {
        "cert_file_path": "/run/spire/upstream-ca/ca.crt",
        "key_file_path": "/run/spire/upstream-ca/ca.key"
      }
    }
  }
]
```

### Verify ConfigMap is immutable

```bash
$ oc get configmap spire-server -n zero-trust-workload-identity-manager -o jsonpath='{.immutable}'
```

**Output:**
```
true
```

### Verify Root CA is mounted in SPIRE server pod

```bash
$ oc exec spire-server-0 -n zero-trust-workload-identity-manager -c spire-server -- ls -la /run/spire/upstream-ca/
```

**Output:**
```
total 0
drwxrwsrwt. 3 root 1000820000 120 Apr 22 00:41 .
drwxr-xr-t. 5 root root        51 Apr 22 00:41 ..
drwxr-sr-x. 2 root 1000820000  80 Apr 22 00:41 ..2026_04_22_00_41_51.656108531
lrwxrwxrwx. 1 root 1000820000  31 Apr 22 00:41 ..data -> ..2026_04_22_00_41_51.656108531
lrwxrwxrwx. 1 root 1000820000  13 Apr 22 00:41 ca.crt -> ..data/ca.crt
lrwxrwxrwx. 1 root 1000820000  13 Apr 22 00:41 ca.key -> ..data/ca.key
```

---

## Step 3: SPIRE Intermediate CA (Signed by Root CA)

SPIRE creates an intermediate CA that is signed by the Root CA. The key evidence is that `upstream_authority_id` is NOT empty in the logs.

### Check SPIRE logs for Intermediate CA

```bash
$ oc logs spire-server-0 -n zero-trust-workload-identity-manager -c spire-server | grep 'X509 CA activated'
```

**Output:**
```
time="2026-04-22T00:41:58.628793157Z" level=info msg="X509 CA activated" expiration="2027-04-22 00:41:58 +0000 UTC" issued_at="2026-04-22 00:41:58.575806132 +0000 UTC" local_authority_id=7c97bb5638c4fe04b7a230cd8c996c44ab6e87a4 slot=A subsystem_name=ca_manager upstream_authority_id=e9f017c91b06e3890b50d1d56408ab3a989e4364
```

**Key evidence:** `upstream_authority_id=e9f017c91b06e3890b50d1d56408ab3a989e4364` is NOT empty, proving the CA was signed by the Root CA (not self-signed).

### Check SPIRE bundle

```bash
$ oc get configmap spire-bundle -n zero-trust-workload-identity-manager -o jsonpath='{.data.bundle\.crt}' | openssl x509 -text -noout | grep -E 'Subject:|Issuer:'
```

**Output:**
```
        Issuer: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
        Subject: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
```

---

## Step 4: Workload SVID (Signed by Intermediate CA)

Workloads receive X.509-SVIDs signed by the SPIRE Intermediate CA. The certificate includes the SPIFFE ID and the CN (app_readonly) used for PostgreSQL authentication.

### Get certificate details from the demo app

```bash
$ curl -sk https://db-client-app-spiffe-edb-demo.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/api/certificate | jq .
```

**Output:**
```json
{
  "common_name": "app_readonly",
  "issuer": {
    "commonName": "SPIRE Server CA",
    "countryName": "US",
    "organizationName": "My Organization",
    "serialNumber": "131741481347152461017029311118100114626"
  },
  "not_valid_after": "2026-04-22T01:45:20",
  "not_valid_before": "2026-04-22T00:45:10",
  "san_uris": [
    "spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app"
  ],
  "serial_number": "298011426006870899089435323542075076824",
  "spiffe_id": "spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app",
  "subject": {
    "commonName": "app_readonly",
    "countryName": "US",
    "organizationName": "SPIRE"
  }
}
```

### View the FULL certificate chain

The app exposes an endpoint that shows the complete certificate chain:

```bash
$ curl -sk https://db-client-app-spiffe-edb-demo.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/api/certificate-chain | jq .
```

**Output:**
```json
{
  "chain_length": 2,
  "chain_summary": "app_readonly → SPIRE Server CA",
  "chain_description": [
    "SVID (app_readonly) → signed by → SPIRE Server CA",
    "SPIRE Server CA → signed by → SPIFFE Root CA"
  ],
  "certificates": [
    {
      "position": 1,
      "type": "Workload SVID",
      "subject": { "commonName": "app_readonly", "organization": "SPIRE", "country": "US" },
      "issuer": { "commonName": "SPIRE Server CA", "organization": "My Organization", "country": "US" },
      "san_uris": ["spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app"]
    },
    {
      "position": 2,
      "type": "CA Certificate 1",
      "subject": { "commonName": "SPIRE Server CA", "organization": "My Organization", "country": "US" },
      "issuer": { "commonName": "SPIFFE Root CA", "organization": "My Organization", "country": "US" },
      "san_uris": ["spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com"]
    }
  ],
  "trust_chain": "SVID → SPIRE Intermediate CA → Root CA"
}
```

### Why the browser shows the OpenShift certificate (not the SPIFFE certificate)

If you inspect the certificate in your browser, you'll see the OpenShift router certificate (*.apps.rosa...), NOT the SPIFFE certificate. This is expected:

```
┌──────────┐      HTTPS       ┌─────────────────┐      HTTP        ┌──────────────┐      mTLS       ┌────────────┐
│  Browser │ ───────────────► │ OpenShift Router│ ───────────────► │  Client App  │ ──────────────► │ PostgreSQL │
└──────────┘                  └─────────────────┘                  └──────────────┘                 └────────────┘
       ↑                             ↑                                    ↑
       │                             │                                    │
 Browser sees                  TLS terminated                       SPIFFE X.509-SVID
 OpenShift cert                here                                 used here (internal)
```

The SPIFFE certificate is used for **internal mTLS** between the client app and PostgreSQL, NOT for browser traffic. Use the `/api/certificate-chain` endpoint above to see the actual SPIFFE certificate chain.

**Certificate Chain:**
- **Subject:** `app_readonly` (the workload identity)
- **Issuer:** `SPIRE Server CA` (the intermediate CA)
- The intermediate CA is signed by the Root CA (from Step 3)

---

## Step 5: PostgreSQL Trusts Root CA

PostgreSQL is configured to trust ONLY the Root CA. It validates the full certificate chain: SVID → Intermediate → Root CA.

### Check what CA PostgreSQL trusts

```bash
$ oc get secret spire-ca-bundle -n edb -o jsonpath='{.data.ca\.crt}' | base64 -d | openssl x509 -text -noout | grep -E 'Subject:|Issuer:|Not Before|Not After'
```

**Output:**
```
        Issuer: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
            Not Before: Apr 21 23:49:25 2026 GMT
            Not After : Apr 18 23:49:25 2036 GMT
        Subject: C=US, ST=State, L=City, O=My Organization, OU=SPIFFE Root CA, CN=SPIFFE Root CA
```

### Test the full chain - Client connects to PostgreSQL

```bash
$ curl -sk https://db-client-app-spiffe-edb-demo.apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/api/db/test | jq .
```

**Output:**
```json
{
  "authentication": "X.509 Certificate (SPIFFE SVID)",
  "current_user": "app_readonly",
  "database": "appdb",
  "postgres_version": "PostgreSQL 16.2 (Debian 16.2-1.pgdg120+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14) 12.2.0, 64-bit",
  "session_user": "app_readonly",
  "ssl_mode": "require",
  "status": "connected"
}
```

**Result:** PostgreSQL successfully validates the certificate chain and authenticates the workload as `app_readonly`.

---

## Implementation Commands

### Create Root CA (one-time)

```bash
# Generate 4096-bit RSA key
openssl genrsa -out root-ca.key 4096

# Create self-signed root CA certificate (10 years)
openssl req -x509 -new -nodes -key root-ca.key -sha256 -days 3650 \
  -out root-ca.crt \
  -subj "/C=US/ST=State/L=City/O=My Organization/OU=SPIFFE Root CA/CN=SPIFFE Root CA"
```

### Create Kubernetes Secret

```bash
oc create secret generic spire-upstream-ca \
  --from-file=ca.crt=root-ca.crt \
  --from-file=ca.key=root-ca.key \
  -n zero-trust-workload-identity-manager
```

### Patch SPIRE ConfigMap (with immutable flag)

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

### Patch StatefulSet to mount Root CA

```bash
oc patch statefulset spire-server -n zero-trust-workload-identity-manager --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/volumes/-", "value": {"name": "upstream-ca", "secret": {"secretName": "spire-upstream-ca"}}},
  {"op": "add", "path": "/spec/template/spec/containers/0/volumeMounts/-", "value": {"name": "upstream-ca", "mountPath": "/run/spire/upstream-ca", "readOnly": true}}
]'
```

### Update PostgreSQL to trust Root CA

```bash
oc create secret generic spire-ca-bundle \
  --from-file=ca.crt=root-ca.crt \
  -n edb \
  --dry-run=client -o yaml | oc apply -f -

# Restart PostgreSQL
oc delete pod edb-spiffe-postgres-0 -n edb
```

---

## Files

| File | Description |
|------|-------------|
| `certs/root-ca.crt` | Root CA certificate (10-year validity) |
| `certs/root-ca.key` | Root CA private key (**KEEP SECURE**) |
