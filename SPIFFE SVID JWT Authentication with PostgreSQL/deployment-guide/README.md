# Detailed Setup Guide: SPIFFE JWT-SVID to Entra ID to PostgreSQL

This guide provides a comprehensive, step-by-step walkthrough of the complete JWT-SVID demo setup, including all components, configurations, and explanations.

## Table of Contents

- [Overview](#overview)
- [Architecture Deep Dive](#architecture-deep-dive)
- [Part 1: SPIRE Setup (Zero Trust Workload Identity Manager)](#part-1-spire-setup-zero-trust-workload-identity-manager)
- [Part 2: Microsoft Entra ID Configuration](#part-2-microsoft-entra-id-configuration)
- [Part 3: PostgreSQL Deployment](#part-3-postgresql-deployment)
- [Part 4: Client Application Deployment](#part-4-client-application-deployment)
- [Part 5: Testing and Verification](#part-5-testing-and-verification)
- [Appendix: Component Deep Dive](#appendix-component-deep-dive)

---

## Overview

This demo demonstrates **Workload Identity Federation** - the ability for a SPIFFE-enabled workload to authenticate to enterprise systems (Microsoft Entra ID) without storing any secrets.

### What You'll Build

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE DEMO ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  OpenShift Cluster                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                                                                     │    │
│  │  ┌─────────────────┐      ┌─────────────────┐                      │    │
│  │  │  SPIRE Server   │      │  SPIRE OIDC     │◄──── Entra ID       │    │
│  │  │  + Agent        │      │  Discovery      │      fetches JWKS   │    │
│  │  └────────┬────────┘      │  Provider       │                      │    │
│  │           │               └────────┬────────┘                      │    │
│  │           │                        │                               │    │
│  │  ┌────────▼────────┐              │                               │    │
│  │  │  Client App     │──────────────┘                               │    │
│  │  │  (Flask/Python) │                                              │    │
│  │  │                 │────────────────────┐                         │    │
│  │  └────────┬────────┘                    │                         │    │
│  │           │                             ▼                         │    │
│  │           │                    ┌─────────────────┐                │    │
│  │           │                    │  PostgreSQL 18  │                │    │
│  │           └───────────────────►│  (Identity-     │                │    │
│  │                                │   based auth)   │                │    │
│  │                                └─────────────────┘                │    │
│  │                                                                     │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Azure Cloud                                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Microsoft Entra ID                                                 │    │
│  │  ┌─────────────────────────────────────────┐                       │    │
│  │  │  App Registration: spiffe-postgres-demo │                       │    │
│  │  │  ├─ Federated Identity Credential       │                       │    │
│  │  │  │  ├─ Issuer: SPIRE OIDC DP URL       │                       │    │
│  │  │  │  ├─ Subject: spiffe://...           │                       │    │
│  │  │  │  └─ Audience: {app-id}              │                       │    │
│  │  │  └─ Issues Access Tokens               │                       │    │
│  │  └─────────────────────────────────────────┘                       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **SPIRE Server** | Issues X.509 and JWT SVIDs to workloads | `zero-trust-workload-identity-manager` namespace |
| **SPIRE Agent** | Runs on each node, handles workload attestation | DaemonSet on all nodes |
| **SPIFFE CSI Driver** | Mounts the SPIFFE Workload API socket into pods | DaemonSet on all nodes |
| **SPIRE OIDC Discovery Provider** | Publishes JWT signing keys via OIDC endpoints | `zero-trust-workload-identity-manager` namespace |
| **Entra ID App Registration** | Trusts SPIRE JWT-SVIDs via federated credential | Azure cloud |
| **Client App** | SPIFFE-enabled app that exchanges JWT-SVID for Entra ID token | `oidc-postgres-demo` namespace |
| **PostgreSQL** | Database with identity-based access control | `oidc-postgres-demo` namespace |

---

## Architecture Deep Dive

### The Complete Authentication Flow

```
Step-by-step flow with timing:

┌──────────────┐                                           
│  1. Pod      │  t=0ms                                    
│  Starts      │───────┐                                   
└──────────────┘       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  2. SPIRE Agent Attests Workload (t=0-100ms)             │
│                                                          │
│  • SPIRE Agent detects new pod via CSI driver            │
│  • Verifies pod against ClusterSPIFFEID selector         │
│  • Creates SPIFFE ID based on template:                  │
│    spiffe://{trust-domain}/ns/{namespace}/sa/{sa-name}   │
└──────────────────────────────────────────────────────────┘
                       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  3. App Requests JWT-SVID (t=100-200ms)                  │
│                                                          │
│  client = WorkloadApiClient(socket_path)                 │
│  jwt_svid = client.fetch_jwt_svid(audience={AZURE_ID})   │
│                                                          │
│  JWT-SVID contains:                                      │
│  {                                                       │
│    "iss": "https://oidc-discovery.apps...",             │
│    "sub": "spiffe://trust-domain/ns/.../sa/...",        │
│    "aud": ["azure-client-id"],                          │
│    "exp": 1234567890,                                    │
│    "iat": 1234567590                                     │
│  }                                                       │
└──────────────────────────────────────────────────────────┘
                       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  4. App Sends JWT-SVID to Entra ID (t=200-400ms)         │
│                                                          │
│  POST https://login.microsoftonline.com/{tenant}/...     │
│  Body:                                                   │
│    client_id: {azure-client-id}                         │
│    client_assertion: {jwt-svid}                         │
│    client_assertion_type: jwt-bearer                    │
│    grant_type: client_credentials                       │
│    scope: {azure-client-id}/.default                    │
└──────────────────────────────────────────────────────────┘
                       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  5. Entra ID Validates JWT-SVID (t=400-800ms)            │
│                                                          │
│  a) Looks up federated credential for client_id         │
│  b) Extracts 'iss' from JWT-SVID                        │
│  c) Fetches JWKS from {issuer}/keys                     │
│  d) Finds key by 'kid' in JWT header                    │
│  e) Verifies JWT signature                              │
│  f) Validates claims (iss, sub, aud, exp)               │
│  g) If valid: issues Entra ID access token              │
└──────────────────────────────────────────────────────────┘
                       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  6. App Receives Entra ID Token (t=800-900ms)            │
│                                                          │
│  {                                                       │
│    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",       │
│    "token_type": "Bearer",                              │
│    "expires_in": 3599                                   │
│  }                                                       │
└──────────────────────────────────────────────────────────┘
                       │                                   
                       ▼                                   
┌──────────────────────────────────────────────────────────┐
│  7. App Validates Token & Connects to PostgreSQL         │
│     (t=900-1100ms)                                       │
│                                                          │
│  a) Validates Entra ID token using Microsoft JWKS       │
│  b) Extracts identity (appid, oid)                      │
│  c) Creates PostgreSQL user from identity hash          │
│  d) Connects to PostgreSQL with identity-based creds    │
│  e) Executes queries                                    │
└──────────────────────────────────────────────────────────┘
```

---

## Part 1: SPIRE Setup (Zero Trust Workload Identity Manager)

### 1.1 Prerequisites

```bash
# Verify OpenShift access
oc whoami
# Should show: cluster-admin (or equivalent)

# Get cluster domain
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
echo "Cluster domain: $CLUSTER_DOMAIN"
```

### 1.2 Install the Operator

```bash
# Create namespace
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: zero-trust-workload-identity-manager
EOF

# Create OperatorGroup
cat <<EOF | oc apply -f -
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: zero-trust-og
  namespace: zero-trust-workload-identity-manager
spec:
  targetNamespaces:
    - zero-trust-workload-identity-manager
EOF

# Subscribe to the operator
cat <<EOF | oc apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: zero-trust-workload-identity-manager
  namespace: zero-trust-workload-identity-manager
spec:
  channel: stable
  name: zero-trust-workload-identity-manager
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# Wait for operator
echo "Waiting for operator to install..."
sleep 60
oc get csv -n zero-trust-workload-identity-manager | grep -i zero
```

### 1.3 Deploy SPIRE Components

```bash
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
TRUST_DOMAIN="apps.${CLUSTER_DOMAIN}"
echo "Trust Domain: $TRUST_DOMAIN"

# Deploy Zero Trust Workload Identity Manager
cat <<EOF | oc apply -f -
apiVersion: zerotrustworkloadidentitymanager.spiffe.io/v1alpha1
kind: ZeroTrustWorkloadIdentityManager
metadata:
  name: zerotrustworkloadidentitymanager
  namespace: zero-trust-workload-identity-manager
spec: {}
EOF

sleep 30

# Deploy SPIRE Server
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: SpireServer
metadata:
  name: spire-server
  namespace: zero-trust-workload-identity-manager
spec:
  trustDomain: $TRUST_DOMAIN
  nodeAttestors:
    - psat
  caKeyType: ec-p256
  caTTL: 24h
  defaultX509SvidTtl: 1h
  defaultJwtSvidTtl: 5m
EOF

# Deploy SPIRE Agent
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: SpireAgent
metadata:
  name: spire-agent
  namespace: zero-trust-workload-identity-manager
spec:
  trustDomain: $TRUST_DOMAIN
EOF

# Deploy SPIFFE CSI Driver
cat <<EOF | oc apply -f -
apiVersion: spiffe.spiffe.io/v1alpha1
kind: SpiffeCsiDriver
metadata:
  name: spiffe-csi-driver
  namespace: zero-trust-workload-identity-manager
spec: {}
EOF

# Deploy SPIRE OIDC Discovery Provider
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: SpireOidcDiscoveryProvider
metadata:
  name: spire-spiffe-oidc-discovery-provider
  namespace: zero-trust-workload-identity-manager
spec:
  trustDomain: $TRUST_DOMAIN
EOF
```

### 1.4 Create Route for OIDC Discovery Provider

```bash
cat <<EOF | oc apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: spire-oidc-discovery-provider
  namespace: zero-trust-workload-identity-manager
spec:
  host: oidc-discovery.$CLUSTER_DOMAIN
  to:
    kind: Service
    name: spire-spiffe-oidc-discovery-provider
  port:
    targetPort: https
  tls:
    termination: reencrypt
    insecureEdgeTerminationPolicy: Redirect
EOF
```

### 1.5 Verify SPIRE Installation

```bash
echo "=== SPIRE Pods ==="
oc get pods -n zero-trust-workload-identity-manager

echo ""
echo "=== OIDC Discovery Provider ==="
OIDC_URL="https://oidc-discovery.$CLUSTER_DOMAIN"
echo "URL: $OIDC_URL"

echo ""
echo "=== OIDC Configuration ==="
curl -sk "$OIDC_URL/.well-known/openid-configuration" | jq .

echo ""
echo "=== JWKS Keys ==="
curl -sk "$OIDC_URL/keys" | jq '.keys | length'
echo "keys available"
```

---

## Part 2: Microsoft Entra ID Configuration

### 2.1 Login to Azure

```bash
# Interactive login (opens browser)
az login

# Verify login
az account show --query "{name:name, subscriptionId:id, tenantId:tenantId}" -o table
```

### 2.2 Create App Registration

```bash
# Create the app
az ad app create --display-name "spiffe-postgres-demo"

# Get the Application (Client) ID
APP_ID=$(az ad app list --display-name "spiffe-postgres-demo" --query "[0].appId" -o tsv)
echo "Application ID: $APP_ID"

# Get the Object ID (needed for some operations)
OBJECT_ID=$(az ad app list --display-name "spiffe-postgres-demo" --query "[0].id" -o tsv)
echo "Object ID: $OBJECT_ID"

# Create Service Principal
az ad sp create --id $APP_ID

# Get Tenant ID
TENANT_ID=$(az account show --query "tenantId" -o tsv)
echo "Tenant ID: $TENANT_ID"

# Store these values
cat <<EOF
====================================
SAVE THESE VALUES:
====================================
APP_ID=$APP_ID
OBJECT_ID=$OBJECT_ID
TENANT_ID=$TENANT_ID
====================================
EOF
```

### 2.3 Create Federated Identity Credential

This is the key configuration that tells Entra ID to trust JWT-SVIDs from SPIRE.

```bash
# Get SPIRE OIDC Discovery Provider URL
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
SPIRE_OIDC_URL="https://oidc-discovery.$CLUSTER_DOMAIN"

# Get the SPIFFE ID that will be used (must match ClusterSPIFFEID)
TRUST_DOMAIN="apps.$CLUSTER_DOMAIN"
SPIFFE_ID="spiffe://$TRUST_DOMAIN/ns/oidc-postgres-demo/sa/spiffe-client"

echo "Creating Federated Identity Credential:"
echo "  Issuer: $SPIRE_OIDC_URL"
echo "  Subject: $SPIFFE_ID"
echo "  Audience: $APP_ID"

# Create the federated credential
az ad app federated-credential create \
  --id $APP_ID \
  --parameters "{
    \"name\": \"spiffe-workload-federation\",
    \"issuer\": \"$SPIRE_OIDC_URL\",
    \"subject\": \"$SPIFFE_ID\",
    \"audiences\": [\"$APP_ID\"]
  }"

# Verify
az ad app federated-credential list --id $APP_ID -o table
```

### 2.4 Understanding the Federated Credential

The federated credential creates a trust relationship:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FEDERATED IDENTITY CREDENTIAL                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  When Entra ID receives a JWT-SVID, it:                                     │
│                                                                              │
│  1. Extracts the 'iss' (issuer) claim from the JWT                         │
│     → Must match: https://oidc-discovery.apps.example.com                   │
│                                                                              │
│  2. Extracts the 'sub' (subject) claim from the JWT                        │
│     → Must match: spiffe://apps.example.com/ns/oidc-postgres-demo/...      │
│                                                                              │
│  3. Extracts the 'aud' (audience) claim from the JWT                       │
│     → Must match: f63d6f2e-f780-4568-a69a-93a07cd8c5db (App ID)            │
│                                                                              │
│  4. Fetches JWKS from {issuer}/keys                                        │
│     → https://oidc-discovery.apps.example.com/keys                          │
│                                                                              │
│  5. Finds the key with matching 'kid' (key ID)                             │
│                                                                              │
│  6. Verifies the JWT signature using the public key                        │
│                                                                              │
│  7. If ALL validations pass → Issues Entra ID access token                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: PostgreSQL Deployment

### 3.1 Create Namespace and Resources

```bash
# Create namespace
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: oidc-postgres-demo
EOF

# Create credentials secret
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: postgresql-credentials
  namespace: oidc-postgres-demo
type: Opaque
stringData:
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres-admin-password
  POSTGRES_DB: demo
EOF

# Create init script ConfigMap
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgresql-init
  namespace: oidc-postgres-demo
data:
  init.sql: |
    -- Create sample table
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        description TEXT,
        price DECIMAL(10,2),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Insert sample data
    INSERT INTO products (name, description, price) VALUES
        ('Widget A', 'A high-quality widget', 29.99),
        ('Gadget B', 'Latest gadget with features', 149.99),
        ('Tool C', 'Professional-grade tool', 79.99),
        ('Device D', 'Smart IoT device', 199.99),
        ('Component E', 'Essential component', 9.99);
    
    -- Create access log table
    CREATE TABLE IF NOT EXISTS access_log (
        id SERIAL PRIMARY KEY,
        subject VARCHAR(255) NOT NULL,
        issuer VARCHAR(255) NOT NULL,
        action VARCHAR(50) NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Grant permissions for dynamic OIDC users
    GRANT SELECT ON products TO PUBLIC;
    GRANT ALL ON access_log TO PUBLIC;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
EOF
```

### 3.2 Deploy PostgreSQL

```bash
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Service
metadata:
  name: postgresql
  namespace: oidc-postgres-demo
spec:
  ports:
    - port: 5432
      targetPort: 5432
  selector:
    app: postgresql
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: oidc-postgres-demo
spec:
  serviceName: postgresql
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
        - name: postgresql
          image: postgres:18
          ports:
            - containerPort: 5432
          env:
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: postgresql-credentials
                  key: POSTGRES_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgresql-credentials
                  key: POSTGRES_PASSWORD
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef:
                  name: postgresql-credentials
                  key: POSTGRES_DB
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: postgresql-data
              mountPath: /var/lib/postgresql/data
            - name: init-scripts
              mountPath: /docker-entrypoint-initdb.d
      volumes:
        - name: init-scripts
          configMap:
            name: postgresql-init
            items:
              - key: init.sql
                path: init.sql
  volumeClaimTemplates:
    - metadata:
        name: postgresql-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 1Gi
EOF

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
sleep 30
oc get pods -n oidc-postgres-demo -l app=postgresql
```

---

## Part 4: Client Application Deployment

### 4.1 Create ClusterSPIFFEID

This registers the workload with SPIRE so it can receive SVIDs.

```bash
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: ClusterSPIFFEID
metadata:
  name: oidc-postgres-client
spec:
  spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}/sa/{{ .PodSpec.ServiceAccountName }}"
  namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: oidc-postgres-demo
  podSelector:
    matchLabels:
      app: client-app
  workloadSelectorTemplates:
    - "k8s:ns:{{ .PodMeta.Namespace }}"
    - "k8s:sa:{{ .PodSpec.ServiceAccountName }}"
EOF
```

### 4.2 Create Service Account and Resources

```bash
# Get your Azure values
APP_ID="YOUR_AZURE_APP_ID"     # From Part 2
TENANT_ID="YOUR_AZURE_TENANT_ID"  # From Part 2

# Create ServiceAccount
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spiffe-client
  namespace: oidc-postgres-demo
EOF

# Create ConfigMap with Azure credentials
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: client-app-config
  namespace: oidc-postgres-demo
data:
  AZURE_TENANT_ID: "$TENANT_ID"
  AZURE_CLIENT_ID: "$APP_ID"
  DB_HOST: "postgresql.oidc-postgres-demo.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "demo"
  DB_ADMIN_USER: "postgres"
  DB_ADMIN_PASSWORD: "postgres-admin-password"
EOF

# Create ImageStream and BuildConfig
cat <<EOF | oc apply -f -
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: client-app
  namespace: oidc-postgres-demo
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: client-app
  namespace: oidc-postgres-demo
spec:
  source:
    type: Binary
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile
  output:
    to:
      kind: ImageStreamTag
      name: client-app:latest
EOF
```

### 4.3 Build and Deploy Client App

```bash
# Navigate to client-app directory
cd /path/to/SPIFFE-PostgreSQL/oidc-postgres-demo/client-app

# Start the build
oc start-build client-app --from-dir=. -n oidc-postgres-demo --follow

# Deploy the application
cat <<EOF | oc apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: client-app
  namespace: oidc-postgres-demo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: client-app
  template:
    metadata:
      labels:
        app: client-app
    spec:
      serviceAccountName: spiffe-client
      containers:
        - name: client-app
          image: image-registry.openshift-image-registry.svc:5000/oidc-postgres-demo/client-app:latest
          ports:
            - containerPort: 8080
          env:
            - name: SPIFFE_ENDPOINT_SOCKET
              value: "unix:///spiffe-workload-api/spire-agent.sock"
          envFrom:
            - configMapRef:
                name: client-app-config
          volumeMounts:
            - name: spiffe-workload-api
              mountPath: /spiffe-workload-api
              readOnly: true
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
      volumes:
        - name: spiffe-workload-api
          csi:
            driver: csi.spiffe.io
            readOnly: true
---
apiVersion: v1
kind: Service
metadata:
  name: client-app
  namespace: oidc-postgres-demo
spec:
  ports:
    - port: 8080
      targetPort: 8080
  selector:
    app: client-app
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: client-app
  namespace: oidc-postgres-demo
spec:
  to:
    kind: Service
    name: client-app
  port:
    targetPort: 8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF
```

---

## Part 5: Testing and Verification

### 5.1 Get Application URL

```bash
CLIENT_URL="https://$(oc get route client-app -n oidc-postgres-demo -o jsonpath='{.spec.host}')"
echo "Client App URL: $CLIENT_URL"
```

### 5.2 Test Each Step

```bash
# Test 1: Health check
echo "=== Health Check ==="
curl -sk "$CLIENT_URL/health" | jq .

# Test 2: Get JWT-SVID
echo ""
echo "=== Get JWT-SVID from SPIRE ==="
curl -sk "$CLIENT_URL/api/jwt-svid" | jq '{status, spiffe_id, audience}'

# Test 3: Exchange for Entra ID token
echo ""
echo "=== Exchange JWT-SVID for Entra ID Token ==="
curl -sk "$CLIENT_URL/api/exchange-token" | jq '{status, token_type, expires_in}'

# Test 4: Query database
echo ""
echo "=== Query Database with Entra ID Identity ==="
curl -sk "$CLIENT_URL/api/query-database" | jq '{status, product_count, identity}'

# Test 5: Full demo
echo ""
echo "=== Full Demo ==="
curl -sk "$CLIENT_URL/api/full-demo" | jq .
```

### 5.3 Expected Output

```json
{
  "overall_status": "success",
  "steps": [
    {
      "step": "1-2",
      "name": "Get JWT-SVID from SPIRE",
      "result": {
        "status": "success",
        "spiffe_id": "spiffe://apps.rosa.example.com/ns/oidc-postgres-demo/sa/spiffe-client",
        "audience": "f63d6f2e-f780-4568-a69a-93a07cd8c5db"
      }
    },
    {
      "step": "3-5",
      "name": "Exchange JWT-SVID for Entra ID token",
      "result": {
        "status": "success",
        "token_type": "Bearer",
        "expires_in": 3599
      }
    },
    {
      "step": "6-8",
      "name": "Connect to PostgreSQL with Entra ID identity",
      "result": {
        "status": "success",
        "authentication_flow": "SPIFFE → Entra ID → PostgreSQL (Identity Federation)",
        "identity": {
          "app_id": "f63d6f2e-f780-4568-a69a-93a07cd8c5db",
          "db_username": "oidc_fa02897b6af811cc"
        },
        "product_count": 5
      }
    }
  ]
}
```

### 5.4 Verify Access Logs

```bash
# Check PostgreSQL access logs
oc exec -n oidc-postgres-demo postgresql-0 -- \
  psql -U postgres -d demo -c "SELECT * FROM access_log ORDER BY timestamp DESC LIMIT 5;"

# Check dynamically created users
oc exec -n oidc-postgres-demo postgresql-0 -- \
  psql -U postgres -d demo -c "SELECT rolname FROM pg_roles WHERE rolname LIKE 'oidc_%';"
```

---

## Appendix: Component Deep Dive

### A.1 SPIFFE Workload API

The SPIFFE Workload API is accessed via a Unix domain socket mounted by the CSI driver:

```python
from spiffe import WorkloadApiClient

# Connect to the Workload API
client = WorkloadApiClient("unix:///spiffe-workload-api/spire-agent.sock")

# Fetch JWT-SVID with specific audience
jwt_svid = client.fetch_jwt_svid(audience={"azure-client-id"})

# Access token and identity
print(f"SPIFFE ID: {jwt_svid.spiffe_id}")
print(f"Token: {jwt_svid.token}")
```

### A.2 JWT-SVID Structure

```json
{
  "header": {
    "alg": "RS256",
    "kid": "JZ4puCaboJ82Mn65L1CSPQPi7DLnJNN3",
    "typ": "JWT"
  },
  "payload": {
    "aud": ["f63d6f2e-f780-4568-a69a-93a07cd8c5db"],
    "exp": 1776063373,
    "iat": 1776063073,
    "iss": "https://oidc-discovery.apps.rosa.example.com",
    "sub": "spiffe://apps.rosa.example.com/ns/oidc-postgres-demo/sa/spiffe-client"
  }
}
```

### A.3 Entra ID Token Exchange

```python
import requests

response = requests.post(
    f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
    data={
        "client_id": AZURE_CLIENT_ID,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": jwt_svid.token,  # The JWT-SVID
        "grant_type": "client_credentials",
        "scope": f"{AZURE_CLIENT_ID}/.default"
    }
)

entra_token = response.json()["access_token"]
```

### A.4 Entra ID Token Structure

```json
{
  "aud": "f63d6f2e-f780-4568-a69a-93a07cd8c5db",
  "iss": "https://sts.windows.net/64dc69e4-d083-49fc-9569-ebece1dd1408/",
  "iat": 1776060877,
  "exp": 1776064777,
  "appid": "f63d6f2e-f780-4568-a69a-93a07cd8c5db",
  "oid": "0cae8089-adea-4bd4-86f4-be530f91ab59",
  "sub": "0cae8089-adea-4bd4-86f4-be530f91ab59",
  "tid": "64dc69e4-d083-49fc-9569-ebece1dd1408"
}
```

---

## Troubleshooting

### JWT-SVID Fetch Fails

```bash
# Check ClusterSPIFFEID
oc get clusterspiffeids oidc-postgres-client -o yaml

# Check SPIRE Agent logs
oc logs -n zero-trust-workload-identity-manager -l app.kubernetes.io/name=agent --tail=50

# Verify CSI driver mount
oc exec -n oidc-postgres-demo deploy/client-app -- ls -la /spiffe-workload-api/
```

### Entra ID Token Exchange Fails

```bash
# Check federated credential
az ad app federated-credential list --id $APP_ID

# Verify OIDC Discovery Provider is accessible
curl -sk "https://oidc-discovery.$CLUSTER_DOMAIN/.well-known/openid-configuration"
curl -sk "https://oidc-discovery.$CLUSTER_DOMAIN/keys"

# Check client app logs
oc logs -n oidc-postgres-demo deploy/client-app --tail=50
```

### PostgreSQL Connection Fails

```bash
# Check PostgreSQL is running
oc get pods -n oidc-postgres-demo -l app=postgresql

# Test direct connection
oc exec -n oidc-postgres-demo postgresql-0 -- psql -U postgres -c "SELECT 1;"
```
