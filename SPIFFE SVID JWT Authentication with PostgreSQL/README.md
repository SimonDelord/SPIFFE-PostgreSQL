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

In this demo, we will:

1. **Deploy a SPIFFE-enabled client application** that:
   - Fetches a JWT-SVID from SPIRE
   - Exchanges it for an enterprise OIDC token (simulated or real)
   - Uses that token to authenticate to a target service

2. **Deploy an OIDC-protected API server** that:
   - Validates OIDC tokens (not JWT-SVIDs directly)
   - Returns data based on token claims

### Folder Structure

```
SPIFFE SVID JWT Authentication with PostgreSQL/
├── README.md                    # This file
├── k8s/
│   ├── client-app/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── clusterspiffeid.yaml
│   │   └── configmap.yaml
│   ├── api-server/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── configmap.yaml
│   └── token-exchange-mock/     # Simulates Entra ID token exchange
│       ├── deployment.yaml
│       └── service.yaml
├── client-app/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── api-server/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
└── scripts/
    └── deploy.sh
```

---

## Prerequisites

1. **OpenShift cluster** with Zero Trust Workload Identity Manager installed
2. **SPIRE OIDC Discovery Provider** deployed and accessible
3. **Enterprise IdP** (Entra ID, AWS IAM, or GCP) configured with:
   - SPIRE OIDC Discovery Provider as a trusted issuer
   - Federated Identity Credential for the specific SPIFFE ID

---

## References

- [Microsoft Entra Workload Identity Federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [AWS IAM OIDC Identity Providers](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [GCP Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [SPIFFE/SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/microservices/oidc/)
- [RFC 8693 - OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)
