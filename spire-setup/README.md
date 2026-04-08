# SPIRE Setup via Zero Trust Workload Identity Manager

This guide explains how to install and configure **SPIRE** (SPIFFE Runtime Environment) on OpenShift using the **Red Hat Zero Trust Workload Identity Manager** operator.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Installation Steps](#installation-steps)
5. [Configuration Files Explained](#configuration-files-explained)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The **Zero Trust Workload Identity Manager** is Red Hat's supported operator for deploying SPIFFE/SPIRE on OpenShift. It manages the lifecycle of:

| Component | Description |
|-----------|-------------|
| **SPIRE Server** | Issues and manages SPIFFE identities (SVIDs) |
| **SPIRE Agent** | Runs on each node (DaemonSet), attests workloads |
| **SPIFFE CSI Driver** | Mounts the Workload API socket into pods |
| **OIDC Discovery Provider** | Exposes SPIFFE identities as OIDC-compatible JWTs |

### What Gets Deployed

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Zero Trust Workload Identity Manager                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Namespace: zero-trust-workload-identity-manager                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SPIRE Server (StatefulSet)                                          │    │
│  │  ─────────────────────────────                                       │    │
│  │  • Issues X.509-SVIDs and JWT-SVIDs                                 │    │
│  │  • Stores identities in SQLite datastore                            │    │
│  │  • Signs certificates with configured CA                            │    │
│  │  • Manages trust bundles                                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                       │                                      │
│                                       │ gRPC                                 │
│                                       ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SPIRE Agent (DaemonSet - one per node)                              │    │
│  │  ─────────────────────────────────────                               │    │
│  │  • Attests workloads using Kubernetes PSAT                         │    │
│  │  • Exposes Workload API via Unix socket                            │    │
│  │  • Caches SVIDs for workloads                                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                       │                                      │
│                                       │ Unix Socket                          │
│                                       ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SPIFFE CSI Driver (DaemonSet)                                       │    │
│  │  ─────────────────────────────                                       │    │
│  │  • Mounts Workload API socket into pods                             │    │
│  │  • driver: csi.spiffe.io                                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  OIDC Discovery Provider (Deployment)                                │    │
│  │  ────────────────────────────────────                                │    │
│  │  • Exposes /.well-known/openid-configuration                        │    │
│  │  • Provides /keys endpoint with JWKS                                │    │
│  │  • Enables external OIDC validation of JWT-SVIDs                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### How SPIFFE Identity Issuance Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SPIFFE Identity Issuance Flow                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. Pod starts with SPIFFE CSI volume mounted                              │
│                                                                              │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  Pod Spec:                                                       │    │
│      │    volumes:                                                      │    │
│      │      - name: spiffe-workload-api                                │    │
│      │        csi:                                                      │    │
│      │          driver: csi.spiffe.io    ◄── Triggers CSI Driver       │    │
│      │          readOnly: true                                          │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                                       │                                      │
│                                       ▼                                      │
│   2. CSI Driver mounts socket from SPIRE Agent                              │
│                                                                              │
│      ┌─────────────┐     mount      ┌─────────────┐                         │
│      │  CSI Driver │───────────────►│  SPIRE      │                         │
│      │             │  socket        │  Agent      │                         │
│      └─────────────┘                └──────┬──────┘                         │
│                                            │                                 │
│                                            │ /spiffe-workload-api/           │
│                                            │   spire-agent.sock              │
│                                            ▼                                 │
│   3. Application requests identity via Workload API                         │
│                                                                              │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  Application Code:                                               │    │
│      │                                                                  │    │
│      │  from spiffe import WorkloadApiClient                           │    │
│      │  client = WorkloadApiClient("unix:///spiffe-workload-api/...")  │    │
│      │  svid = client.fetch_x509_context().default_svid                │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                                       │                                      │
│                                       ▼                                      │
│   4. SPIRE Agent attests workload and requests SVID from Server            │
│                                                                              │
│      ┌─────────────┐   attest      ┌─────────────┐   request   ┌─────────┐ │
│      │  SPIRE      │──────────────►│  Kubernetes │   SVID     │  SPIRE  │ │
│      │  Agent      │   workload    │  API        │────────────►│  Server │ │
│      └─────────────┘               └─────────────┘             └────┬────┘ │
│                                                                      │      │
│                                                                      │      │
│   5. SPIRE Server issues X.509-SVID                                        │
│                                                                              │
│      ┌─────────────────────────────────────────────────────────────────┐    │
│      │  X.509-SVID Contents:                                            │    │
│      │                                                                  │    │
│      │  • Certificate with SAN:                                        │    │
│      │    spiffe://trust-domain/ns/namespace/sa/serviceaccount         │    │
│      │  • Private Key                                                   │    │
│      │  • Trust Bundle (CA certificates)                               │    │
│      │  • TTL: 1 hour (configurable)                                   │    │
│      └─────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- **OpenShift 4.14+** (ROSA, OCP, or similar)
- **Cluster-admin access** via `oc` CLI
- **OperatorHub access** (Red Hat Operators catalog)

---

## Installation Steps

### Step 1: Create Namespace

```bash
oc apply -f k8s/01-namespace.yaml
```

This creates the `zero-trust-workload-identity-manager` namespace where all SPIRE components will be deployed.

### Step 2: Create OperatorGroup

```bash
oc apply -f k8s/02-operatorgroup.yaml
```

The OperatorGroup allows the operator to manage resources in its namespace.

### Step 3: Subscribe to the Operator

```bash
oc apply -f k8s/03-subscription.yaml

# Wait for the operator to be installed
oc get csv -n zero-trust-workload-identity-manager -w
```

Wait until the ClusterServiceVersion shows `Succeeded` phase.

### Step 4: Create ZeroTrustWorkloadIdentityManager

```bash
oc apply -f k8s/04-zerotrustworkloadidentitymanager.yaml
```

**Important:** Before applying, update the `trustDomain` to match your cluster:

```yaml
spec:
  trustDomain: "apps.YOUR-CLUSTER-DOMAIN.com"  # Update this!
  clusterName: "your-cluster-name"
```

### Step 5: Deploy SPIRE Server

```bash
oc apply -f k8s/05-spireserver.yaml
```

**Important:** Update the `jwtIssuer` to match your OIDC Discovery Provider route:

```yaml
spec:
  jwtIssuer: "https://oidc-discovery.apps.YOUR-CLUSTER-DOMAIN.com"  # Update this!
```

Wait for the SPIRE Server to be ready:

```bash
oc get pods -n zero-trust-workload-identity-manager -l app=spire-server -w
```

### Step 6: Deploy SPIRE Agent

```bash
oc apply -f k8s/06-spireagent.yaml
```

Wait for agents to be running on all nodes:

```bash
oc get pods -n zero-trust-workload-identity-manager -l app=spire-agent -w
```

### Step 7: Deploy SPIFFE CSI Driver

```bash
oc apply -f k8s/07-spiffecsidriver.yaml
```

Verify the CSI driver is registered:

```bash
oc get csidrivers | grep spiffe
```

### Step 8: Deploy OIDC Discovery Provider

```bash
oc apply -f k8s/08-spireoidcdiscoveryprovider.yaml
```

**Important:** Update the `jwtIssuer` to match Step 5:

```yaml
spec:
  jwtIssuer: "https://oidc-discovery.apps.YOUR-CLUSTER-DOMAIN.com"  # Must match SpireServer!
```

Verify the OIDC endpoint is accessible:

```bash
OIDC_URL=$(oc get route -n zero-trust-workload-identity-manager -l app=spire-oidc -o jsonpath='{.items[0].spec.host}')
curl -sk https://$OIDC_URL/.well-known/openid-configuration | jq .
```

---

## Configuration Files Explained

### 1. Namespace (`01-namespace.yaml`)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: zero-trust-workload-identity-manager
```

All SPIRE components run in this namespace.

---

### 2. OperatorGroup (`02-operatorgroup.yaml`)

```yaml
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-zero-trust-workload-identity-manager
  namespace: zero-trust-workload-identity-manager
spec:
  upgradeStrategy: Default
```

Required for OLM-managed operators. Defines the scope of operator management.

---

### 3. Subscription (`03-subscription.yaml`)

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-zero-trust-workload-identity-manager
  namespace: zero-trust-workload-identity-manager
spec:
  channel: stable-v1
  name: openshift-zero-trust-workload-identity-manager
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

| Field | Description |
|-------|-------------|
| `channel` | Release channel (stable-v1 recommended) |
| `source` | Catalog source (redhat-operators for supported version) |
| `installPlanApproval` | Automatic installs updates automatically |

---

### 4. ZeroTrustWorkloadIdentityManager (`04-zerotrustworkloadidentitymanager.yaml`)

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: ZeroTrustWorkloadIdentityManager
metadata:
  name: cluster
spec:
  trustDomain: "apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com"
  clusterName: "rosa-cluster"
  bundleConfigMap: "spire-bundle"
```

| Field | Description |
|-------|-------------|
| `trustDomain` | The SPIFFE trust domain (usually your cluster's apps domain) |
| `clusterName` | Identifier for this cluster in multi-cluster setups |
| `bundleConfigMap` | Name of ConfigMap that will contain the SPIRE CA bundle |

**The trust domain appears in all SPIFFE IDs:**
```
spiffe://apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com/ns/my-namespace/sa/my-sa
         └─────────────────────────────────────────────┘
                        Trust Domain
```

---

### 5. SpireServer (`05-spireserver.yaml`)

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpireServer
metadata:
  name: cluster
spec:
  logLevel: "info"
  logFormat: "text"
  jwtIssuer: "https://oidc-discovery.apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com"
  caValidity: "24h"
  defaultX509Validity: "1h"
  defaultJWTValidity: "5m"
  jwtKeyType: "rsa-2048"
  caSubject:
    country: "US"
    organization: "Red Hat Demo"
    commonName: "SPIRE Server CA"
  persistence:
    size: "1Gi"
    accessMode: "ReadWriteOnce"
  datastore:
    databaseType: "sqlite3"
    connectionString: "/run/spire/data/datastore.sqlite3"
```

| Field | Description |
|-------|-------------|
| `jwtIssuer` | URL of OIDC Discovery Provider (must match the route) |
| `caValidity` | How long the CA certificate is valid |
| `defaultX509Validity` | Default TTL for X.509-SVIDs (1 hour) |
| `defaultJWTValidity` | Default TTL for JWT-SVIDs (5 minutes) |
| `jwtKeyType` | Key type for JWT signing (rsa-2048 or ec-p256) |
| `caSubject` | Subject fields for the CA certificate |
| `persistence` | Storage for the SPIRE datastore |

---

### 6. SpireAgent (`06-spireagent.yaml`)

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpireAgent
metadata:
  name: cluster
spec:
  socketPath: "/run/spire/agent-sockets"
  logLevel: "info"
  nodeAttestor:
    k8sPSATEnabled: "true"
  workloadAttestors:
    k8sEnabled: "true"
    workloadAttestorsVerification:
      type: "auto"
      hostCertBasePath: "/etc/kubernetes"
      hostCertFileName: "kubelet-ca.crt"
    disableContainerSelectors: "false"
    useNewContainerLocator: "true"
```

| Field | Description |
|-------|-------------|
| `socketPath` | Where the agent exposes the Workload API socket |
| `nodeAttestor.k8sPSATEnabled` | Use Kubernetes Projected Service Account Tokens |
| `workloadAttestors.k8sEnabled` | Attest workloads using Kubernetes metadata |

**PSAT (Projected Service Account Token) Attestation:**
- Kubernetes API server issues short-lived OIDC tokens to pods
- SPIRE Agent validates these tokens against Kubernetes API
- Provides cryptographic proof of pod identity

---

### 7. SpiffeCSIDriver (`07-spiffecsidriver.yaml`)

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpiffeCSIDriver
metadata:
  name: cluster
spec:
  agentSocketPath: "/run/spire/agent-sockets"
  pluginName: "csi.spiffe.io"
```

| Field | Description |
|-------|-------------|
| `agentSocketPath` | Must match SpireAgent's socketPath |
| `pluginName` | The CSI driver name used in pod volumes |

**Usage in Pods:**
```yaml
volumes:
  - name: spiffe-workload-api
    csi:
      driver: csi.spiffe.io    # Matches pluginName
      readOnly: true
```

---

### 8. SpireOIDCDiscoveryProvider (`08-spireoidcdiscoveryprovider.yaml`)

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: SpireOIDCDiscoveryProvider
metadata:
  name: cluster
spec:
  logLevel: "info"
  csiDriverName: "csi.spiffe.io"
  jwtIssuer: "https://oidc-discovery.apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com"
  replicaCount: 1
  managedRoute: "true"
```

| Field | Description |
|-------|-------------|
| `csiDriverName` | Must match SpiffeCSIDriver's pluginName |
| `jwtIssuer` | Must match SpireServer's jwtIssuer |
| `managedRoute` | Automatically create OpenShift Route |

**OIDC Endpoints Provided:**
- `/.well-known/openid-configuration` - OIDC discovery document
- `/keys` - JSON Web Key Set (JWKS) for token validation

---

## Verification

### Check All Components Are Running

```bash
# Check all pods
oc get pods -n zero-trust-workload-identity-manager

# Expected output:
# NAME                                    READY   STATUS    RESTARTS   AGE
# spire-server-0                          1/1     Running   0          5m
# spire-agent-xxxxx                       1/1     Running   0          4m
# spire-agent-yyyyy                       1/1     Running   0          4m
# spiffe-csi-driver-xxxxx                 2/2     Running   0          3m
# spire-oidc-discovery-provider-xxxxx     1/1     Running   0          2m
```

### Check SPIRE Server Health

```bash
oc exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  /opt/spire/bin/spire-server healthcheck
```

### Check SPIRE Bundle ConfigMap

```bash
oc get configmap spire-bundle -n zero-trust-workload-identity-manager -o yaml
```

### Verify OIDC Discovery Provider

```bash
OIDC_URL=$(oc get route -n zero-trust-workload-identity-manager -o jsonpath='{.items[0].spec.host}')

# Check OIDC configuration
curl -sk https://$OIDC_URL/.well-known/openid-configuration | jq .

# Check JWKS
curl -sk https://$OIDC_URL/keys | jq .
```

### Check CSI Driver

```bash
oc get csidrivers csi.spiffe.io
```

---

## Troubleshooting

### SPIRE Server Won't Start

```bash
# Check logs
oc logs -n zero-trust-workload-identity-manager spire-server-0

# Common issues:
# - PVC not bound (check storage class)
# - Invalid trust domain
```

### SPIRE Agents Not Running

```bash
# Check agent logs
oc logs -n zero-trust-workload-identity-manager -l app=spire-agent

# Common issues:
# - Can't connect to SPIRE Server
# - PSAT validation failing
```

### Workload Not Getting Identity

```bash
# Check if ClusterSPIFFEID exists
oc get clusterspiffeids

# Check pod has correct labels
oc get pod <pod-name> -o yaml | grep -A5 labels

# Check SPIFFE socket is mounted
oc exec <pod-name> -- ls -la /spiffe-workload-api/
```

### OIDC Discovery Provider Returns 404

```bash
# Check route exists
oc get routes -n zero-trust-workload-identity-manager

# Check jwtIssuer matches route URL
oc get spireserver cluster -o yaml | grep jwtIssuer
oc get spireoidcdiscoveryprovider cluster -o yaml | grep jwtIssuer
```

---

## Quick Reference

| Resource | Purpose |
|----------|---------|
| `ZeroTrustWorkloadIdentityManager` | Main CR that enables the operator |
| `SpireServer` | Configures the SPIRE Server |
| `SpireAgent` | Configures SPIRE Agents (DaemonSet) |
| `SpiffeCSIDriver` | Enables CSI volume mounting |
| `SpireOIDCDiscoveryProvider` | Exposes OIDC endpoints |
| `ClusterSPIFFEID` | Registers workloads to receive SVIDs |

---

## Next Steps

After SPIRE is installed:

1. **Create a ClusterSPIFFEID** to register your workloads
2. **Deploy your application** with the SPIFFE CSI volume
3. **Use the SVID** for authentication (X.509 or JWT)

See the main [README.md](../README.md) for the PostgreSQL demo that uses SPIFFE X.509 certificates.
