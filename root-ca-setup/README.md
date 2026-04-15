# Root CA Setup for SPIRE

This guide explains how to configure SPIRE to use a long-lived Root CA, eliminating the need to update trust bundles when SPIRE's intermediate CA rotates.

## Table of Contents

- [The Problem](#the-problem)
- [The Solution: SPIRE as Intermediate CA](#the-solution-spire-as-intermediate-ca)
- [Architecture](#architecture)
- [Setup Steps](#setup-steps)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## The Problem

By default, SPIRE operates as its own Certificate Authority with a short-lived CA (24 hours in our setup). When this CA rotates:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     THE PROBLEM: CA ROTATION BREAKS TRUST                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Day 1: Everything works                                                    │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ SPIRE CA     │────►│ Client App   │────►│ PostgreSQL   │                │
│  │ (Root CA A)  │     │ (Cert from A)│     │ (Trusts A)   │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                                              ✓ Connection OK                │
│                                                                              │
│  Day 2: SPIRE CA rotates                                                    │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ SPIRE CA     │────►│ Client App   │────►│ PostgreSQL   │                │
│  │ (Root CA B)  │     │ (Cert from B)│     │ (Trusts A)   │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                                              ✗ SSL ERROR!                   │
│                                              "unknown ca"                   │
│                                                                              │
│  Manual fix required: Update PostgreSQL's CA bundle                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Impact:**
- PostgreSQL stops trusting client certificates after SPIRE CA rotation
- Manual intervention required every 24 hours
- Production systems break unexpectedly

---

## The Solution: SPIRE as Intermediate CA

Configure SPIRE to operate as an **intermediate CA** under a long-lived **Root CA**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              THE SOLUTION: SPIRE AS INTERMEDIATE CA                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Root CA (10 years)                                 │  │
│  │                     CN: Demo Root CA                                   │  │
│  │                     ┌─────────────────────────────────┐               │  │
│  │                     │ This is what PostgreSQL trusts  │               │  │
│  │                     └─────────────────────────────────┘               │  │
│  └──────────────────────────────┬────────────────────────────────────────┘  │
│                                 │                                            │
│                                 │ Signs                                      │
│                                 ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                SPIRE Intermediate CA (24 hours)                        │  │
│  │                CN: SPIRE Server CA                                     │  │
│  │                ┌──────────────────────────────────────┐               │  │
│  │                │ This rotates, but chain still valid │               │  │
│  │                └──────────────────────────────────────┘               │  │
│  └──────────────────────────────┬────────────────────────────────────────┘  │
│                                 │                                            │
│                                 │ Signs                                      │
│                                 ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                   Workload Certificates (1 hour)                       │  │
│  │                   spiffe://trust-domain/ns/.../sa/...                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  PostgreSQL trusts Root CA → All intermediate CAs are trusted              │
│  SPIRE CA can rotate → No manual intervention needed                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- PostgreSQL only needs to trust the Root CA (10-year validity)
- SPIRE CA can rotate freely without breaking trust chains
- No manual intervention required for CA rotation
- Follows PKI best practices (short-lived intermediates, long-lived root)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CERTIFICATE HIERARCHY                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Level 0: Root CA                                                           │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Subject: CN=Demo Root CA, O=Demo Organization                        │  │
│  │  Validity: 10 years                                                   │  │
│  │  Key Usage: Certificate Sign, CRL Sign                                │  │
│  │  Basic Constraints: CA:TRUE                                           │  │
│  │                                                                        │  │
│  │  Storage: Kubernetes Secret (root-ca-secret)                          │  │
│  │  Used by: PostgreSQL SSL configuration (trust anchor)                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                 │                                            │
│                                 │                                            │
│  Level 1: SPIRE Intermediate CA                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Subject: CN=SPIRE Server CA, O=My Organization                       │  │
│  │  Validity: 24 hours (auto-rotates)                                    │  │
│  │  Key Usage: Certificate Sign, CRL Sign                                │  │
│  │  Basic Constraints: CA:TRUE, pathlen:0                                │  │
│  │                                                                        │  │
│  │  Managed by: SPIRE Server (upstream_authority: disk)                  │  │
│  │  Signed by: Root CA                                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                 │                                            │
│                                 │                                            │
│  Level 2: Workload Certificates (X.509 SVIDs)                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Subject: O=SPIFFE, CN=<workload-name>                                │  │
│  │  SAN: URI:spiffe://trust-domain/ns/namespace/sa/service-account       │  │
│  │  Validity: 1 hour (auto-rotates)                                      │  │
│  │  Key Usage: Digital Signature, Key Encipherment                       │  │
│  │                                                                        │  │
│  │  Issued by: SPIRE Server                                              │  │
│  │  Used for: mTLS between workloads                                     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Setup Steps

### Step 1: Generate the Root CA

```bash
# Create directory for CA files
mkdir -p /tmp/root-ca
cd /tmp/root-ca

# Generate Root CA private key (4096-bit RSA)
openssl genrsa -out root-ca.key 4096

# Generate Root CA certificate (10 years validity)
openssl req -x509 -new -nodes \
  -key root-ca.key \
  -sha256 \
  -days 3650 \
  -out root-ca.crt \
  -subj "/C=US/O=Demo Organization/CN=Demo Root CA"

# Verify the Root CA
openssl x509 -in root-ca.crt -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After"
```

### Step 2: Create Kubernetes Secret for Root CA

```bash
# Create secret in the SPIRE namespace
oc create secret generic spire-upstream-ca \
  -n zero-trust-workload-identity-manager \
  --from-file=root-ca.crt=root-ca.crt \
  --from-file=root-ca.key=root-ca.key
```

### Step 3: Configure SPIRE to Use Upstream Authority

Update the SPIRE Server configuration to use the disk upstream authority:

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpireServer
metadata:
  name: cluster
  namespace: zero-trust-workload-identity-manager
spec:
  caSubject:
    commonName: SPIRE Server CA
    country: US
    organization: My Organization
  caValidity: 24h
  defaultX509Validity: 1h
  defaultJWTValidity: 5m
  # Add upstream authority configuration
  upstreamAuthority:
    disk:
      certFilePath: /run/spire/upstream-ca/root-ca.crt
      keyFilePath: /run/spire/upstream-ca/root-ca.key
```

### Step 4: Mount the Secret in SPIRE Server

The SPIRE Server StatefulSet needs to mount the upstream CA secret:

```yaml
# Add to SPIRE Server StatefulSet
volumeMounts:
  - name: upstream-ca
    mountPath: /run/spire/upstream-ca
    readOnly: true
volumes:
  - name: upstream-ca
    secret:
      secretName: spire-upstream-ca
```

### Step 5: Update PostgreSQL to Trust Root CA

```bash
# Create/update the CA bundle secret for PostgreSQL
oc create secret generic spire-ca-bundle \
  -n spiffe-edb-demo \
  --from-file=ca.crt=root-ca.crt \
  --dry-run=client -o yaml | oc apply -f -

# Restart PostgreSQL to pick up the new CA
oc rollout restart statefulset/edb-spiffe-postgres -n spiffe-edb-demo
```

---

## Verification

### Check Certificate Chain

```bash
# Get a workload certificate and verify the chain
oc exec -n spiffe-edb-demo deploy/spiffe-edb-client -- \
  cat /spiffe-workload-api/svid.0.pem | \
  openssl verify -CAfile root-ca.crt -untrusted /dev/stdin

# Expected output: stdin: OK
```

### Check SPIRE Server Logs

```bash
oc logs -n zero-trust-workload-identity-manager -l app.kubernetes.io/name=server --tail=50 | \
  grep -i "upstream"
```

### Test mTLS Connection

```bash
# The client should be able to connect without CA bundle updates
oc exec -n spiffe-edb-demo deploy/spiffe-edb-client -- \
  curl -sk https://your-postgres-endpoint
```

---

## Troubleshooting

### SPIRE Server Fails to Start

Check if the secret is mounted correctly:

```bash
oc exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  ls -la /run/spire/upstream-ca/
```

### Certificate Chain Verification Fails

Ensure the Root CA certificate is the same one used to sign SPIRE's intermediate:

```bash
# Get SPIRE's current CA
oc get configmap spire-bundle -n zero-trust-workload-identity-manager \
  -o jsonpath='{.data.bundle\.crt}' | openssl x509 -text -noout

# Check if it's signed by our Root CA
oc get configmap spire-bundle -n zero-trust-workload-identity-manager \
  -o jsonpath='{.data.bundle\.crt}' | \
  openssl verify -CAfile root-ca.crt
```

### PostgreSQL Still Rejects Connections

Verify PostgreSQL is using the correct CA bundle:

```bash
oc exec -n spiffe-edb-demo edb-spiffe-postgres-0 -- \
  cat /etc/ssl/certs/spire-ca.crt | openssl x509 -text -noout
```

---

## Important Notes

1. **Root CA Security**: The Root CA private key should be stored securely. Consider using:
   - HashiCorp Vault
   - AWS Secrets Manager
   - Azure Key Vault
   - Hardware Security Module (HSM)

2. **Root CA Rotation**: Even with a 10-year validity, plan for Root CA rotation before expiry.

3. **Backup**: Always backup the Root CA certificate and key in a secure location.

4. **Monitoring**: Set up alerts for:
   - Root CA expiry (e.g., 6 months before)
   - Certificate chain validation failures
   - SPIRE intermediate CA rotation failures
