#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== SPIFFE JWT-SVID Token Exchange Demo Deployment ==="
echo ""

echo "Step 1: Creating namespace..."
oc apply -f "$BASE_DIR/k8s/namespace.yaml"

echo ""
echo "Step 2: Registering workload with SPIRE..."
oc apply -f "$BASE_DIR/k8s/clusterspiffeid.yaml"

echo ""
echo "Step 3: Deploying API Server (OIDC-only)..."
oc apply -f "$BASE_DIR/k8s/api-server.yaml"

echo ""
echo "Step 4: Building API Server image..."
oc start-build api-server \
    --from-dir="$BASE_DIR/api-server" \
    -n spiffe-jwt-demo \
    --follow

echo ""
echo "Step 5: Waiting for API Server deployment..."
oc rollout status deployment/api-server -n spiffe-jwt-demo --timeout=120s

echo ""
echo "Step 6: Deploying JWT Exchange Client (SPIFFE-enabled)..."
oc apply -f "$BASE_DIR/k8s/client-app.yaml"

echo ""
echo "Step 7: Building Client App image..."
oc start-build jwt-exchange-client \
    --from-dir="$BASE_DIR/client-app" \
    -n spiffe-jwt-demo \
    --follow

echo ""
echo "Step 8: Waiting for Client App deployment..."
oc rollout status deployment/jwt-exchange-client -n spiffe-jwt-demo --timeout=120s

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Application URLs:"
echo "  Client App: https://$(oc get route jwt-exchange-client -n spiffe-jwt-demo -o jsonpath='{.spec.host}')"
echo "  API Server: https://$(oc get route api-server -n spiffe-jwt-demo -o jsonpath='{.spec.host}')"
echo ""
echo "To test the full flow, open the Client App URL in your browser."
