# Deployment Guides: SPIFFE JWT-SVID Authentication with PostgreSQL

This folder contains deployment guides for the JWT-SVID to PostgreSQL demo.

## Available Guides

### 1. [Entra ID Setup Guide](./entra-id-setup.md) (Recommended)

**Status: Active and Tested**

Complete guide for deploying the demo with **Microsoft Entra ID** as the enterprise Identity Provider. This is the production-ready approach using Workload Identity Federation.

**Features:**
- Real enterprise IdP integration (Microsoft Entra ID)
- Workload Identity Federation (no secrets stored)
- Identity-based PostgreSQL authentication
- Full audit trail of access

### 2. Keycloak Setup Guide (Legacy)

**Status: Deprecated - For Reference Only**

The original guide below shows how to deploy with Keycloak as a mock enterprise IdP. This approach was experimental and has been superseded by the Entra ID integration.

---

# Legacy: Keycloak Deployment Guide

> **Note:** This guide is kept for reference. For production use, please use the [Entra ID Setup Guide](./entra-id-setup.md).

This guide provides step-by-step instructions to deploy the JWT-SVID Token Exchange demo on an OpenShift cluster using Keycloak.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Deploy SPIRE (Zero Trust Workload Identity Manager)](#step-1-deploy-spire-zero-trust-workload-identity-manager)
- [Step 2: Deploy Keycloak (Enterprise IdP)](#step-2-deploy-keycloak-enterprise-idp)
- [Step 3: Configure Keycloak](#step-3-configure-keycloak)
- [Step 4: Deploy the Demo Applications](#step-4-deploy-the-demo-applications)
- [Step 5: Test the Demo](#step-5-test-the-demo)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before starting, ensure you have:

1. **OpenShift cluster** (tested on ROSA/OCP 4.14+)
2. **`oc` CLI** with cluster-admin access
3. **`curl` and `jq`** installed locally

### Verify Cluster Access

```bash
oc whoami
oc get nodes
```

---

## Step 1: Deploy SPIRE (Zero Trust Workload Identity Manager)

If SPIRE is not already deployed, follow these steps:

### 1.1 Install the Operator

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

# Wait for operator to be ready
echo "Waiting for operator..."
sleep 60
oc get csv -n zero-trust-workload-identity-manager
```

### 1.2 Deploy SPIRE Components

```bash
# Get your cluster domain
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
echo "Cluster domain: $CLUSTER_DOMAIN"

# Deploy Zero Trust Workload Identity Manager
cat <<EOF | oc apply -f -
apiVersion: zerotrustworkloadidentitymanager.spiffe.io/v1alpha1
kind: ZeroTrustWorkloadIdentityManager
metadata:
  name: zerotrustworkloadidentitymanager
  namespace: zero-trust-workload-identity-manager
spec: {}
EOF

# Wait for deployment
sleep 30

# Deploy SPIRE Server
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: SpireServer
metadata:
  name: spire-server
  namespace: zero-trust-workload-identity-manager
spec:
  trustDomain: apps.$CLUSTER_DOMAIN
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
  trustDomain: apps.$CLUSTER_DOMAIN
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
  trustDomain: apps.$CLUSTER_DOMAIN
EOF
```

### 1.3 Create Route for OIDC Discovery Provider

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

### 1.4 Verify SPIRE Deployment

```bash
# Check all pods are running
oc get pods -n zero-trust-workload-identity-manager

# Test OIDC Discovery Provider
OIDC_URL="https://oidc-discovery.$CLUSTER_DOMAIN"
curl -sk "$OIDC_URL/.well-known/openid-configuration" | jq .
```

---

## Step 2: Deploy Keycloak (Enterprise IdP)

Keycloak emulates an enterprise IdP like Microsoft Entra ID in this demo.

### 2.1 Install Keycloak Operator

```bash
# Create namespace
oc create namespace keycloak

# Create OperatorGroup
cat <<EOF | oc apply -f -
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: keycloak-operator-group
  namespace: keycloak
spec:
  targetNamespaces:
    - keycloak
EOF

# Subscribe to operator
cat <<EOF | oc apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhbk-operator
  namespace: keycloak
spec:
  channel: stable-v24
  name: rhbk-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# Wait for operator
echo "Waiting for Keycloak operator..."
sleep 60
oc get csv -n keycloak
```

### 2.2 Deploy PostgreSQL Database

```bash
# Create database secret
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-db-secret
  namespace: keycloak
type: Opaque
stringData:
  username: keycloak
  password: keycloak123
EOF

# Create service account with anyuid
oc create serviceaccount postgresql-sa -n keycloak
oc adm policy add-scc-to-user anyuid -z postgresql-sa -n keycloak

# Deploy PostgreSQL
cat <<EOF | oc apply -f -
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql-db
  namespace: keycloak
spec:
  serviceName: postgresql-db
  replicas: 1
  selector:
    matchLabels:
      app: postgresql-db
  template:
    metadata:
      labels:
        app: postgresql-db
    spec:
      serviceAccountName: postgresql-sa
      securityContext:
        fsGroup: 999
      containers:
        - name: postgresql
          image: postgres:15
          securityContext:
            runAsUser: 999
          env:
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: keycloak-db-secret
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-db-secret
                  key: password
            - name: POSTGRES_DB
              value: keycloak
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: postgres-data
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: postgresql-db
  namespace: keycloak
spec:
  selector:
    app: postgresql-db
  ports:
    - port: 5432
      targetPort: 5432
EOF

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
sleep 30
oc get pods -n keycloak
```

### 2.3 Deploy Keycloak Instance

```bash
# Deploy Keycloak with token-exchange feature enabled
cat <<EOF | oc apply -f -
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: keycloak
  namespace: keycloak
spec:
  instances: 1
  db:
    vendor: postgres
    host: postgresql-db
    usernameSecret:
      name: keycloak-db-secret
      key: username
    passwordSecret:
      name: keycloak-db-secret
      key: password
  http:
    httpEnabled: true
  hostname:
    strict: false
  proxy:
    headers: xforwarded
  additionalOptions:
    - name: features
      value: "token-exchange,admin-fine-grained-authz"
EOF

# Wait for Keycloak
echo "Waiting for Keycloak (this takes ~2 minutes)..."
sleep 120
oc get pods -n keycloak
```

### 2.4 Create Keycloak Route

```bash
cat <<EOF | oc apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: keycloak
  namespace: keycloak
spec:
  port:
    targetPort: http
  to:
    kind: Service
    name: keycloak-service
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF

# Get Keycloak URL and credentials
KEYCLOAK_URL="https://$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')"
ADMIN_USER=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)
ADMIN_PASS=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)

echo ""
echo "=== Keycloak Credentials ==="
echo "URL: $KEYCLOAK_URL"
echo "Username: $ADMIN_USER"
echo "Password: $ADMIN_PASS"
echo "==========================="
```

---

## Step 3: Configure Keycloak

Configure Keycloak to trust the SPIRE OIDC Discovery Provider.

### 3.1 Get Admin Token

```bash
KEYCLOAK_URL="https://$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')"
ADMIN_USER=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)
ADMIN_PASS=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)

TOKEN=$(curl -sk -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$ADMIN_USER" \
  -d "password=$ADMIN_PASS" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" | jq -r '.access_token')

echo "Token obtained: ${#TOKEN} characters"
```

### 3.2 Create spiffe-demo Realm

```bash
curl -sk -X POST "$KEYCLOAK_URL/admin/realms" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "realm": "spiffe-demo",
    "enabled": true
  }'

