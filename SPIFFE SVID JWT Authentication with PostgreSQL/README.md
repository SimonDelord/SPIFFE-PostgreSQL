# SPIFFE JWT-SVID Authentication with Enterprise IdP (Workload Identity Federation)

This document describes how a **SPIFFE-enabled workload** can authenticate to services that only understand **OIDC tokens** by leveraging **Workload Identity Federation** with an enterprise Identity Provider (like Microsoft Entra ID, AWS IAM, or Google Cloud).

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [The Solution: Workload Identity Federation](#the-solution-workload-identity-federation)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Demo Implementation](#demo-implementation)
- [Prerequisites](#prerequisites)
- [References](#references)

---

## Overview

In enterprise environments, organizations often have a centralized Identity Provider (IdP) like **Microsoft Entra ID** (formerly Azure AD) that manages identities for all applications and services. However, modern cloud-native workloads may use **SPIFFE/SPIRE** for workload identity.

This creates an integration challenge: **How can SPIFFE-enabled workloads authenticate to services that only understand the enterprise IdP's OIDC tokens?**

---

## The Problem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           THE CHALLENGE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SPIFFE World                              Enterprise OIDC World            │
│   ┌─────────────────┐                       ┌─────────────────┐             │
│   │                 │                       │                 │             │
│   │   App A         │     ───────?──────►   │   App B         │             │
│   │  (SPIFFE        │     JWT-SVID          │  (Only trusts   │             │
│   │   enabled)      │     not accepted!     │   Entra ID)     │             │
│   │                 │                       │                 │             │
│   └─────────────────┘                       └─────────────────┘             │
│                                                                              │
│   App A has a JWT-SVID from SPIRE                                           │
│   App B only validates tokens from Entra ID                                 │
│   How do they communicate?                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Challenges:**
1. App B doesn't know how to validate JWT-SVIDs
2. App B's authorization logic is based on Entra ID roles/claims
3. The enterprise security team requires all access to go through Entra ID

---

## The Solution: Workload Identity Federation

**Workload Identity Federation** allows external identity providers (like SPIFFE/SPIRE) to exchange their tokens for tokens from the enterprise IdP (like Entra ID).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WORKLOAD IDENTITY FEDERATION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────┐                                                           │
│   │   SPIRE     │                                                           │
│   │   Server    │                                                           │
│   └──────┬──────┘                                                           │
│          │                                                                   │
│          │ 1. Issue JWT-SVID                                                │
│          ▼                                                                   │
│   ┌─────────────┐     2. Present JWT-SVID      ┌─────────────────────┐     │
│   │   App A     │─────────────────────────────►│                     │     │
│   │  (SPIFFE    │                              │   Enterprise IdP    │     │
│   │   enabled)  │◄─────────────────────────────│   (Entra ID)        │     │
│   └──────┬──────┘     3. Return OIDC Token     │                     │     │
│          │                                      │  • Validates SVID   │     │
│          │                                      │  • Checks policy    │     │
│          │                                      │  • Issues token     │     │
│          │                                      └──────────┬──────────┘     │
│          │                                                 │                 │
│          │                                                 │ Fetch JWKS     │
│          │                                                 ▼                 │
│          │                                      ┌─────────────────────┐     │
│          │                                      │  SPIRE OIDC         │     │
│          │                                      │  Discovery Provider │     │
│          │                                      │  /.well-known/...   │     │
│          │                                      │  /keys              │     │
│          │                                      └─────────────────────┘     │
│          │                                                                   │
│          │ 4. Call with Entra ID Token                                      │
│          ▼                                                                   │
│   ┌─────────────┐                                                           │
│   │   App B     │  ✓ Validates Entra ID token                              │
│   │  (OIDC only)│  ✓ Extracts roles/permissions                            │
│   │             │  ✓ Grants access                                          │
│   └─────────────┘                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Components

| Component | Role |
|-----------|------|
| **SPIRE Server** | Issues JWT-SVIDs to registered workloads |
| **SPIRE OIDC Discovery Provider** | Exposes JWKS endpoint for JWT-SVID validation |
| **Enterprise IdP (Entra ID)** | Validates JWT-SVIDs and issues enterprise tokens |
| **App A (SPIFFE-enabled)** | Obtains JWT-SVID, exchanges for enterprise token |
| **App B (OIDC-only)** | Validates enterprise tokens, serves requests |

### Trust Chain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TRUST CHAIN                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SPIRE Server ──────► SPIRE OIDC Discovery Provider                        │
│        │                         │                                           │
│        │ Signs JWT-SVIDs         │ Publishes JWKS                           │
│        │                         │                                           │
│        ▼                         ▼                                           │
│   ┌─────────────────────────────────────────────────────────┐               │
│   │                                                          │               │
│   │   Enterprise IdP (Entra ID)                             │               │
│   │                                                          │               │
│   │   Federated Identity Credential:                        │               │
│   │   ┌────────────────────────────────────────────────┐    │               │
│   │   │ Issuer: https://spire-oidc.example.com         │    │               │
│   │   │ Subject: spiffe://trust-domain/ns/prod/sa/app-a│    │               │
│   │   │ Audience: api://AzureADTokenExchange           │    │               │
│   │   └────────────────────────────────────────────────┘    │               │
│   │                                                          │               │
│   │   "I trust JWT-SVIDs from this SPIRE instance            │               │
│   │    for workloads with these specific SPIFFE IDs"        │               │
│   │                                                          │               │
│   └─────────────────────────────────────────────────────────┘               │
│                              │                                               │
│                              │ Issues Entra ID tokens                       │
│                              ▼                                               │
│   ┌─────────────────────────────────────────────────────────┐               │
│   │                                                          │               │
│   │   App B (and other Entra ID-protected resources)        │               │
│   │                                                          │               │
│   │   Validates tokens using Entra ID JWKS                  │               │
│   │                                                          │               │
│   └─────────────────────────────────────────────────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works

### Step-by-Step Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TOKEN EXCHANGE FLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Step 1: App A obtains JWT-SVID from SPIRE                                  │
│  ─────────────────────────────────────────                                  │
│                                                                              │
│  App A ──────────────────────────────────────────────► SPIRE Agent          │
│         Request JWT-SVID                                                     │
│         audience: "api://AzureADTokenExchange"                              │
│                                                                              │
│  App A ◄────────────────────────────────────────────── SPIRE Agent          │
│         JWT-SVID:                                                            │
│         {                                                                    │
│           "iss": "https://spire-oidc.example.com",                          │
│           "sub": "spiffe://trust-domain/ns/prod/sa/app-a",                  │
│           "aud": "api://AzureADTokenExchange",                              │
│           "exp": 1234567890,                                                │
│           "iat": 1234567800                                                 │
│         }                                                                    │
│                                                                              │
│  ────────────────────────────────────────────────────────────────────────   │
│                                                                              │
│  Step 2: App A exchanges JWT-SVID for Entra ID token                        │
│  ─────────────────────────────────────────────────────                      │
│                                                                              │
│  App A ──────────────────────────────────────────────► Entra ID             │
│         POST /oauth2/v2.0/token                                             │
│         client_id={app-registration-id}                                     │
│         client_assertion_type=urn:ietf:params:oauth:                        │
│                                client-assertion-type:jwt-bearer             │
│         client_assertion={JWT-SVID}                                         │
│         grant_type=client_credentials                                       │
│         scope=api://app-b/.default                                          │
│                                                                              │
│  Entra ID internally:                                                        │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ 1. Parse JWT-SVID header to get "kid"                              │     │
│  │ 2. Fetch JWKS from https://spire-oidc.example.com/keys            │     │
│  │ 3. Verify signature using SPIRE's public key                       │     │
│  │ 4. Check "iss" matches Federated Identity Credential               │     │
│  │ 5. Check "sub" (SPIFFE ID) matches allowed subject                 │     │
│  │ 6. Check "aud" matches expected audience                           │     │
│  │ 7. Check token is not expired                                      │     │
│  │ 8. All checks pass → Issue Entra ID access token                   │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  App A ◄────────────────────────────────────────────── Entra ID             │
│         {                                                                    │
│           "access_token": "eyJ0eXAiOi...",                                  │
│           "token_type": "Bearer",                                           │
│           "expires_in": 3600                                                │
│         }                                                                    │
│                                                                              │
│  ────────────────────────────────────────────────────────────────────────   │
│                                                                              │
│  Step 3: App A calls App B with Entra ID token                              │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  App A ──────────────────────────────────────────────► App B                │
│         GET /api/data                                                        │
│         Authorization: Bearer {Entra ID Access Token}                       │
│                                                                              │
│  App B validates token against Entra ID JWKS                                │
│  App B extracts claims (roles, permissions)                                 │
│  App B serves request                                                        │
│                                                                              │
│  App A ◄────────────────────────────────────────────── App B                │
│         200 OK                                                               │
│         {"data": "..."}                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Demo Implementation

### What We Built

This demo implements the Workload Identity Federation pattern using:

| Component | Production | This Demo |
|-----------|------------|-----------|
| **Enterprise IdP** | Microsoft Entra ID, AWS IAM, or GCP | **Keycloak** (emulating Entra ID) |
| **Token Exchange** | Real RFC 8693 token exchange | **Mock Token Exchange** (validates JWT-SVID, issues OIDC token) |
| **SPIFFE Identity** | SPIRE (production) | SPIRE via Zero Trust Workload Identity Manager |
| **OIDC-only App** | Any OIDC-protected service | Flask API Server |

### Demo Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         DEMO ARCHITECTURE                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  Namespace: zero-trust-workload-identity-manager                         │    │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐      │    │
│  │  │  SPIRE Server   │    │  SPIRE Agent    │    │  SPIRE OIDC     │      │    │
│  │  │                 │    │  (DaemonSet)    │    │  Discovery      │      │    │
│  │  │                 │    │                 │    │  Provider       │      │    │
│  │  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘      │    │
│  │           │                      │                      │                │    │
│  │           └──────────────────────┼──────────────────────┘                │    │
│  │                                  │ Issues JWT-SVIDs                      │    │
│  └──────────────────────────────────┼───────────────────────────────────────┘    │
│                                     ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  Namespace: spiffe-jwt-demo                                              │    │
│  │                                                                          │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │  JWT Exchange Client (SPIFFE-enabled)                           │    │    │
│  │  │                                                                  │    │    │
│  │  │  1. Fetches JWT-SVID from SPIRE Agent                           │    │    │
│  │  │  2. Validates JWT-SVID against SPIRE OIDC Discovery Provider    │    │    │
│  │  │  3. Issues mock OIDC token (simulating Keycloak/Entra ID)       │    │    │
│  │  │  4. Calls API Server with OIDC token                            │    │    │
│  │  │                                                                  │    │    │
│  │  └─────────────────────────────────┬───────────────────────────────┘    │    │
│  │                                    │                                     │    │
│  │                                    │ OIDC Token                          │    │
│  │                                    ▼                                     │    │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │    │
│  │  │  API Server (OIDC-only, does NOT understand SPIFFE)             │    │    │
│  │  │                                                                  │    │    │
│  │  │  • Validates OIDC tokens only                                   │    │    │
│  │  │  • Does NOT have SPIFFE CSI driver mounted                      │    │    │
│  │  │  • Returns data if token is valid                               │    │    │
│  │  │                                                                  │    │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │    │
│  │                                                                          │    │
│  └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  Namespace: keycloak                                                     │    │
│  │                                                                          │    │
│  │  ┌─────────────────┐    ┌─────────────────┐                             │    │
│  │  │  Keycloak       │    │  PostgreSQL     │                             │    │
│  │  │  (IdP)          │────│  (Database)     │                             │    │
│  │  │                 │    │                 │                             │    │
│  │  │  Configured     │    └─────────────────┘                             │    │
│  │  │  with:          │                                                     │    │
│  │  │  • spiffe-demo  │                                                     │    │
│  │  │    realm        │                                                     │    │
│  │  │  • SPIRE OIDC   │                                                     │    │
│  │  │    as IdP       │                                                     │    │
│  │  └─────────────────┘                                                     │    │
│  │                                                                          │    │
│  └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### How the Mock Token Exchange Works

Since configuring real Keycloak Token Exchange (RFC 8693) requires complex fine-grained authorization, this demo uses a **mock token exchange** that accurately demonstrates the pattern:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MOCK TOKEN EXCHANGE FLOW                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Client App                    SPIRE OIDC                   API Server       │
│      │                         Provider                          │           │
│      │                            │                              │           │
│      │  1. Get JWT-SVID           │                              │           │
│      │     from SPIRE Agent       │                              │           │
│      │                            │                              │           │
│      │  2. Validate JWT-SVID ────►│                              │           │
│      │     (fetch JWKS, verify)   │                              │           │
│      │                            │                              │           │
│      │  3. JWT-SVID is valid ◄────│                              │           │
│      │                            │                              │           │
│      │  4. Issue mock OIDC token  │                              │           │
│      │     (simulating Keycloak)  │                              │           │
│      │     {                      │                              │           │
│      │       "iss": "keycloak",   │                              │           │
│      │       "sub": "{spiffe-id}",│                              │           │
│      │       "aud": "api-server"  │                              │           │
│      │     }                      │                              │           │
│      │                            │                              │           │
│      │  5. Call API with OIDC token ─────────────────────────────►          │
│      │                            │                              │           │
│      │                            │              6. Validate token           │
│      │                            │                 (mock validation)        │
│      │                            │                              │           │
│      │  7. Return data ◄──────────────────────────────────────────          │
│      │                            │                              │           │
│                                                                              │
│  KEY POINT: The JWT-SVID is REALLY validated against SPIRE OIDC Discovery   │
│  Provider. Only the token issuance is mocked.                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Deployed Components

| Component | Namespace | Description |
|-----------|-----------|-------------|
| **Keycloak** | `keycloak` | Enterprise IdP (emulating Entra ID) with SPIRE as trusted Identity Provider |
| **JWT Exchange Client** | `spiffe-jwt-demo` | SPIFFE-enabled app that gets JWT-SVIDs and exchanges for OIDC tokens |
| **API Server** | `spiffe-jwt-demo` | OIDC-only app that validates Keycloak tokens |
| **SPIRE** | `zero-trust-workload-identity-manager` | Issues JWT-SVIDs and X.509-SVIDs |

### Live Demo URLs

After deployment, the following URLs are available:

- **JWT Exchange Client**: `https://jwt-exchange-client-spiffe-jwt-demo.apps.<cluster-domain>`
- **API Server**: `https://api-server-spiffe-jwt-demo.apps.<cluster-domain>`
- **Keycloak Admin**: `https://keycloak-keycloak.apps.<cluster-domain>`

### Folder Structure

```
SPIFFE SVID JWT Authentication with PostgreSQL/
├── README.md                    # This file
├── deployment-guide/            # Step-by-step deployment instructions
│   └── README.md
├── k8s/
│   ├── namespace.yaml           # spiffe-jwt-demo namespace
│   ├── clusterspiffeid.yaml     # SPIRE workload registration
│   ├── client-app.yaml          # JWT Exchange Client deployment
│   └── api-server.yaml          # OIDC-only API Server deployment
├── client-app/
│   ├── app.py                   # Flask app with SPIFFE + token exchange
│   ├── requirements.txt
│   └── Dockerfile
├── api-server/
│   ├── app.py                   # Flask app validating OIDC tokens
│   ├── requirements.txt
│   └── Dockerfile
└── scripts/
    └── deploy.sh                # Automated deployment script
```

---

## Prerequisites

1. **OpenShift cluster** with Zero Trust Workload Identity Manager installed
2. **SPIRE OIDC Discovery Provider** deployed and accessible
3. **Keycloak** deployed (or use the deployment guide to deploy it)

---

## Deployment

For step-by-step deployment instructions, see the [Deployment Guide](deployment-guide/README.md).

---

## References

- [Microsoft Entra Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [AWS IAM OIDC Identity Providers](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [GCP Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [SPIFFE/SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/microservices/oidc/)
- [RFC 8693 - OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)
