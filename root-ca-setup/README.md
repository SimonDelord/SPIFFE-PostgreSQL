# SPIRE Intermediate CA Setup with Disk-based Upstream Authority

This document describes how to configure SPIRE to use an **intermediate CA** signed by a long-lived **root CA**, solving the certificate rotation issues where applications need to be reconfigured every time SPIRE's CA rotates.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INTERMEDIATE CA ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │                     ROOT CA (Long-lived)                         │       │
│   │                     Validity: 10 years                           │       │
│   │                     CN: SPIFFE Root CA                           │       │
│   │                     Stored: Kubernetes Secret                    │       │
│   └──────────────────────────────┬──────────────────────────────────┘       │
│                                  │                                           │
│                                  │ Signs (via UpstreamAuthority plugin)      │
│                                  ▼                                           │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │                SPIRE Intermediate CA                             │       │
│   │                Validity: 1 year (configurable)                   │       │
│   │                CN: SPIRE Server CA                               │       │
│   │                Managed by: SPIRE Server                          │       │
│   └──────────────────────────────┬──────────────────────────────────┘       │
│                                  │                                           │
│                                  │ Signs                                     │
│                                  ▼                                           │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │              Workload X.509-SVIDs                                │       │
│   │              Validity: 1 hour (default)                          │       │
│   │              Issued to: Pods/Workloads                           │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                              │
│   BENEFIT: Applications only need to trust the ROOT CA                       │
│            SPIRE can rotate its intermediate CA without breaking trust       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- OpenShift cluster with Zero Trust Workload Identity Manager operator installed
- `oc` CLI with cluster-admin access
- `openssl` for certificate generation

## Setup Steps

### Step 1: Create the Root CA

```bash
# Create directory for certificates
mkdir -p certs && cd certs

# Generate Root CA private key (4096-bit RSA)
openssl genrsa -out root-ca.key 4096

# Create Root CA certificate (10 years validity)
openssl req -x509 -new -nodes -key root-ca.key -sha256 -days 3650 \
  -out root-ca.crt \
  -subj "/C=US/ST=State/L=City/O=My Organization/OU=SPIFFE Root CA/CN=SPIFFE Root CA"

# Verify the certificate
openssl x509 -in root-ca.crt -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After"
```

### Step 2: Create Kubernetes Secret

```bash
# Create secret with root CA cert and key
oc create secret generic spire-upstream-ca \
  --from-file=ca.crt=root-ca.crt \
  --from-file=ca.key=root-ca.key \
  -n zero-trust-workload-identity-manager
```

### Step 3: Patch SPIRE Server ConfigMap

The key is to:
1. Add the `UpstreamAuthority` plugin to the SPIRE server config
2. Set the ConfigMap as **immutable** to prevent the operator from overwriting it

```bash
# Get current config
CONFIG=$(oc get configmap spire-server -n zero-trust-workload-identity-manager -o jsonpath='{.data.server\.conf}')

# Add UpstreamAuthority plugin
NEW_CONFIG=$(echo "$CONFIG" | jq '.plugins.UpstreamAuthority = [{"disk": {"plugin_data": {"cert_file_path": "/run/spire/upstream-ca/ca.crt", "key_file_path": "/run/spire/upstream-ca/ca.key"}}}]')

# Patch ConfigMap with UpstreamAuthority AND set immutable: true
oc patch configmap spire-server -n zero-trust-workload-identity-manager \
  --type='merge' \
  -p="{\"immutable\": true, \"data\": {\"server.conf\": $(echo "$NEW_CONFIG" | jq -c . | jq -Rs .)}}"
```

### Step 4: Patch SPIRE Server StatefulSet

Mount the root CA secret into the SPIRE server pod:

```bash
oc patch statefulset spire-server -n zero-trust-workload-identity-manager --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/volumes/-", "value": {"name": "upstream-ca", "secret": {"secretName": "spire-upstream-ca"}}},
  {"op": "add", "path": "/spec/template/spec/containers/0/volumeMounts/-", "value": {"name": "upstream-ca", "mountPath": "/run/spire/upstream-ca", "readOnly": true}}
]'
```

### Step 5: Restart SPIRE Server

```bash
# Delete the pod to trigger restart with new config
oc delete pod spire-server-0 -n zero-trust-workload-identity-manager

# Wait for pod to come back
oc get pods -n zero-trust-workload-identity-manager -w
```

### Step 6: Verify

Check the SPIRE server logs to confirm the UpstreamAuthority plugin is loaded:

```bash
oc logs spire-server-0 -n zero-trust-workload-identity-manager -c spire-server | grep -i upstream
```

You should see:
```
level=info msg="Plugin loaded" external=false plugin_name=disk plugin_type=UpstreamAuthority
```

## Files in this Directory

| File | Description |
|------|-------------|
| `certs/root-ca.crt` | Root CA certificate (10-year validity) |
| `certs/root-ca.key` | Root CA private key (KEEP SECURE!) |
| `spire-upstream-ca-secret.yaml` | Kubernetes Secret manifest |
| `spire-server-configmap-patch.yaml` | ConfigMap patch (for reference) |

## Important Notes

### ConfigMap Immutability

Setting `immutable: true` on the ConfigMap prevents the Zero Trust Workload Identity Manager operator from reverting our changes. However, this also means:
- You cannot modify the ConfigMap without deleting and recreating it
- If you need to change the config, you'll need to delete the ConfigMap first

### Root CA Security

The root CA private key (`root-ca.key`) is highly sensitive:
- In production, store it in an HSM or secure vault
- Consider using a shorter-lived intermediate if the root key is on disk
- Limit access to the Kubernetes Secret

### Certificate Chain

When SPIRE mints a new intermediate CA:
1. It requests signing from the UpstreamAuthority plugin
2. The plugin signs with the root CA
3. Workload SVIDs chain: `Workload → SPIRE Intermediate → Root CA`

Applications trusting the root CA will automatically trust all workload certificates.

## Troubleshooting

### ConfigMap reverts to original

If the operator keeps overwriting changes:
1. Ensure `immutable: true` is set on the ConfigMap
2. Check operator logs for errors

### SPIRE server fails to start

Check logs for certificate loading errors:
```bash
oc logs spire-server-0 -n zero-trust-workload-identity-manager -c spire-server | grep -i error
```

Common issues:
- Incorrect file paths in UpstreamAuthority config
- Certificate/key mismatch
- Permissions issues on mounted files

### Verify certificate chain

To verify a workload certificate chains to the root CA:
```bash
# Get root CA
ROOT_CA=$(oc get secret spire-upstream-ca -n zero-trust-workload-identity-manager -o jsonpath='{.data.ca\.crt}' | base64 -d)

# Verify workload cert (example)
echo "$WORKLOAD_CERT" | openssl verify -CAfile <(echo "$ROOT_CA")
```