echo "Realm 'spiffe-demo' created"
```

### 3.3 Add SPIRE as Identity Provider

```bash
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
SPIRE_OIDC_URL="https://oidc-discovery.$CLUSTER_DOMAIN"

curl -sk -X POST "$KEYCLOAK_URL/admin/realms/spiffe-demo/identity-provider/instances" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "alias": "spire-oidc",
    "displayName": "SPIRE Workload Identity",
    "providerId": "oidc",
    "enabled": true,
    "trustEmail": true,
    "storeToken": true,
    "config": {
      "issuer": "'"$SPIRE_OIDC_URL"'",
      "jwksUrl": "'"$SPIRE_OIDC_URL/keys"'",
      "validateSignature": "true",
      "useJwksUrl": "true",
      "clientId": "spire-client",
      "clientSecret": "not-used",
      "syncMode": "IMPORT"
    }
  }'

echo "SPIRE OIDC Identity Provider added"
```

### 3.4 Create Clients

```bash
# Create spiffe-workload client (for token exchange)
curl -sk -X POST "$KEYCLOAK_URL/admin/realms/spiffe-demo/clients" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "spiffe-workload",
    "name": "SPIFFE Workload Client",
    "enabled": true,
    "publicClient": false,
    "directAccessGrantsEnabled": true,
    "serviceAccountsEnabled": true,
    "standardFlowEnabled": false,
    "secret": "spiffe-workload-secret"
  }'

# Create api-server client
curl -sk -X POST "$KEYCLOAK_URL/admin/realms/spiffe-demo/clients" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "api-server",
    "name": "API Server (OIDC Only)",
    "enabled": true,
    "publicClient": false,
    "directAccessGrantsEnabled": true,
    "serviceAccountsEnabled": true,
    "standardFlowEnabled": false,
    "secret": "api-server-secret"
  }'

echo "Clients created"
```

---

## Step 4: Deploy the Demo Applications

### 4.1 Create Namespace and SPIRE Registration

```bash
# Create namespace
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: spiffe-jwt-demo
  labels:
    app.kubernetes.io/part-of: spiffe-demo
EOF

# Register workload with SPIRE
cat <<EOF | oc apply -f -
apiVersion: spire.spiffe.io/v1alpha1
kind: ClusterSPIFFEID
metadata:
  name: jwt-exchange-client
