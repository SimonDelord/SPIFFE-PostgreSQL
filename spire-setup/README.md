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
8. [Making an Application SPIFFE-Enabled](#making-an-application-spiffe-enabled)

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

## Making an Application SPIFFE-Enabled

Once SPIRE is installed, you need to configure your application to receive SPIFFE identities. This is done through a **ClusterSPIFFEID** resource - you don't manually configure entries in the SPIRE Server.

### Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Automatic Workload Registration                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. ClusterSPIFFEID (defines which pods get identities)                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  spec:                                                              │   │
│   │    spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/..."          │   │
│   │    podSelector:                                                     │   │
│   │      matchLabels:                                                   │   │
│   │        spiffe.io/spiffe-id: "my-app"     ◄── Selector              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              │ SPIRE Controller watches & auto-registers    │
│                              ▼                                               │
│   2. Pod with matching labels                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  labels:                                                            │   │
│   │    spiffe.io/spiffe-id: "my-app"         ◄── Matches!              │   │
│   │  volumes:                                                           │   │
│   │    - csi:                                                           │   │
│   │        driver: csi.spiffe.io             ◄── Mounts SPIRE socket   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│   3. SPIRE Agent issues X.509-SVID automatically when pod starts           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Step 1: Create a ClusterSPIFFEID

Create a `ClusterSPIFFEID` resource that defines which pods should receive SPIFFE identities:

```yaml
apiVersion: spire.spiffe.io/v1alpha1
kind: ClusterSPIFFEID
metadata:
  name: my-app-workload
spec:
  # Template for the SPIFFE ID
  # Available variables: .TrustDomain, .PodMeta.Namespace, .PodSpec.ServiceAccountName
  spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}/sa/{{ .PodSpec.ServiceAccountName }}"
  
  # Match pods with this label
  podSelector:
    matchLabels:
      spiffe.io/spiffe-id: "my-app"
  
  # Optional: Only in namespaces with this label
  namespaceSelector:
    matchLabels:
      app.kubernetes.io/part-of: my-project
  
  # Optional: DNS names to include in the certificate
  dnsNameTemplates:
    - "{{ .PodMeta.Name }}.{{ .PodMeta.Namespace }}.svc.cluster.local"
  
  # Certificate TTL (default: 1h)
  ttl: "1h"
```

### Step 2: Label Your Namespace

If using `namespaceSelector`, label your namespace:

```bash
oc label namespace my-namespace app.kubernetes.io/part-of=my-project
```

### Step 3: Configure Your Pod/Deployment

Add the required labels and CSI volume to your deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: my-namespace
spec:
  template:
    metadata:
      labels:
        app: my-app
        # This label must match the ClusterSPIFFEID podSelector
        spiffe.io/spiffe-id: "my-app"
    spec:
      # ServiceAccount name is used in the SPIFFE ID
      serviceAccountName: my-app-sa
      
      containers:
        - name: my-app
          image: my-app:latest
          env:
            # Tell your app where to find the SPIRE socket
            - name: SPIFFE_ENDPOINT_SOCKET
              value: "unix:///spiffe-workload-api/spire-agent.sock"
          volumeMounts:
            # Mount the Workload API socket
            - name: spiffe-workload-api
              mountPath: /spiffe-workload-api
              readOnly: true
      
      volumes:
        # CSI volume that provides the SPIRE Workload API
        - name: spiffe-workload-api
          csi:
            driver: csi.spiffe.io
            readOnly: true
```

### Step 4: Use the SVID in Your Application

**Python Example:**

```python
from spiffe import WorkloadApiClient

# Connect to the Workload API
client = WorkloadApiClient("unix:///spiffe-workload-api/spire-agent.sock")

# Fetch X.509-SVID
x509_context = client.fetch_x509_context()
svid = x509_context.default_svid

# Access the certificate and key
print(f"SPIFFE ID: {svid.spiffe_id}")
print(f"Certificate: {svid.cert_chain}")
print(f"Private Key: {svid.private_key}")
```

**Go Example:**

```go
import "github.com/spiffe/go-spiffe/v2/workloadapi"

ctx := context.Background()
client, _ := workloadapi.New(ctx, workloadapi.WithAddr("unix:///spiffe-workload-api/spire-agent.sock"))

x509SVID, _ := client.FetchX509SVID(ctx)
fmt.Printf("SPIFFE ID: %s\n", x509SVID.ID)
```

### Registration Flow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         How Registration Works                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. You create ClusterSPIFFEID                                              │
│     └──► SPIRE Controller creates registration entry in SPIRE Server       │
│                                                                              │
│  2. Pod starts with matching labels + CSI volume                            │
│     └──► CSI Driver mounts /spiffe-workload-api/spire-agent.sock           │
│                                                                              │
│  3. SPIRE Agent attests the workload                                        │
│     └──► Checks: namespace, serviceaccount, labels                         │
│     └──► Matches registration entry                                         │
│                                                                              │
│  4. SPIRE Agent issues X.509-SVID                                           │
│     └──► Available via Workload API socket                                  │
│     └──► Auto-rotates before expiry                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Verification Commands

```bash
# Check ClusterSPIFFEID was created
oc get clusterspiffeids

# See details of your registration
oc describe clusterspiffeid my-app-workload

# Check if pod has the SPIFFE socket mounted
oc exec my-pod -- ls -la /spiffe-workload-api/

# From inside the pod, check identity (if you have the spiffe-helper)
oc exec my-pod -- cat /spiffe-workload-api/svid.pem
```

### Checklist: Making an App SPIFFE-Enabled

| Step | Action | Verification |
|------|--------|--------------|
| ✅ | Create `ClusterSPIFFEID` | `oc get clusterspiffeids` |
| ✅ | Label namespace (if using namespaceSelector) | `oc get ns -l app.kubernetes.io/part-of=...` |
| ✅ | Add `spiffe.io/spiffe-id` label to pod | `oc get pod -l spiffe.io/spiffe-id=...` |
| ✅ | Set `serviceAccountName` in pod spec | - |
| ✅ | Add CSI volume (`csi.spiffe.io`) | `oc describe pod ... \| grep csi.spiffe.io` |
| ✅ | Mount volume at `/spiffe-workload-api` | `oc exec pod -- ls /spiffe-workload-api/` |
| ✅ | Set `SPIFFE_ENDPOINT_SOCKET` env var | - |
| ✅ | Use Workload API in application code | Test with `/api/identity` endpoint |

---

## Next Steps

After SPIRE is installed:

1. **Create a ClusterSPIFFEID** to register your workloads (see above)
2. **Deploy your application** with the SPIFFE CSI volume
3. **Use the SVID** for authentication (X.509 or JWT)

See the main [README.md](../README.md) for the PostgreSQL demo that uses SPIFFE X.509 certificates.
