# SPIFFE JWT-SVID Authentication with PostgreSQL via Entra ID

This demo shows how a **SPIFFE-enabled workload** can authenticate to **PostgreSQL** by leveraging **Workload Identity Federation** with **Microsoft Entra ID**.

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [The Solution: Workload Identity Federation](#the-solution-workload-identity-federation)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Live Demo Results](#live-demo-results)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
- [References](#references)

---

## Overview

This demo demonstrates how **SPIFFE-enabled workloads** running on OpenShift can authenticate to PostgreSQL by:
1. Obtaining a **JWT-SVID** from SPIRE
2. Exchanging it for an **Entra ID access token** via Workload Identity Federation
3. Validating the Entra ID token and extracting identity claims
4. Connecting to **PostgreSQL** using identity-based authentication

---

## The Problem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           THE CHALLENGE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SPIFFE World                              Enterprise World                 │
│   ┌─────────────────┐                       ┌─────────────────┐             │
│   │                 │                       │                 │             │
│   │   App A         │     ───────?──────►   │   PostgreSQL    │             │
│   │  (SPIFFE        │     JWT-SVID          │  (Enterprise    │             │
│   │   enabled)      │     not accepted!     │   managed)      │             │
│   │                 │                       │                 │             │
│   └─────────────────┘                       └─────────────────┘             │
│                                                                              │
│   App A has a JWT-SVID from SPIRE                                           │
│   Enterprise requires Entra ID for all authentication                       │
│   How do they communicate?                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Challenges:**
1. PostgreSQL doesn't understand JWT-SVIDs directly
2. The enterprise security team requires all access to go through Entra ID
3. Need a way to bridge SPIFFE identity to Entra ID identity

---

## The Solution: Workload Identity Federation

**Workload Identity Federation** allows SPIFFE/SPIRE to exchange JWT-SVIDs for Entra ID tokens. The Entra ID token is then validated, and the identity is used to authorize database access.

### Key Components

| Component | Role |
|-----------|------|
| **SPIRE Server** | Issues JWT-SVIDs to workloads |
| **SPIRE OIDC Discovery Provider** | Publishes JWKS for JWT-SVID validation |
| **Microsoft Entra ID** | Enterprise IdP that validates JWT-SVIDs and issues access tokens |
| **PostgreSQL** | Database with identity-based access control |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│              SPIFFE → ENTRA ID → POSTGRESQL (IDENTITY FEDERATION)                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────┐     ┌─────────────────────────────┐     ┌──────────────┐             │
│  │              │     │        SPIRE Server         │     │              │             │
│  │   SPIFFE     │     │  ┌───────────────────────┐  │     │   Entra ID   │             │
│  │   Client     │     │  │  SPIRE OIDC Discovery │  │     │  (Azure AD)  │             │
│  │              │     │  │  Provider             │  │     │              │             │
│  │              │     │  │  (/.well-known, /keys)│  │     │              │             │
│  └──────┬───────┘     │  └───────────┬───────────┘  │     └──────┬───────┘             │
│         │             └──────────────┼──────────────┘            │                     │
│         │                            │                           │                     │
│         │                            │                           │  ┌───────────────┐  │
│         │                            │                           │  │  PostgreSQL   │  │
│         │                            │                           │  │  (OpenShift)  │  │
│         │                            │                           │  │               │  │
│         │                            │                           │  │  Identity-    │  │
│         │                            │                           │  │  based users  │  │
│         │                            │                           │  └───────┬───────┘  │
│         │                            │                           │          │          │
│    1.   │ Request JWT-SVID           │                           │          │          │
│         │───────────────────────────►│                           │          │          │
│         │                            │                           │          │          │
│    2.   │◄───────────────────────────│ Issue JWT-SVID            │          │          │
│         │       (signed JWT)         │                           │          │          │
│         │                            │                           │          │          │
│    3.   │ Exchange JWT-SVID for Entra ID token                   │          │          │
│         │───────────────────────────────────────────────────────►│          │          │
│         │            (Workload Identity Federation)              │          │          │
│         │                            │                           │          │          │
│    4.   │                            │◄──────────────────────────│          │          │
│         │                            │  Fetch JWKS to validate   │          │          │
│         │                            │  JWT-SVID signature       │          │          │
│         │                            │──────────────────────────►│          │          │
│         │                            │                           │          │          │
│    5.   │◄───────────────────────────────────────────────────────│          │          │
│         │              Entra ID Access Token                     │          │          │
│         │                            │                           │          │          │
│    6.   │ Validate token, extract identity                       │          │          │
│         │ Create PostgreSQL user from identity hash              │          │          │
│         │────────────────────────────────────────────────────────────────────►         │
│         │                            │                           │          │          │
│    7.   │◄────────────────────────────────────────────────────────────────────         │
│         │                       Query results                    │          │          │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Flow Summary

| Step | From | To | Description |
|------|------|-----|-------------|
| 1-2 | Client | SPIRE Server | Client requests and receives JWT-SVID |
| 3 | Client | Entra ID | Client exchanges JWT-SVID for Entra ID token |
| 4 | Entra ID | SPIRE OIDC DP | Entra ID fetches JWKS to validate JWT-SVID |
| 5 | Entra ID | Client | Entra ID issues access token |
| 6 | Client | PostgreSQL | Client validates token, extracts identity, connects with identity-based user |
| 7 | PostgreSQL | Client | Connection established, queries executed |

---

## How It Works

### Step 1-2: Client Obtains JWT-SVID from SPIRE

```python
from spiffe import WorkloadApiClient

client = WorkloadApiClient("unix:///spiffe-workload-api/spire-agent.sock")
jwt_svid = client.fetch_jwt_svid(audience={AZURE_CLIENT_ID})

# JWT-SVID payload:
# {
#   "iss": "https://oidc-discovery.apps.example.com",
#   "sub": "spiffe://trust-domain/ns/oidc-postgres-demo/sa/spiffe-client",
#   "aud": "{azure-client-id}",
#   "exp": 1234567890
# }
```

### Step 3-5: Exchange JWT-SVID for Entra ID Token

```python
import requests

response = requests.post(
    f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
    data={
        "client_id": AZURE_CLIENT_ID,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": jwt_svid.token,
        "grant_type": "client_credentials",
        "scope": f"{AZURE_CLIENT_ID}/.default"
    }
)

entra_token = response.json()["access_token"]
```

### Step 6: Validate Token and Extract Identity

```python
import jwt
import hashlib

# Validate and decode the Entra ID token
jwks_client = jwt.PyJWKClient(f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys")
signing_key = jwks_client.get_signing_key_from_jwt(entra_token)
claims = jwt.decode(entra_token, signing_key.key, algorithms=["RS256"], audience=AZURE_CLIENT_ID)

# Extract identity
app_id = claims.get('appid')
object_id = claims.get('oid')
issuer = claims.get('iss')

# Create deterministic PostgreSQL username from identity
identity_hash = hashlib.sha256(app_id.encode()).hexdigest()[:16]
db_username = f"oidc_{identity_hash}"
```

### Step 7: Connect to PostgreSQL with Identity-Based User

```python
import psycopg2

# Dynamically create user if not exists (done by admin connection)
# Then connect as the identity-based user

conn = psycopg2.connect(
    host="postgresql.oidc-postgres-demo.svc",
    port=5432,
    database="demo",
    user=db_username,  # e.g., "oidc_fa02897b6af811cc"
    password=derived_password,
    sslmode="prefer"
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM products")
results = cursor.fetchall()
```

---

## Live Demo Results

The demo was successfully deployed and tested. Here are the actual results:

### Full Demo Output

```json
{
  "overall_status": "success",
  "steps": [
    {
      "step": "1-2",
      "name": "Get JWT-SVID from SPIRE",
      "result": {
        "status": "success",
        "spiffe_id": "spiffe://apps.rosa.rosa-v99n5.8ie9.p3.openshiftapps.com/ns/oidc-postgres-demo/sa/spiffe-client",
        "audience": "f63d6f2e-f780-4568-a69a-93a07cd8c5db"
      }
    },
    {
      "step": "3-5",
      "name": "Exchange JWT-SVID for Entra ID token",
      "result": {
        "status": "success",
        "token_type": "Bearer",
        "expires_in": 3598
      }
    },
    {
      "step": "6-8",
      "name": "Connect to PostgreSQL with Entra ID identity",
      "result": {
        "status": "success",
        "message": "Successfully authenticated with Entra ID identity!",
        "authentication_flow": "SPIFFE → Entra ID → PostgreSQL (Identity Federation)",
        "identity": {
          "app_id": "f63d6f2e-f780-4568-a69a-93a07cd8c5db",
          "object_id": "0cae8089-adea-4bd4-86f4-be530f91ab59",
          "issuer": "https://sts.windows.net/64dc69e4-d083-49fc-9569-ebece1dd1408/",
          "db_username": "oidc_fa02897b6af811cc"
        },
        "product_count": 5
      }
    }
  ]
}
```

### PostgreSQL Access Log

The access is tracked in the `access_log` table:

| id | subject | issuer | action | timestamp |
|----|---------|--------|--------|-----------|
| 1 | appid:f63d6f2e-f780-4568-a69a-93a07cd8c5db | https://sts.windows.net/64dc69e4-d083-49fc-9569-ebece1dd1408/ | SELECT products | 2026-04-13 06:38:45 |

### PostgreSQL Users Created

Identity-based users are dynamically created:

| rolname | rolcanlogin |
|---------|-------------|
| oidc_fa02897b6af811cc | true |

---

## Prerequisites

### Azure Requirements

1. **Azure Subscription** with permissions to create App Registrations in Entra ID

2. **Entra ID App Registration** with:
   - Federated Identity Credential configured to trust your SPIRE OIDC Discovery Provider
   - Issuer: `https://your-spire-oidc-discovery-provider-url`
   - Subject: `spiffe://your-trust-domain/ns/oidc-postgres-demo/sa/spiffe-client`
   - Audience: The App Registration's Client ID

### OpenShift/Kubernetes Requirements

1. **SPIRE** deployed via Zero Trust Workload Identity Manager
2. **SPIRE OIDC Discovery Provider** accessible from the internet (for Entra ID to fetch JWKS)
3. **PostgreSQL** database

---

## Deployment

### 1. Configure Entra ID

```bash
# Login to Azure
az login

# Create App Registration
az ad app create --display-name "spiffe-postgres-demo"

# Get Application ID
APP_ID=$(az ad app list --display-name "spiffe-postgres-demo" --query "[0].appId" -o tsv)
echo "Application ID: $APP_ID"

# Create Service Principal
az ad sp create --id $APP_ID

# Get your SPIRE OIDC Discovery Provider URL
SPIRE_OIDC_URL="https://oidc-discovery.apps.your-cluster.example.com"

# Create Federated Identity Credential
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "spiffe-federation",
    "issuer": "'$SPIRE_OIDC_URL'",
    "subject": "spiffe://your-trust-domain/ns/oidc-postgres-demo/sa/spiffe-client",
    "audiences": ["'$APP_ID'"]
  }'
```

### 2. Deploy the Demo on OpenShift

```bash
# Create namespace
oc apply -f ../oidc-postgres-demo/k8s/namespace.yaml

# Deploy PostgreSQL
oc apply -f ../oidc-postgres-demo/k8s/postgresql.yaml

# Create ClusterSPIFFEID for workload registration
oc apply -f ../oidc-postgres-demo/k8s/clusterspiffeid.yaml

# Update ConfigMaps with your Azure credentials
# Edit client-app.yaml to set AZURE_TENANT_ID and AZURE_CLIENT_ID

# Build and deploy client app
cd ../oidc-postgres-demo/client-app
oc start-build client-app --from-dir=. -n oidc-postgres-demo --follow

# Deploy the client app
oc apply -f ../k8s/client-app.yaml
```

### 3. Test the Demo

Access the demo UI:
```
https://client-app-oidc-postgres-demo.apps.your-cluster.example.com
```

Or via curl:
```bash
curl -sk https://client-app-oidc-postgres-demo.apps.your-cluster.example.com/api/full-demo | jq .
```

---

## Folder Structure

```
oidc-postgres-demo/
├── k8s/
│   ├── namespace.yaml           # Namespace definition
│   ├── clusterspiffeid.yaml     # SPIRE workload registration
│   ├── postgresql.yaml          # PostgreSQL deployment
│   └── client-app.yaml          # SPIFFE client deployment
└── client-app/
    ├── app.py                   # Flask app with SPIFFE + Entra ID + PostgreSQL
    ├── requirements.txt
    └── Dockerfile
```

---

## Key Benefits

1. **No Secrets Management**: Workloads don't need long-lived credentials
2. **Identity Federation**: SPIFFE identities are bridged to enterprise IdP
3. **Audit Trail**: All database access is logged with full identity information
4. **Dynamic User Provisioning**: PostgreSQL users are created on-demand based on identity
5. **Zero Trust**: Every request is authenticated and authorized

---

## References

- [Microsoft Entra Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [SPIFFE/SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/microservices/oidc/)
- [Azure CLI - Federated Credentials](https://learn.microsoft.com/en-us/cli/azure/ad/app/federated-credential)
