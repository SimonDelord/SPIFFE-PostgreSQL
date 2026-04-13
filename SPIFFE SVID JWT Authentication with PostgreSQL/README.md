# SPIFFE JWT-SVID Authentication with PostgreSQL 18 via Entra ID

This document describes how a **SPIFFE-enabled workload** can authenticate directly to **PostgreSQL 18** (running on OpenShift) by leveraging **Workload Identity Federation** with **Microsoft Entra ID** and PostgreSQL 18's native **OIDC authentication support**.

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [The Solution: Workload Identity Federation + PostgreSQL 18 OIDC](#the-solution-workload-identity-federation--postgresql-18-oidc)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
- [References](#references)

---

## Overview

**PostgreSQL 18** introduced native **OAuth 2.0/OIDC authentication support**, allowing applications to connect using OIDC tokens instead of passwords. Combined with the **pg_oidc_validator** extension, PostgreSQL can validate tokens from identity providers like **Microsoft Entra ID**.

This demo shows how **SPIFFE-enabled workloads** running on OpenShift can authenticate to PostgreSQL 18 by:
1. Obtaining a **JWT-SVID** from SPIRE
2. Exchanging it for an **Entra ID access token** via Workload Identity Federation
3. Connecting directly to **PostgreSQL 18** (on OpenShift) using the Entra ID token

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
│   │   App A         │     ───────?──────►   │   PostgreSQL 18 │             │
│   │  (SPIFFE        │     JWT-SVID          │  (Only accepts  │             │
│   │   enabled)      │     not accepted!     │   Entra ID      │             │
│   │                 │                       │   tokens)       │             │
│   └─────────────────┘                       └─────────────────┘             │
│                                                                              │
│   App A has a JWT-SVID from SPIRE                                           │
│   PostgreSQL only accepts Entra ID tokens                                   │
│   How do they communicate?                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Challenges:**
1. PostgreSQL doesn't understand JWT-SVIDs directly
2. The enterprise security team requires all database access to go through Entra ID
3. Need a way to bridge SPIFFE identity to Entra ID identity

---

## The Solution: Workload Identity Federation + PostgreSQL 18 OIDC

**Workload Identity Federation** allows SPIFFE/SPIRE to exchange JWT-SVIDs for Entra ID tokens. **PostgreSQL 18** with the **pg_oidc_validator** extension can then validate these Entra ID tokens directly.

### Key Components

| Component | Role |
|-----------|------|
| **PostgreSQL 18** | Native OAuth 2.0 authentication support |
| **pg_oidc_validator** | Extension that validates OIDC tokens against identity providers |
| **Microsoft Entra ID** | Enterprise IdP that issues access tokens |
| **SPIRE OIDC Discovery Provider** | Publishes JWKS for JWT-SVID validation |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                      SPIFFE → ENTRA ID → POSTGRESQL 18 (ON OPENSHIFT)                   │
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
│         │                            │                           │  │ PostgreSQL 18 │  │
│         │                            │                           │  │ (OpenShift)   │  │
│         │                            │                           │  │ + pg_oidc_    │  │
│         │                            │                           │  │   validator   │  │
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
│    6.   │ Connect to PostgreSQL with Entra ID token              │          │          │
│         │────────────────────────────────────────────────────────────────────►         │
│         │                            │                           │          │          │
│    7.   │                            │                           │◄─────────│          │
│         │                            │                           │ Validate │          │
│         │                            │                           │ token via│          │
│         │                            │                           │ Entra ID │          │
│         │                            │                           │ JWKS     │          │
│         │                            │                           │─────────►│          │
│         │                            │                           │          │          │
│    8.   │◄────────────────────────────────────────────────────────────────────         │
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
| 6 | Client | PostgreSQL 18 | Client connects using Entra ID token as password |
| 7 | PostgreSQL | Entra ID | PostgreSQL validates token via pg_oidc_validator |
| 8 | PostgreSQL | Client | Connection established, queries executed |

---

## How It Works

### Step 1-2: Client Obtains JWT-SVID from SPIRE

```python
from spiffe import WorkloadApiClient

client = WorkloadApiClient("unix:///spiffe-workload-api/spire-agent.sock")
jwt_svid = client.fetch_jwt_svid(audience={AZURE_CLIENT_ID})

# JWT-SVID payload:
# {
#   "iss": "https://spire-oidc.example.com",
#   "sub": "spiffe://trust-domain/ns/app/sa/client",
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

### Step 6-8: Connect to PostgreSQL 18 with Entra ID Token

```python
import psycopg2

conn = psycopg2.connect(
    host="postgresql.oidc-postgres-demo.svc",
    port=5432,
    database="demo",
    user="entra-app-name",      # The Entra ID app name or object ID
    password=entra_token,        # The Entra ID access token
    sslmode="require"
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM products")
results = cursor.fetchall()
```

---

## Prerequisites

### Azure Requirements

1. **Azure Subscription** with permissions to create App Registrations in Entra ID

2. **Entra ID App Registration** with:
   - Federated Identity Credential configured to trust your SPIRE OIDC Discovery Provider
   - Issuer: `https://your-spire-oidc-discovery-provider-url`
   - Subject: `spiffe://your-trust-domain/ns/oidc-postgres-demo/sa/spiffe-client`

### OpenShift/Kubernetes Requirements

1. **SPIRE** deployed via Zero Trust Workload Identity Manager
2. **SPIRE OIDC Discovery Provider** accessible from the internet (for Entra ID to fetch JWKS)
3. **PostgreSQL 18** with `pg_oidc_validator` extension

---

## Deployment

### 1. Configure Entra ID

```bash
# Login to Azure
az login

# Create App Registration
az ad app create --display-name "spiffe-postgres-client"

# Get Application ID
APP_ID=$(az ad app list --display-name "spiffe-postgres-client" --query "[0].appId" -o tsv)
echo "Application ID: $APP_ID"

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

### 2. Deploy PostgreSQL 18 on OpenShift

See `k8s/postgresql.yaml` for the deployment manifest.

```bash
# Apply PostgreSQL 18 deployment
oc apply -f k8s/postgresql.yaml

# Verify PostgreSQL is running
oc get pods -n oidc-postgres-demo
```

### 3. Configure PostgreSQL for OIDC Authentication

```sql
-- In PostgreSQL, configure pg_hba.conf for OAuth authentication
-- host all all 0.0.0.0/0 oauth

-- Configure the OAuth validator
ALTER SYSTEM SET oauth.validator_library = 'pg_oidc_validator';
ALTER SYSTEM SET oauth.issuer = 'https://login.microsoftonline.com/{tenant-id}/v2.0';
ALTER SYSTEM SET oauth.client_id = '{your-azure-client-id}';

SELECT pg_reload_conf();
```

### 4. Deploy the Client Application

```bash
# Update ConfigMaps with your Azure credentials
oc apply -f k8s/client-app.yaml

# Build the application
oc start-build client-app --from-dir=client-app/ -n oidc-postgres-demo --follow
```

---

## Folder Structure

```
SPIFFE SVID JWT Authentication with PostgreSQL/
├── README.md                    # This file
├── k8s/
│   ├── namespace.yaml           # Namespace definition
│   ├── clusterspiffeid.yaml     # SPIRE workload registration
│   ├── postgresql.yaml          # PostgreSQL 18 with pg_oidc_validator
│   └── client-app.yaml          # SPIFFE client deployment
├── client-app/
│   ├── app.py                   # Flask app with SPIFFE + Entra ID + PostgreSQL
│   ├── requirements.txt
│   └── Dockerfile
└── scripts/
    └── deploy.sh                # Automated deployment script
```

---

## PostgreSQL 18 OIDC Configuration

### pg_hba.conf

```
# TYPE  DATABASE        USER            ADDRESS                 METHOD
host    all             all             0.0.0.0/0               oauth
```

### postgresql.conf

```
# OAuth/OIDC Configuration
oauth.validator_library = 'pg_oidc_validator'
oauth.issuer = 'https://login.microsoftonline.com/{tenant-id}/v2.0'
oauth.client_id = '{azure-client-id}'
oauth.jwks_uri = 'https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys'
```

---

## References

- [PostgreSQL 18 OAuth Authentication Documentation](http://www.postgres.com/docs/18/auth-oauth.html)
- [pg_oidc_validator Extension](https://www.postgresql.org/about/news/announcing-pg_oidc_validator-3160/)
- [PostgreSQL 18 OIDC with Entra ID - Percona Blog](https://percona.community/blog/2025/10/22/say-hello-to-oidc-in-postgresql-18/)
- [Microsoft Entra Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [SPIFFE/SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/microservices/oidc/)
