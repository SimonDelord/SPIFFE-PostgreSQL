# SPIFFE JWT-SVID Authentication with PostgreSQL via Entra ID

This document describes how a **SPIFFE-enabled workload** can authenticate directly to **PostgreSQL** by leveraging **Workload Identity Federation** with **Microsoft Entra ID** (formerly Azure AD).

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [The Solution: Workload Identity Federation](#the-solution-workload-identity-federation)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
- [References](#references)

---

## Overview

In enterprise environments, organizations often use **Microsoft Entra ID** as their centralized Identity Provider. **Azure Database for PostgreSQL** supports native Entra ID authentication, allowing applications to connect using OIDC tokens instead of passwords.

This demo shows how **SPIFFE-enabled workloads** running on Kubernetes can authenticate to PostgreSQL by:
1. Obtaining a **JWT-SVID** from SPIRE
2. Exchanging it for an **Entra ID access token** via Workload Identity Federation
3. Connecting directly to **PostgreSQL** using the Entra ID token

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
1. PostgreSQL doesn't understand JWT-SVIDs
2. The enterprise security team requires all database access to go through Entra ID
3. Need a way to bridge SPIFFE identity to Entra ID identity

---

## The Solution: Workload Identity Federation

**Workload Identity Federation** allows external identity providers (like SPIFFE/SPIRE) to exchange their tokens for Entra ID tokens. Entra ID validates the JWT-SVID by fetching the JWKS from the **SPIRE OIDC Discovery Provider**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                      SPIFFE → ENTRA ID → POSTGRESQL FLOW                                │
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
│         │                            │                           │      ┌────────────┐ │
│         │                            │                           │      │ PostgreSQL │ │
│         │                            │                           │      │ (Azure DB) │ │
│         │                            │                           │      └──────┬─────┘ │
│         │                            │                           │             │       │
│    1.   │ Request JWT-SVID           │                           │             │       │
│         │───────────────────────────►│                           │             │       │
│         │                            │                           │             │       │
│    2.   │◄───────────────────────────│ Issue JWT-SVID            │             │       │
│         │       (signed JWT)         │                           │             │       │
│         │                            │                           │             │       │
│    3.   │ Exchange JWT-SVID for Entra ID token                   │             │       │
│         │───────────────────────────────────────────────────────►│             │       │
│         │            (Workload Identity Federation)              │             │       │
│         │                            │                           │             │       │
│    4.   │                            │◄──────────────────────────│             │       │
│         │                            │  Fetch JWKS to validate   │             │       │
│         │                            │  JWT-SVID signature       │             │       │
│         │                            │──────────────────────────►│             │       │
│         │                            │                           │             │       │
│    5.   │◄───────────────────────────────────────────────────────│             │       │
│         │              Entra ID Access Token                     │             │       │
│         │                            │                           │             │       │
│    6.   │ Connect to PostgreSQL with Entra ID token              │             │       │
│         │────────────────────────────────────────────────────────────────────►│       │
│         │                            │                           │             │       │
│    7.   │                            │                           │◄────────────│       │
│         │                            │                           │ Validate    │       │
│         │                            │                           │ token via   │       │
│         │                            │                           │ Entra JWKS  │       │
│         │                            │                           │────────────►│       │
│         │                            │                           │             │       │
│    8.   │◄─────────────────────────────────────────────────────────────────────│       │
│         │                            │        Return data        │             │       │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Role |
|-----------|------|
| **SPIRE Server** | Issues JWT-SVIDs to registered workloads |
| **SPIRE OIDC Discovery Provider** | Exposes JWKS endpoint (`/keys`) for JWT-SVID validation |
| **Microsoft Entra ID** | Validates JWT-SVIDs via OIDC Discovery Provider, issues access tokens |
| **SPIFFE Client App** | Obtains JWT-SVID, exchanges for Entra ID token, connects to PostgreSQL |
| **Azure Database for PostgreSQL** | Validates Entra ID tokens, serves database queries |

---

## How It Works

### Step-by-Step Flow

#### Step 1: Client Requests JWT-SVID from SPIRE

```
Client App ──────────────────────────────► SPIRE Agent
            Request JWT-SVID
            audience: "{azure-client-id}"
```

The SPIFFE-enabled client uses the Workload API to request a JWT-SVID with the Azure application's client ID as the audience.

#### Step 2: SPIRE Issues JWT-SVID

```
Client App ◄────────────────────────────── SPIRE Agent
            JWT-SVID:
            {
              "iss": "https://spire-oidc.example.com",
              "sub": "spiffe://trust-domain/ns/app/sa/client",
              "aud": "{azure-client-id}",
              "exp": 1234567890,
              "iat": 1234567800
            }
```

SPIRE signs the JWT-SVID with its private key. The public key is available via the OIDC Discovery Provider.

#### Step 3: Client Exchanges JWT-SVID for Entra ID Token

```
Client App ──────────────────────────────► Entra ID
            POST /oauth2/v2.0/token
            
            client_id={azure-app-registration-id}
            client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
            client_assertion={JWT-SVID}
            grant_type=client_credentials
            scope=https://ossrdbms-aad.database.windows.net/.default
```

The client sends the JWT-SVID to Entra ID's token endpoint using the `client_credentials` grant with `client_assertion`.

#### Step 4: Entra ID Validates JWT-SVID

```
Entra ID ──────────────────────────────► SPIRE OIDC Discovery Provider
          GET /.well-known/openid-configuration
          GET /keys (JWKS)
          
Entra ID validates:
  ✓ Signature (using SPIRE's public key from JWKS)
  ✓ Issuer matches Federated Identity Credential
  ✓ Subject (SPIFFE ID) matches allowed pattern
  ✓ Audience matches expected value
  ✓ Token is not expired
```

#### Step 5: Entra ID Issues Access Token

```
Client App ◄────────────────────────────── Entra ID
            {
              "access_token": "eyJ0eXAiOiJKV1...",
              "token_type": "Bearer",
              "expires_in": 3600
            }
```

#### Step 6-8: Client Connects to PostgreSQL

```
Client App ──────────────────────────────► PostgreSQL
            Connect with:
            - Username: {entra-user-or-app-name}
            - Password: {entra-access-token}
            
PostgreSQL:
  ✓ Validates token against Entra ID JWKS
  ✓ Checks user has database permissions
  ✓ Establishes connection
  
Client App ◄────────────────────────────── PostgreSQL
            Query results
```

---

## Prerequisites

### Azure Requirements

1. **Azure Subscription** with permissions to create:
   - App Registration in Entra ID
   - Azure Database for PostgreSQL Flexible Server

2. **Entra ID App Registration** with:
   - Federated Identity Credential configured to trust your SPIRE OIDC Discovery Provider
   - API permissions for PostgreSQL access

3. **Azure Database for PostgreSQL Flexible Server** with:
   - Entra ID authentication enabled
   - Database user mapped to the App Registration

### OpenShift/Kubernetes Requirements

1. **SPIRE** deployed via Zero Trust Workload Identity Manager
2. **SPIRE OIDC Discovery Provider** accessible from the internet (for Entra ID to fetch JWKS)
3. **ClusterSPIFFEID** configured for the client workload

---

## Deployment

### 1. Configure Entra ID

#### Create App Registration

```bash
# Login to Azure
az login

# Create App Registration
az ad app create --display-name "spiffe-postgres-client"

# Note the Application (client) ID
APP_ID=$(az ad app list --display-name "spiffe-postgres-client" --query "[0].appId" -o tsv)
echo "Application ID: $APP_ID"
```

#### Configure Federated Identity Credential

```bash
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

### 2. Configure Azure PostgreSQL

```bash
# Create PostgreSQL Flexible Server (if not exists)
az postgres flexible-server create \
  --name your-postgres-server \
  --resource-group your-resource-group \
  --location eastus \
  --admin-user adminuser \
  --admin-password YourSecurePassword123!

# Enable Entra ID authentication
az postgres flexible-server ad-admin create \
  --resource-group your-resource-group \
  --server-name your-postgres-server \
  --display-name "spiffe-postgres-client" \
  --object-id $(az ad app show --id $APP_ID --query "id" -o tsv)
```

### 3. Deploy the Client Application

See the `k8s/` folder for Kubernetes manifests and `client-app/` for the application code.

```bash
# Update ConfigMaps with your Azure credentials
# Then apply manifests
oc apply -f k8s/
```

---

## Folder Structure

```
SPIFFE SVID JWT Authentication with PostgreSQL/
├── README.md                    # This file
├── k8s/
│   ├── namespace.yaml           # Namespace definition
│   ├── clusterspiffeid.yaml     # SPIRE workload registration
│   ├── postgresql.yaml          # PostgreSQL deployment (for local testing)
│   └── client-app.yaml          # SPIFFE client deployment
├── client-app/
│   ├── app.py                   # Flask app with SPIFFE + Entra ID integration
│   ├── requirements.txt
│   └── Dockerfile
└── scripts/
    └── deploy.sh                # Automated deployment script
```

---

## References

- [Microsoft Entra Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [Azure Database for PostgreSQL - Entra ID Authentication](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication)
- [SPIFFE/SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/microservices/oidc/)
- [OAuth 2.0 Client Credentials with Federated Credentials](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow#third-case-access-token-request-with-a-federated-credential)