spec:
  spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}/sa/{{ .PodSpec.ServiceAccountName }}"
  podSelector:
    matchLabels:
      spiffe.io/spiffe-id: "jwt-exchange-client"
  namespaceSelector:
    matchLabels:
      app.kubernetes.io/part-of: spiffe-demo
  ttl: "1h"
EOF
```

### 4.2 Deploy API Server

```bash
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
KEYCLOAK_URL="https://keycloak-keycloak.$CLUSTER_DOMAIN"

# Apply API Server resources
cd "/path/to/SPIFFE SVID JWT Authentication with PostgreSQL"
oc apply -f k8s/api-server.yaml

# Build API Server image
oc start-build api-server --from-dir=api-server -n spiffe-jwt-demo --follow

# Wait for deployment
oc rollout status deployment/api-server -n spiffe-jwt-demo --timeout=120s
```

### 4.3 Deploy JWT Exchange Client

```bash
# Apply Client App resources
oc apply -f k8s/client-app.yaml

# Build Client App image
oc start-build jwt-exchange-client --from-dir=client-app -n spiffe-jwt-demo --follow

# Wait for deployment
oc rollout status deployment/jwt-exchange-client -n spiffe-jwt-demo --timeout=120s
```

### 4.4 Get Application URLs

```bash
echo "=== Application URLs ==="
echo "Client App: https://$(oc get route jwt-exchange-client -n spiffe-jwt-demo -o jsonpath='{.spec.host}')"
echo "API Server: https://$(oc get route api-server -n spiffe-jwt-demo -o jsonpath='{.spec.host}')"
```

---

## Step 5: Test the Demo

### 5.1 Via Web UI

Open the Client App URL in your browser and use the interactive buttons to:
1. **Get JWT-SVID** - Fetches a JWT-SVID from SPIRE
2. **Exchange Token** - Exchanges JWT-SVID for OIDC token
3. **Call API** - Calls the OIDC-protected API
4. **Full Flow** - Executes all steps in sequence

### 5.2 Via Command Line

```bash
CLIENT_URL="https://$(oc get route jwt-exchange-client -n spiffe-jwt-demo -o jsonpath='{.spec.host}')"

# Test JWT-SVID fetch
echo "=== Step 1: Get JWT-SVID ==="
curl -sk "$CLIENT_URL/api/jwt-svid" | jq .

# Test token exchange
echo ""
echo "=== Step 2: Exchange Token ==="
curl -sk "$CLIENT_URL/api/exchange" | jq .

# Test full flow
echo ""
echo "=== Full Flow ==="
curl -sk "$CLIENT_URL/api/full-flow" | jq .
```

### Expected Output

```json
{
  "final_status": "success",
  "steps": [
    {
      "step": 1,
      "name": "Get JWT-SVID from SPIRE",
      "result": {
        "status": "success",
        "spiffe_id": "spiffe://apps.example.com/ns/spiffe-jwt-demo/sa/jwt-exchange-client"
      }
    },
    {
      "step": 2,
      "name": "Exchange JWT-SVID for OIDC Token",
      "result": {
        "status": "success",
        "method": "mock_token_exchange",
        "original_svid_validated": true
      }
    },
    {
      "step": 3,
      "name": "Call API with OIDC Token",
      "result": {
        "status": "success",
        "data": {
          "message": "You have successfully accessed the OIDC-protected API!"
        }
      }
    }
  ]
}
```

---

## Troubleshooting

### SPIRE Agent Not Running

```bash
# Check SPIRE pods
oc get pods -n zero-trust-workload-identity-manager

# Check SPIRE Agent logs
oc logs -n zero-trust-workload-identity-manager -l app=spire-agent
```

### JWT-SVID Fetch Fails

```bash
# Check if ClusterSPIFFEID is registered
oc get clusterspiffeids

# Check if pod has the correct labels
oc get pods -n spiffe-jwt-demo -l spiffe.io/spiffe-id=jwt-exchange-client

# Check if CSI driver is mounted
oc exec -n spiffe-jwt-demo deploy/jwt-exchange-client -- ls -la /spiffe-workload-api/
```

### Keycloak Not Responding

```bash
# Check Keycloak pods
oc get pods -n keycloak

# Check Keycloak logs
oc logs -n keycloak -l app=keycloak
```

### Token Exchange Fails

The demo uses mock token exchange. If you see "JWT-SVID validation failed":

```bash
# Verify SPIRE OIDC Discovery Provider is accessible
OIDC_URL="https://$(oc get route spire-oidc-discovery-provider -n zero-trust-workload-identity-manager -o jsonpath='{.spec.host}')"
curl -sk "$OIDC_URL/.well-known/openid-configuration" | jq .
curl -sk "$OIDC_URL/keys" | jq .
```

---

## Cleanup

To remove all deployed resources:

```bash
# Delete demo applications
oc delete namespace spiffe-jwt-demo

# Delete Keycloak (optional)
oc delete keycloak keycloak -n keycloak
oc delete namespace keycloak

# Delete SPIRE (optional - only if you want to remove it entirely)
# oc delete namespace zero-trust-workload-identity-manager
```
