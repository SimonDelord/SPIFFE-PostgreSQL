# EDB Use Case: SPIFFE X.509 Certificate Authentication with PostgreSQL

This demo shows how a **SPIFFE-enabled application** uses its **X.509-SVID** (certificate) to authenticate to a **PostgreSQL database**, with the database performing both **authentication** (certificate verification) and **authorization** (role-based permissions).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [File Structure](#file-structure)
5. [Configuration Files Explained](#configuration-files-explained)
6. [Step-by-Step Deployment](#step-by-step-deployment)
7. [Testing the Demo](#testing-the-demo)
8. [How It Works](#how-it-works)
9. [Troubleshooting](#troubleshooting)
10. [Key Learnings](#key-learnings)

---

## Overview

### The Scenario

```
┌─────────────────────────────────────────────────────────────────────────────┐
│            SPIFFE X.509 Certificate → PostgreSQL Authentication             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────────┐     ┌─────────────────────────────┐   │
│   │  SPIFFE-Enabled Client App      │     │  PostgreSQL Database        │   │
│   │  (spiffe-edb-demo namespace)    │     │  (edb namespace)            │   │
│   │                                 │     │                             │   │
│   │  Gets X.509-SVID from SPIRE:    │     │  Configured with:           │   │
│   │  ┌───────────────────────────┐  │     │  ┌───────────────────────┐  │   │
│   │  │ Certificate:              │  │     │  │ • SPIRE CA trusted    │  │   │
│   │  │   SAN: spiffe://...       │  │     │  │ • SSL required        │  │   │
│   │  │   /ns/spiffe-edb-demo/    │══╬═════╬══│ • Client cert verify  │  │   │
│   │  │   sa/db-client-app        │  │ mTLS│  │ • Role-based access   │  │   │
│   │  │                           │  │     │  │                       │  │   │
│   │  │ Private Key               │  │     │  │ Roles:                │  │   │
│   │  └───────────────────────────┘  │     │  │ • app_readonly        │  │   │
│   │                                 │     │  │ • app_readwrite       │  │   │
│   └─────────────────────────────────┘     │  │ • app_admin           │  │   │
│                                           └─────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **No passwords** | No database passwords to manage or rotate |
| **Automatic rotation** | SPIFFE certificates rotate automatically (every ~1 hour) |
| **Strong identity** | Cryptographic proof of workload identity |
| **Fine-grained authZ** | Different SPIFFE workloads can have different database roles |
| **Audit trail** | Clear identity in database connection logs |

### Demo Results

| Test | Result |
|------|--------|
| SPIFFE Identity Fetch | ✅ `spiffe://apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app` |
| Database Connection | ✅ Connected as `app_readonly` user |
| SELECT Query | ✅ Success - 3 rows returned |
| INSERT Query | ❌ Permission denied (expected - read-only role) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OpenShift Cluster                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  zero-trust-workload-identity-manager namespace                      │    │
│  │                                                                      │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │    │
│  │  │   SPIRE     │  │   SPIRE     │  │   SPIFFE    │                  │    │
│  │  │   Server    │  │   Agent     │  │   CSI       │                  │    │
│  │  │             │  │  (DaemonSet)│  │   Driver    │                  │    │
│  │  └──────┬──────┘  └──────┬──────┘  └─────────────┘                  │    │
│  │         │                │                                           │    │
│  │         │  Issues SVIDs  │  Delivers to pods via CSI volume         │    │
│  │         └────────────────┘                                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                          │                                   │
│                                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  spiffe-edb-demo namespace                                           │    │
│  │                                                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────┐    │    │
│  │  │  db-client-app Pod                                           │    │    │
│  │  │                                                              │    │    │
│  │  │  ┌──────────────────┐     ┌────────────────────────────┐    │    │    │
│  │  │  │  Flask App       │     │  SPIFFE CSI Volume         │    │    │    │
│  │  │  │                  │     │  /spiffe-workload-api/     │    │    │    │
│  │  │  │  Uses X.509-SVID │◄────│    spire-agent.sock        │    │    │    │
│  │  │  │  for DB auth     │     │                            │    │    │    │
│  │  │  └────────┬─────────┘     └────────────────────────────┘    │    │    │
│  │  │           │                                                  │    │    │
│  │  └───────────┼──────────────────────────────────────────────────┘    │    │
│  │              │                                                        │    │
│  └──────────────┼────────────────────────────────────────────────────────┘    │
│                 │                                                              │
│                 │  mTLS Connection (TCP 5432)                                 │
│                 │  Client presents X.509-SVID                                 │
│                 ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  edb namespace                                                       │    │
│  │                                                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────┐    │    │
│  │  │  PostgreSQL StatefulSet                                      │    │    │
│  │  │                                                              │    │    │
│  │  │  • Server TLS certificate (OpenShift Service CA)            │    │    │
│  │  │  • Client CA = SPIRE CA bundle (trusts SPIFFE certs)        │    │    │
│  │  │  • pg_hba.conf: hostssl with clientcert=verify-ca           │    │    │
│  │  │  • Roles: app_readonly, app_readwrite, app_admin            │    │    │
│  │  │                                                              │    │    │
│  │  └─────────────────────────────────────────────────────────────┘    │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- OpenShift cluster (tested on ROSA)
- **SPIRE deployed** via Zero Trust Workload Identity Manager operator
- `oc` CLI with cluster-admin access
- The `edb` namespace must exist

---

## File Structure

```
EDB use case/
├── README.md                           # This documentation
│
├── k8s/
│   ├── edb/                            # PostgreSQL database resources
│   │   ├── postgres-statefulset.yaml   # Main PostgreSQL deployment
│   │   ├── serviceaccount.yaml         # Service account for PostgreSQL
│   │   ├── spire-ca-secret.yaml        # Reference for SPIRE CA secret
│   │   └── edb-cluster.yaml            # (Alternative) EDB operator config
│   │
│   └── db-client/                      # SPIFFE-enabled client app resources
│       ├── namespace.yaml              # Namespace definition
│       ├── serviceaccount.yaml         # Service account for client
│       ├── clusterspiffeid.yaml        # SPIRE workload registration
│       ├── configmap.yaml              # Database connection config
│       ├── imagestream.yaml            # OpenShift image stream
│       ├── buildconfig.yaml            # OpenShift build config
│       ├── deployment.yaml             # Client app deployment
│       ├── service.yaml                # Internal service
│       └── route.yaml                  # External route
│
├── db-client-app/                      # Client application source
│   ├── app.py                          # Flask application
│   ├── requirements.txt                # Python dependencies
│   └── Dockerfile                      # Container build file
│
└── scripts/
    ├── deploy.sh                       # Automated deployment script
    └── test-connection.sh              # Connection test script
```

---

## Configuration Files Explained

### 1. PostgreSQL Configuration

#### `k8s/edb/postgres-statefulset.yaml`

This file contains:
- **ConfigMap** with PostgreSQL configuration files
- **Service** with OpenShift TLS certificate annotation
- **StatefulSet** for PostgreSQL

**Key Configuration - `postgresql.conf`:**
```ini
# SSL Configuration
ssl = on
ssl_cert_file = '/var/lib/postgresql/server-certs/tls.crt'
ssl_key_file = '/var/lib/postgresql/server-certs/tls.key'
ssl_ca_file = '/var/lib/postgresql/client-ca/ca.crt'    # SPIRE CA!
ssl_min_protocol_version = 'TLSv1.2'
```

**Key Configuration - `pg_hba.conf`:**
```
# TYPE  DATABASE  USER          ADDRESS       METHOD    OPTIONS

# Local admin access
local   all       postgres                    trust

# SPIFFE certificate authentication
# verify-ca = verify cert is signed by trusted CA (SPIRE)
# trust = allow connection if cert is valid (no password)
hostssl all       app_readonly  0.0.0.0/0     trust     clientcert=verify-ca
hostssl all       app_readwrite 0.0.0.0/0     trust     clientcert=verify-ca
hostssl all       app_admin     0.0.0.0/0     trust     clientcert=verify-ca

# Password auth for admin
hostssl all       postgres      0.0.0.0/0     scram-sha-256
```

**Database Initialization SQL:**
```sql
-- Create roles with different permission levels
CREATE ROLE app_readonly WITH LOGIN;
CREATE ROLE app_readwrite WITH LOGIN;
CREATE ROLE app_admin WITH LOGIN CREATEDB CREATEROLE;

-- Create demo database and table
CREATE DATABASE appdb;
\connect appdb

CREATE TABLE demo_data (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100)
);

-- Grant permissions
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_readonly;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_readwrite;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin;

-- Sample data
INSERT INTO demo_data (name, created_by) VALUES 
  ('Sample Record 1', 'system'),
  ('Sample Record 2', 'system'),
  ('Sample Record 3', 'system');
```

**Service with TLS Certificate:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: edb-spiffe-postgres
  namespace: edb
  annotations:
    # OpenShift automatically generates TLS certificate for this service
    service.beta.openshift.io/serving-cert-secret-name: postgres-server-tls
spec:
  selector:
    app: edb-spiffe-postgres
  ports:
    - port: 5432
      targetPort: 5432
```

#### Understanding the Service TLS Certificate Annotation

This annotation uses **OpenShift Service Serving Certificates**, a built-in feature that automatically generates and manages TLS certificates for services.

**How It Works:**

When you add the annotation `service.beta.openshift.io/serving-cert-secret-name: postgres-server-tls`, OpenShift's **Service CA Operator** automatically:

1. **Generates a TLS certificate** signed by the cluster's internal Service CA
2. **Creates a Secret** named `postgres-server-tls` containing:
   - `tls.crt` - The server certificate
   - `tls.key` - The private key
3. **Auto-rotates** the certificate before expiration

```
┌─────────────────────────────────────────────────────────────────────┐
│                    OpenShift Service CA Flow                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. You create Service with annotation                               │
│     ┌──────────────────────────────────────────────────────────┐    │
│     │  service.beta.openshift.io/serving-cert-secret-name:     │    │
│     │    postgres-server-tls                                    │    │
│     └──────────────────────────────────────────────────────────┘    │
│                              │                                       │
│                              ▼                                       │
│  2. Service CA Operator detects annotation                          │
│     ┌─────────────────────┐                                         │
│     │  Service CA         │                                         │
│     │  Operator           │──────► Generates certificate for:       │
│     │  (watches services) │        edb-spiffe-postgres.edb.svc      │
│     └─────────────────────┘                                         │
│                              │                                       │
│                              ▼                                       │
│  3. Creates Secret automatically                                     │
│     ┌──────────────────────────────────────────────────────────┐    │
│     │  Secret: postgres-server-tls                              │    │
│     │  ├── tls.crt  (certificate for the service)              │    │
│     │  └── tls.key  (private key)                              │    │
│     └──────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Why We Need It:**

PostgreSQL requires **server-side TLS** to:
- **Encrypt connections** between clients and the database
- **Prove server identity** to connecting clients

| Without This Annotation | With This Annotation |
|-------------------------|----------------------|
| Manually generate certificates | OpenShift auto-generates them |
| Manually manage certificate rotation | OpenShift auto-rotates them |
| Complex PKI setup required | Simple annotation |
| Certificates could expire unnoticed | Always valid |

**The Two Certificates in Our Setup:**

Our PostgreSQL setup uses **two different CAs** for different purposes:

```
┌─────────────────────────────────────────────────────────────────────┐
│                  PostgreSQL TLS Configuration                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  SERVER CERTIFICATE (OpenShift Service CA)                          │
│  ─────────────────────────────────────────                          │
│  Purpose: PostgreSQL proves its identity to clients                 │
│  Source:  service.beta.openshift.io/serving-cert-secret-name        │
│  Used in: ssl_cert_file, ssl_key_file                               │
│                                                                      │
│     ┌─────────────┐          ┌─────────────────┐                    │
│     │  OpenShift  │ signs    │  postgres-      │                    │
│     │  Service CA │─────────►│  server-tls     │                    │
│     └─────────────┘          │  Secret         │                    │
│                              └─────────────────┘                    │
│                                                                      │
│  CLIENT CA (SPIRE CA)                                               │
│  ────────────────────                                               │
│  Purpose: PostgreSQL verifies client certificates                   │
│  Source:  SPIRE trust bundle (spire-ca-bundle secret)               │
│  Used in: ssl_ca_file                                               │
│                                                                      │
│     ┌─────────────┐          ┌─────────────────┐                    │
│     │  SPIRE      │ signs    │  Client App     │                    │
│     │  CA         │─────────►│  X.509-SVID     │                    │
│     └─────────────┘          └─────────────────┘                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**In `postgresql.conf`:**

```ini
# Server presents this certificate to clients (from OpenShift Service CA)
ssl_cert_file = '/var/lib/postgresql/server-certs/tls.crt'
ssl_key_file = '/var/lib/postgresql/server-certs/tls.key'

# Server uses this CA to verify CLIENT certificates (from SPIRE)
ssl_ca_file = '/var/lib/postgresql/client-ca/ca.crt'
```

| Component | Purpose | Source |
|-----------|---------|--------|
| **Server TLS** (OpenShift annotation) | PostgreSQL proves it's the real database | OpenShift Service CA |
| **Client CA** (SPIRE bundle) | PostgreSQL verifies SPIFFE client certs | SPIRE CA |

> **Note:** The OpenShift Service CA annotation is a convenience feature that saves you from manually managing server certificates. It is unrelated to SPIFFE, but necessary for PostgreSQL to support TLS connections.

---

### 2. SPIFFE Client Configuration

#### `k8s/db-client/clusterspiffeid.yaml`

Registers the workload with SPIRE to receive SPIFFE identities:

```yaml
apiVersion: spire.spiffe.io/v1alpha1
kind: ClusterSPIFFEID
metadata:
  name: db-client-workload
spec:
  # SPIFFE ID template
  spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}/sa/{{ .PodSpec.ServiceAccountName }}"
  
  # Match pods with this label
  podSelector:
    matchLabels:
      spiffe.io/spiffe-id: "db-client-app"
  
  # Namespace selector
  namespaceSelector:
    matchLabels:
      app.kubernetes.io/part-of: spiffe-demo
  
  # Certificate TTL
  ttl: "1h"
```

#### `k8s/db-client/deployment.yaml`

Key aspects of the deployment:

```yaml
spec:
  template:
    metadata:
      labels:
        app: db-client-app
        spiffe.io/spiffe-id: "db-client-app"  # Matches ClusterSPIFFEID selector
    spec:
      serviceAccountName: db-client-app
      containers:
        - name: db-client
          env:
            - name: DB_HOST
              value: "edb-spiffe-postgres.edb.svc.cluster.local"
            - name: DB_USER
              value: "app_readonly"
            - name: DB_SSLMODE
              value: "require"
            - name: SPIFFE_ENDPOINT_SOCKET
              value: "unix:///spiffe-workload-api/spire-agent.sock"
          volumeMounts:
            - name: spiffe-workload-api
              mountPath: /spiffe-workload-api
              readOnly: true
      volumes:
        - name: spiffe-workload-api
          csi:
            driver: csi.spiffe.io    # SPIFFE CSI Driver
            readOnly: true
```

#### `k8s/db-client/configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-client-config
  namespace: spiffe-edb-demo
data:
  DB_HOST: "edb-spiffe-postgres.edb.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "appdb"
  DB_USER: "app_readonly"
  DB_SSLMODE: "require"
```

---

### 3. Client Application

#### `db-client-app/app.py`

Key functions:

**Getting SPIFFE Identity:**
```python
from spiffe import WorkloadApiClient

def get_x509_svid():
    """Fetch X.509-SVID from SPIRE."""
    client = WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
    x509_source = client.fetch_x509_context()
    return x509_source.default_svid
```

**Connecting to PostgreSQL with Certificate:**
```python
import psycopg2
import tempfile

def get_db_connection():
    svid = get_x509_svid()
    
    # Write certificate to temp file
    cert_file = tempfile.NamedTemporaryFile(suffix='.pem', delete=False)
    for cert in svid.cert_chain:
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    cert_file.close()
    
    # Write private key to temp file
    key_file = tempfile.NamedTemporaryFile(suffix='.pem', delete=False)
    key_bytes = svid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    key_file.write(key_bytes)
    key_file.close()
    
    # Connect using certificate
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        sslmode=DB_SSLMODE,
        sslcert=cert_file.name,
        sslkey=key_file.name
    )
    return conn
```

#### `db-client-app/requirements.txt`

```
Flask==2.3.3
psycopg2-binary==2.9.9
spiffe==0.2.6
cryptography>=41.0.0
```

---

## Step-by-Step Deployment

### Step 1: Create SPIRE CA Secret in EDB Namespace

The PostgreSQL database needs to trust the SPIRE CA to verify client certificates.

```bash
# Export SPIRE CA bundle from the SPIRE server ConfigMap
# and create a secret in the edb namespace

oc delete secret spire-ca-bundle -n edb --ignore-not-found

oc create secret generic spire-ca-bundle \
    --from-literal=ca.crt="$(oc get configmap spire-bundle \
        -n zero-trust-workload-identity-manager \
        -o jsonpath='{.data.bundle\.crt}')" \
    -n edb

# Verify the secret was created
oc get secret spire-ca-bundle -n edb
```

### Step 2: Create PostgreSQL Service Account

PostgreSQL needs to run with specific permissions on OpenShift.

```bash
# Create service account
oc create serviceaccount postgres-sa -n edb

# Grant anyuid SCC (required for PostgreSQL to run as uid 999)
oc adm policy add-scc-to-user anyuid -z postgres-sa -n edb
```

### Step 3: Deploy PostgreSQL

```bash
# Apply the PostgreSQL StatefulSet (includes ConfigMap, Service, StatefulSet)
oc apply -f k8s/edb/postgres-statefulset.yaml

# Wait for PostgreSQL to be ready
oc rollout status statefulset/edb-spiffe-postgres -n edb --timeout=120s

# Verify the pod is running
oc get pods -n edb

# Check PostgreSQL logs
oc logs -n edb edb-spiffe-postgres-0 -c postgres
```

### Step 4: Create Client Application Namespace

```bash
# Create namespace
oc apply -f k8s/db-client/namespace.yaml

# Label the namespace (required for ClusterSPIFFEID selector)
oc label namespace spiffe-edb-demo app.kubernetes.io/part-of=spiffe-demo --overwrite
```

### Step 5: Deploy Client Resources

```bash
# Create service account
oc apply -f k8s/db-client/serviceaccount.yaml

# Create ConfigMap with database connection settings
oc apply -f k8s/db-client/configmap.yaml

# Create OpenShift build resources
oc apply -f k8s/db-client/imagestream.yaml
oc apply -f k8s/db-client/buildconfig.yaml

# Register workload with SPIRE
oc apply -f k8s/db-client/clusterspiffeid.yaml

# Verify ClusterSPIFFEID was created
oc get clusterspiffeids
```

### Step 6: Build Client Application

```bash
# Build the container image from source
oc start-build db-client-app \
    --from-dir=db-client-app \
    -n spiffe-edb-demo \
    --follow

# Wait for build to complete
oc get builds -n spiffe-edb-demo
```

### Step 7: Deploy Client Application

```bash
# Deploy the application
oc apply -f k8s/db-client/deployment.yaml
oc apply -f k8s/db-client/service.yaml
oc apply -f k8s/db-client/route.yaml

# Wait for deployment to be ready
oc rollout status deployment/db-client-app -n spiffe-edb-demo --timeout=120s

# Get the application URL
oc get route db-client-app -n spiffe-edb-demo -o jsonpath='{.spec.host}'
```

---

## Testing the Demo

### Get Application URL

```bash
APP_URL=$(oc get route db-client-app -n spiffe-edb-demo -o jsonpath='{.spec.host}')
echo "Application URL: https://$APP_URL"
```

### Test 1: Verify SPIFFE Identity

```bash
curl -sk https://$APP_URL/api/identity | jq .
```

**Expected Output:**
```json
{
  "spiffe_id": "spiffe://apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app",
  "spiffe_available": true,
  "certificate_count": 1,
  "expires_at": "2026-04-08T00:09:05"
}
```

### Test 2: View Certificate Details

```bash
curl -sk https://$APP_URL/api/certificate | jq .
```

**Expected Output:**
```json
{
  "subject": {
    "countryName": "US",
    "organizationName": "SPIRE"
  },
  "common_name": "N/A",
  "san_uris": [
    "spiffe://apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com/ns/spiffe-edb-demo/sa/db-client-app"
  ],
  "issuer": {
    "commonName": "SPIRE Server CA",
    "countryName": "US",
    "organizationName": "Red Hat Demo"
  },
  "not_valid_before": "2026-04-07T23:08:55",
  "not_valid_after": "2026-04-08T00:09:05"
}
```

### Test 3: Test Database Connection

```bash
curl -sk https://$APP_URL/api/db/test | jq .
```

**Expected Output:**
```json
{
  "status": "connected",
  "current_user": "app_readonly",
  "session_user": "app_readonly",
  "database": "appdb",
  "postgres_version": "PostgreSQL 16.2 ...",
  "authentication": "X.509 Certificate (SPIFFE SVID)",
  "ssl_mode": "require"
}
```

### Test 4: Query Data (SELECT)

```bash
curl -sk https://$APP_URL/api/db/query | jq .
```

**Expected Output:**
```json
{
  "status": "success",
  "operation": "SELECT",
  "row_count": 3,
  "data": [
    {"id": 1, "name": "Sample Record 1", "created_by": "system"},
    {"id": 2, "name": "Sample Record 2", "created_by": "system"},
    {"id": 3, "name": "Sample Record 3", "created_by": "system"}
  ]
}
```

### Test 5: Insert Data (Should Fail - Read Only)

```bash
curl -sk -X POST https://$APP_URL/api/db/insert | jq .
```

**Expected Output:**
```json
{
  "status": "error",
  "operation": "INSERT",
  "error": "permission denied for table demo_data\n",
  "hint": "Your SPIFFE identity is mapped to a read-only role. INSERT requires app_readwrite or app_admin role."
}
```

### Web UI

You can also open the application URL in a browser to use the interactive web interface:

```
https://db-client-app-spiffe-edb-demo.apps.rosa.rosa-69t6c.hyq5.p3.openshiftapps.com
```

---

## How It Works

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SPIFFE Certificate Authentication Flow                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. POD STARTS - SPIFFE CSI Driver mounts Workload API socket              │
│                                                                              │
│   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐          │
│   │ db-client   │  Attest │   SPIRE     │ Request │   SPIRE     │          │
│   │ Pod         │────────►│   Agent     │────────►│   Server    │          │
│   └─────────────┘         └─────────────┘         └─────────────┘          │
│                                                          │                  │
│                                                          │ Issue X.509-SVID │
│                                                          ▼                  │
│                                                   Certificate with:         │
│                                                   • SAN: spiffe://...       │
│                                                   • 1 hour TTL              │
│                                                                              │
│   2. APP FETCHES SVID via Workload API                                      │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Python App calls:                                                   │   │
│   │  client = WorkloadApiClient("unix:///spiffe-workload-api/...")      │   │
│   │  svid = client.fetch_x509_context().default_svid                    │   │
│   │                                                                      │   │
│   │  svid.cert_chain  → X.509 Certificate                               │   │
│   │  svid.private_key → Private Key                                     │   │
│   │  svid.spiffe_id   → spiffe://trust-domain/ns/.../sa/...            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   3. TLS HANDSHAKE WITH POSTGRESQL                                          │
│                                                                              │
│   ┌─────────────┐                                      ┌─────────────────┐  │
│   │ db-client   │                                      │  PostgreSQL     │  │
│   │             │──── TLS ClientHello ────────────────►│                 │  │
│   │             │                                      │                 │  │
│   │             │◄─── ServerHello + Server Cert ──────│                 │  │
│   │             │     + CertificateRequest             │                 │  │
│   │             │                                      │                 │  │
│   │  sslcert=   │──── Client Cert (X.509-SVID) ───────►│  Verify cert   │  │
│   │  svid.pem   │                                      │  against       │  │
│   │             │                                      │  SPIRE CA      │  │
│   │  sslkey=    │◄─── Finished ───────────────────────│                 │  │
│   │  key.pem    │                                      │                 │  │
│   │             │═════ Encrypted SQL Connection ══════►│                 │  │
│   └─────────────┘                                      └─────────────────┘  │
│                                                                              │
│   4. POSTGRESQL VERIFIES CERTIFICATE                                        │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  PostgreSQL checks:                                                  │   │
│   │                                                                      │   │
│   │  ssl_ca_file = /var/lib/postgresql/client-ca/ca.crt (SPIRE CA)     │   │
│   │                                                                      │   │
│   │  ✓ Certificate is valid (not expired)                               │   │
│   │  ✓ Certificate is signed by trusted CA (SPIRE CA)                   │   │
│   │  ✓ Certificate chain is valid                                        │   │
│   │                                                                      │   │
│   │  pg_hba.conf rule matched:                                           │   │
│   │  hostssl all app_readonly 0.0.0.0/0 trust clientcert=verify-ca      │   │
│   │                                                                      │   │
│   │  → Connection allowed as user "app_readonly"                         │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   5. AUTHORIZATION (Role-Based Permissions)                                 │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  app_readonly role permissions:                                      │   │
│   │  • SELECT on demo_data ✓                                            │   │
│   │  • INSERT on demo_data ✗ (permission denied)                        │   │
│   │  • UPDATE on demo_data ✗ (permission denied)                        │   │
│   │  • DELETE on demo_data ✗ (permission denied)                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Technical Points

1. **SPIFFE Certificates Don't Have CN**: By default, SPIFFE X.509-SVIDs don't include a Common Name (CN). The identity is in the SAN (Subject Alternative Name) as a URI.

2. **clientcert=verify-ca**: We use `clientcert=verify-ca` instead of `clientcert=verify-full` because PostgreSQL's `verify-full` tries to match the CN, which doesn't exist in SPIFFE certs.

3. **Trust Authentication with Certificate Verification**: The combination of `trust` auth method with `clientcert=verify-ca` means:
   - The certificate must be signed by the SPIRE CA (authentication)
   - Once verified, the user specified in the connection string is trusted
   - This is appropriate because any workload that can present a valid SPIRE certificate is already authenticated

4. **User Role Selection**: The client application specifies which PostgreSQL user to connect as (`app_readonly`). Different SPIFFE-enabled workloads could connect as different users based on their needs.

---

## Troubleshooting

### Check SPIRE Components

```bash
# Check SPIRE server and agents
oc get pods -n zero-trust-workload-identity-manager

# Check ClusterSPIFFEID registrations
oc get clusterspiffeids

# Check if the workload received an identity
oc describe clusterspiffeid db-client-workload
```

### Check PostgreSQL

```bash
# Check PostgreSQL pod status
oc get pods -n edb

# Check PostgreSQL logs
oc logs -n edb edb-spiffe-postgres-0 -c postgres

# Connect to PostgreSQL directly (as admin)
oc exec -it edb-spiffe-postgres-0 -n edb -- psql -U postgres -d appdb

# Inside psql, check roles
\du

# Check pg_hba.conf being used
SHOW hba_file;
```

### Check Client Application

```bash
# Check client pod status
oc get pods -n spiffe-edb-demo

# Check client logs
oc logs -n spiffe-edb-demo deploy/db-client-app

# Check if SPIFFE socket is mounted
oc exec -n spiffe-edb-demo deploy/db-client-app -- ls -la /spiffe-workload-api/

# Check environment variables
oc exec -n spiffe-edb-demo deploy/db-client-app -- env | grep DB
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "certificate verify failed" | Check SPIRE CA secret is correctly mounted in PostgreSQL |
| "permission denied for table" | Working as expected for read-only role; use different role for writes |
| "no identity issued" | Check ClusterSPIFFEID selector matches pod labels |
| Pod won't start | Check SCC permissions for service account |

---

## Key Learnings

### What We Demonstrated

1. **Zero-Password Database Authentication**: The client application connects to PostgreSQL without any password, using only its SPIFFE certificate.

2. **Automatic Certificate Rotation**: SPIFFE certificates are short-lived (~1 hour) and automatically rotated by SPIRE.

3. **Workload Identity**: The database connection is tied to workload identity, not secrets or service accounts.

4. **Role-Based Authorization**: Different permissions can be granted based on which user the SPIFFE workload connects as.

### SPIFFE Certificate Challenge

SPIFFE X.509-SVIDs don't include a CN (Common Name) by default. The identity is stored in the SAN URI:
```
spiffe://trust-domain/ns/namespace/sa/serviceaccount
```

PostgreSQL's traditional `cert` authentication method expects a CN for user mapping. Our workaround:
- Use `clientcert=verify-ca` to verify the certificate is signed by SPIRE CA
- Use `trust` authentication method (since certificate proves identity)
- Specify the username in the connection string

### Production Considerations

For production, consider:

1. **Configure SPIRE to include CN**: Modify SPIRE server configuration to include meaningful CN in certificates
2. **Use external authorization**: Combine with OPA or other policy engine for fine-grained authorization
3. **Certificate rotation handling**: Ensure application handles certificate renewal gracefully
4. **Audit logging**: Enable PostgreSQL logging for connection events
5. **Network policies**: Restrict which pods can connect to the database

---

## Resources

- [SPIFFE Specification](https://spiffe.io/docs/latest/spiffe-about/spiffe-concepts/)
- [SPIRE Documentation](https://spiffe.io/docs/latest/spire-about/)
- [PostgreSQL SSL/TLS Documentation](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [PostgreSQL Certificate Authentication](https://www.postgresql.org/docs/current/auth-cert.html)
- [Red Hat Zero Trust Workload Identity Manager](https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/security_and_compliance/zero-trust-workload-identity-manager)
- [py-spiffe Library](https://github.com/spiffe/py-spiffe)
