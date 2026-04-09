# Certificate Rotation Use Case: SPIRE as Intermediate CA

This document addresses the challenge of **SPIRE CA rotation** when non-SPIFFE applications (like PostgreSQL) need to trust SPIFFE certificates.

---

## Table of Contents

1. [The Problem](#the-problem)
2. [The Solution: SPIRE as Intermediate CA](#the-solution-spire-as-intermediate-ca)
3. [Architecture Comparison](#architecture-comparison)
4. [Upstream Authority Options](#upstream-authority-options)
5. [Implementation Guide](#implementation-guide)
6. [Certificate Chain Validation](#certificate-chain-validation)
7. [Operational Considerations](#operational-considerations)

---

## The Problem

### Current Setup (SPIRE as Root CA)

In our basic demo, SPIRE acts as the **root CA**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Current Setup - SPIRE as Root CA                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SPIRE CA (Root)                                                           │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Validity: 24 hours (configurable, but typically short)             │   │
│   │  ⚠️ Rotates frequently for security                                 │   │
│   └─────────────────────┬───────────────────────────────────────────────┘   │
│                         │                                                    │
│           ┌─────────────┴─────────────┐                                     │
│           │                           │                                     │
│           ▼                           ▼                                     │
│   ┌───────────────┐           ┌───────────────────────────────────────┐    │
│   │  X.509-SVIDs  │           │  PostgreSQL ssl_ca_file               │    │
│   │  (1h TTL)     │           │                                       │    │
│   │  ✓ Auto-      │           │  ❌ Must manually update when SPIRE   │    │
│   │    rotated    │           │     CA rotates                        │    │
│   │    by SPIRE   │           │  ❌ Requires pod restart or config    │    │
│   │               │           │     reload                            │    │
│   └───────────────┘           │  ❌ Operational burden                 │    │
│                               │  ❌ Risk of outage if not updated     │    │
│                               └───────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### The Challenge

| Component | Rotation Frequency | Impact |
|-----------|-------------------|--------|
| X.509-SVIDs | Every ~1 hour | ✅ Handled automatically by SPIRE |
| SPIRE CA | Every ~24 hours | ❌ Non-SPIFFE apps must be updated |

**Non-SPIFFE applications** (like PostgreSQL, external APIs, legacy systems) that trust the SPIRE CA:
- Must be updated every time the CA rotates
- May require pod restarts or service reloads
- Create operational overhead
- Risk connection failures if CA is not updated in time

---

## The Solution: SPIRE as Intermediate CA

Configure SPIRE to operate as an **intermediate CA** under a **long-lived external root CA**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│               Solution - SPIRE as Intermediate CA                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   External Root CA (Long-lived)                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Validity: 5-10 years                                                │   │
│   │  ✓ Stable, rarely rotates                                           │   │
│   │  ✓ Stored securely (HSM, Vault, AWS PCA, offline)                   │   │
│   │  ✓ This is what non-SPIFFE apps trust                               │   │
│   └─────────────────────┬───────────────────────────────────────────────┘   │
│                         │ Signs                                              │
│                         ▼                                                    │
│   SPIRE Intermediate CA (Short-lived)                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Validity: 24 hours - 7 days                                        │   │
│   │  ✓ Can rotate frequently (security benefit)                         │   │
│   │  ✓ Compromise has limited blast radius                              │   │
│   │  ✓ Rotation is transparent to downstream apps                       │   │
│   └─────────────────────┬───────────────────────────────────────────────┘   │
│                         │ Signs                                              │
│           ┌─────────────┴─────────────┐                                     │
│           │                           │                                     │
│           ▼                           ▼                                     │
│   ┌───────────────┐           ┌───────────────────────────────────────┐    │
│   │  X.509-SVIDs  │           │  PostgreSQL ssl_ca_file               │    │
│   │  (1h TTL)     │           │                                       │    │
│   │  ✓ Auto-      │           │  ✓ Trusts ROOT CA (long-lived)       │    │
│   │    rotated    │           │  ✓ No updates when intermediate      │    │
│   │               │           │    rotates                            │    │
│   │  Chain:       │           │  ✓ Set once, stable for years         │    │
│   │  SVID →       │           │                                       │    │
│   │  Intermediate │           └───────────────────────────────────────┘    │
│   │  → Root       │                                                         │
│   └───────────────┘                                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **Stability** | Non-SPIFFE apps trust a root CA that rarely changes |
| **Security** | SPIRE intermediate can still rotate frequently |
| **Blast Radius** | Compromised intermediate only affects short window |
| **Operations** | No recurring CA update tasks for downstream systems |
| **Compliance** | Matches enterprise PKI best practices |

---

## Architecture Comparison

### Before (SPIRE as Root)

```
PostgreSQL trusts → SPIRE CA (24h) → Signs → X.509-SVIDs
                    ↑
                    Must update every 24h!
```

### After (SPIRE as Intermediate)

```
PostgreSQL trusts → Root CA (10 years) → Signs → SPIRE Intermediate (24h) → Signs → X.509-SVIDs
                    ↑                             ↑
                    Set once!                     Can rotate freely
```

---

## Upstream Authority Options

SPIRE supports several **upstream authority** plugins for obtaining its intermediate CA certificate:

### Option 1: Disk-based (Simple)

Store the root CA certificate and key on disk. SPIRE loads them at startup.

```yaml
# SpireServer configuration
spec:
  upstreamAuthority:
    disk:
      certFilePath: "/run/spire/upstream-ca/intermediate.crt"
      keyFilePath: "/run/spire/upstream-ca/intermediate.key"
      bundleFilePath: "/run/spire/upstream-ca/root-bundle.crt"
```

| Pros | Cons |
|------|------|
| Simple to set up | Key stored on disk (less secure) |
| No external dependencies | Manual key rotation |
| Good for dev/test | Not recommended for production |

### Option 2: HashiCorp Vault (Enterprise)

Use Vault's PKI secrets engine to issue the intermediate CA.

```yaml
spec:
  upstreamAuthority:
    vault:
      vaultAddr: "https://vault.example.com:8200"
      pkiMountPoint: "pki_int"
      caCertPath: "/run/spire/vault-ca/ca.crt"
      # Authentication via Kubernetes auth method
      k8sAuth:
        k8sAuthMountPoint: "kubernetes"
        k8sAuthRoleName: "spire-server"
        tokenPath: "/var/run/secrets/kubernetes.io/serviceaccount/token"
```

| Pros | Cons |
|------|------|
| Centralized PKI management | Requires Vault infrastructure |
| Automatic rotation | More complex setup |
| Audit logging | Additional operational overhead |
| HSM integration possible | |

### Option 3: AWS Private CA (Cloud-native)

Use AWS Private Certificate Authority for the root/intermediate.

```yaml
spec:
  upstreamAuthority:
    awsPCA:
      region: "us-east-1"
      certificateAuthorityArn: "arn:aws:acm-pca:us-east-1:123456789:certificate-authority/abc-123"
      signingAlgorithm: "SHA256WITHRSA"
      # Optional: assume role for cross-account
      assumeRoleArn: "arn:aws:iam::123456789:role/spire-pca-role"
```

| Pros | Cons |
|------|------|
| Fully managed | AWS-specific |
| HSM-backed | Cost per certificate |
| Compliance ready (SOC2, etc.) | Requires AWS credentials |
| No key management needed | |

### Option 4: cert-manager (Kubernetes-native)

Use Kubernetes cert-manager to issue the intermediate CA.

```yaml
spec:
  upstreamAuthority:
    certManager:
      namespace: "cert-manager"
      issuerName: "spire-issuer"
      issuerKind: "ClusterIssuer"  # or "Issuer"
      issuerGroup: "cert-manager.io"
```

| Pros | Cons |
|------|------|
| Kubernetes-native | Requires cert-manager |
| Integrates with existing PKI | Additional CRDs |
| Multiple backend support | |

### Comparison Matrix

| Feature | Disk | Vault | AWS PCA | cert-manager |
|---------|------|-------|---------|--------------|
| **Complexity** | Low | High | Medium | Medium |
| **Security** | Low | High | High | Medium |
| **Cost** | Free | License | Per-cert | Free |
| **Auto-rotation** | No | Yes | Yes | Yes |
| **HSM support** | No | Yes | Yes | Depends |
| **Best for** | Dev/Test | Enterprise | AWS workloads | K8s-native |

---

## Implementation Guide

### Step 1: Generate Root CA (One-time)

For production, use an HSM or managed service. For testing, you can generate locally:

```bash
# Create directory for CA files
mkdir -p /tmp/spire-pki

# Generate Root CA private key
openssl genrsa -out /tmp/spire-pki/root-ca.key 4096

# Generate Root CA certificate (10 year validity)
openssl req -x509 -new -nodes \
  -key /tmp/spire-pki/root-ca.key \
  -sha256 -days 3650 \
  -out /tmp/spire-pki/root-ca.crt \
  -subj "/C=US/O=My Organization/CN=SPIFFE Root CA"

# Verify
openssl x509 -in /tmp/spire-pki/root-ca.crt -text -noout | head -20
```

### Step 2: Generate Intermediate CA for SPIRE

```bash
# Generate Intermediate CA private key
openssl genrsa -out /tmp/spire-pki/intermediate-ca.key 4096

# Generate CSR for Intermediate CA
openssl req -new \
  -key /tmp/spire-pki/intermediate-ca.key \
  -out /tmp/spire-pki/intermediate-ca.csr \
  -subj "/C=US/O=My Organization/CN=SPIRE Intermediate CA"

# Create extensions file for CA certificate
cat > /tmp/spire-pki/intermediate-ext.cnf << EOF
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always, issuer
EOF

# Sign Intermediate CA with Root CA (1 year validity)
openssl x509 -req \
  -in /tmp/spire-pki/intermediate-ca.csr \
  -CA /tmp/spire-pki/root-ca.crt \
  -CAkey /tmp/spire-pki/root-ca.key \
  -CAcreateserial \
  -out /tmp/spire-pki/intermediate-ca.crt \
  -days 365 \
  -sha256 \
  -extfile /tmp/spire-pki/intermediate-ext.cnf

# Create bundle (Root CA for distribution)
cp /tmp/spire-pki/root-ca.crt /tmp/spire-pki/root-bundle.crt
```

### Step 3: Create Kubernetes Secrets

```bash
# Create namespace if needed
oc create namespace zero-trust-workload-identity-manager --dry-run=client -o yaml | oc apply -f -

# Create secret with intermediate CA and root bundle
oc create secret generic spire-upstream-ca \
  --from-file=intermediate.crt=/tmp/spire-pki/intermediate-ca.crt \
  --from-file=intermediate.key=/tmp/spire-pki/intermediate-ca.key \
  --from-file=root-bundle.crt=/tmp/spire-pki/root-bundle.crt \
  -n zero-trust-workload-identity-manager
```

### Step 4: Configure SPIRE Server with Upstream Authority

Update your SpireServer configuration:

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpireServer
metadata:
  name: cluster
spec:
  logLevel: "info"
  jwtIssuer: "https://oidc-discovery.apps.your-cluster.com"
  
  # Upstream Authority configuration
  upstreamAuthority:
    disk:
      certFilePath: "/run/spire/upstream-ca/intermediate.crt"
      keyFilePath: "/run/spire/upstream-ca/intermediate.key"
      bundleFilePath: "/run/spire/upstream-ca/root-bundle.crt"
  
  # Mount the secret
  extraVolumes:
    - name: upstream-ca
      secret:
        secretName: spire-upstream-ca
  extraVolumeMounts:
    - name: upstream-ca
      mountPath: /run/spire/upstream-ca
      readOnly: true
  
  # Other settings...
  caValidity: "24h"
  defaultX509Validity: "1h"
```

### Step 5: Update PostgreSQL to Trust Root CA

Now PostgreSQL trusts the **root CA** instead of the SPIRE CA:

```bash
# Create secret with ROOT CA (not SPIRE intermediate!)
oc create secret generic spire-root-ca-bundle \
  --from-file=ca.crt=/tmp/spire-pki/root-ca.crt \
  -n edb

# Update PostgreSQL to use this secret for ssl_ca_file
```

---

## Certificate Chain Validation

### How It Works

When a SPIFFE workload connects to PostgreSQL:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Certificate Chain Validation                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Client presents certificate chain:                                        │
│                                                                              │
│   1. Leaf Certificate (X.509-SVID)                                          │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  Subject: spiffe://trust-domain/ns/app/sa/client                │    │
│      │  Issuer: CN=SPIRE Intermediate CA                               │    │
│      │  Validity: 1 hour                                               │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                              │ signed by                                     │
│                              ▼                                               │
│   2. Intermediate Certificate                                               │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  Subject: CN=SPIRE Intermediate CA                              │    │
│      │  Issuer: CN=SPIFFE Root CA                                      │    │
│      │  Validity: 1 year                                               │    │
│      │  ✓ Included in SVID cert chain by SPIRE                        │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                              │ signed by                                     │
│                              ▼                                               │
│   3. Root Certificate (in PostgreSQL ssl_ca_file)                           │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  Subject: CN=SPIFFE Root CA                                     │    │
│      │  Issuer: Self-signed                                            │    │
│      │  Validity: 10 years                                             │    │
│      │  ✓ This is what PostgreSQL trusts                              │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│   PostgreSQL validation:                                                     │
│   ✓ SVID signed by Intermediate? YES                                       │
│   ✓ Intermediate signed by Root? YES                                       │
│   ✓ Root in ssl_ca_file? YES                                               │
│   → Connection ALLOWED                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### SPIRE Automatically Includes Intermediate

When SPIRE is configured with an upstream authority, it automatically:
1. Signs SVIDs with its intermediate CA
2. Includes the intermediate certificate in the cert chain
3. Includes the root CA in the trust bundle

The workload receives a complete chain that can be validated up to the root.

---

## Operational Considerations

### Rotation Schedule

| Certificate | Validity | Rotation Trigger | Impact |
|-------------|----------|------------------|--------|
| Root CA | 5-10 years | Manual (planned) | Requires updating all trust stores |
| Intermediate CA | 1 year | Automatic (SPIRE) | Transparent to downstream |
| X.509-SVIDs | 1 hour | Automatic (SPIRE) | Transparent to workloads |

### Monitoring

Monitor these events:
- Intermediate CA approaching expiry
- Root CA expiry (set alerts well in advance)
- SVID issuance failures

```bash
# Check SPIRE server logs for CA rotation
oc logs -n zero-trust-workload-identity-manager -l app=spire-server | grep -i "rotating"

# Check current CA validity
oc exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  /opt/spire/bin/spire-server bundle show | openssl x509 -text -noout | grep -A2 "Validity"
```

### Disaster Recovery

Keep backups of:
- Root CA certificate and key (secure offline storage)
- Intermediate CA certificate and key
- SPIRE configuration

### Security Best Practices

1. **Root CA Key Protection**
   - Store in HSM or secure vault
   - Never on disk in production
   - Limit access to security team

2. **Intermediate CA Rotation**
   - Rotate before expiry (e.g., at 80% of validity)
   - SPIRE handles this automatically with upstream authority

3. **Audit Logging**
   - Enable SPIRE audit logs
   - Track all CA operations in Vault/AWS PCA

---

## Next Steps

1. **Choose an upstream authority** based on your infrastructure
2. **Generate or provision** the root and intermediate CAs
3. **Configure SPIRE** with the upstream authority
4. **Update downstream systems** to trust the root CA
5. **Test certificate chain validation**
6. **Set up monitoring** for CA expiry

---

## References

- [SPIRE Upstream Authority Documentation](https://spiffe.io/docs/latest/deploying/configuring/#upstream-authority)
- [SPIRE Server Configuration Reference](https://spiffe.io/docs/latest/deploying/spire_server/)
- [HashiCorp Vault PKI Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/pki)
- [AWS Private CA Documentation](https://docs.aws.amazon.com/privateca/latest/userguide/PcaWelcome.html)
