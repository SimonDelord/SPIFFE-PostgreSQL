#!/bin/bash
set -e

echo "=========================================="
echo "SPIFFE PostgreSQL Demo Deployment Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

echo -e "${YELLOW}Step 1: Create SPIRE CA Secret in EDB namespace${NC}"
# Export SPIRE CA bundle and create secret
SPIRE_CA=$(oc get configmap spire-bundle -n zero-trust-workload-identity-manager -o jsonpath='{.data.bundle\.crt}')
if [ -z "$SPIRE_CA" ]; then
    echo -e "${RED}ERROR: Could not get SPIRE CA bundle${NC}"
    exit 1
fi

# Delete existing secret if it exists
oc delete secret spire-ca-bundle -n edb --ignore-not-found

# Create secret with SPIRE CA
oc create secret generic spire-ca-bundle \
    --from-literal=ca.crt="$SPIRE_CA" \
    -n edb

echo -e "${GREEN}✓ SPIRE CA secret created${NC}"

echo -e "${YELLOW}Step 2: Deploy EDB PostgreSQL Cluster${NC}"
oc apply -f "$BASE_DIR/k8s/edb/edb-cluster.yaml"

echo "Waiting for EDB cluster to be ready..."
sleep 10

# Wait for cluster to be ready (timeout after 5 minutes)
TIMEOUT=300
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(oc get cluster edb-spiffe-cluster -n edb -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    if [ "$STATUS" == "Cluster in healthy state" ]; then
        echo -e "${GREEN}✓ EDB Cluster is ready${NC}"
        break
    fi
    echo "  Cluster status: $STATUS (waiting...)"
    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo -e "${YELLOW}Warning: Cluster may still be initializing. Check with: oc get cluster -n edb${NC}"
fi

echo -e "${YELLOW}Step 3: Create client namespace and resources${NC}"
oc apply -f "$BASE_DIR/k8s/db-client/namespace.yaml"

# Label the namespace for SPIFFE
oc label namespace spiffe-edb-demo app.kubernetes.io/part-of=spiffe-demo --overwrite

oc apply -f "$BASE_DIR/k8s/db-client/serviceaccount.yaml"
oc apply -f "$BASE_DIR/k8s/db-client/configmap.yaml"
oc apply -f "$BASE_DIR/k8s/db-client/imagestream.yaml"
oc apply -f "$BASE_DIR/k8s/db-client/buildconfig.yaml"

echo -e "${GREEN}✓ Client resources created${NC}"

echo -e "${YELLOW}Step 4: Register workload with SPIRE${NC}"
oc apply -f "$BASE_DIR/k8s/db-client/clusterspiffeid.yaml"
echo -e "${GREEN}✓ ClusterSPIFFEID created${NC}"

echo -e "${YELLOW}Step 5: Build client application${NC}"
oc start-build db-client-app \
    --from-dir="$BASE_DIR/db-client-app" \
    -n spiffe-edb-demo \
    --follow

echo -e "${GREEN}✓ Application built${NC}"

echo -e "${YELLOW}Step 6: Deploy client application${NC}"
oc apply -f "$BASE_DIR/k8s/db-client/deployment.yaml"
oc apply -f "$BASE_DIR/k8s/db-client/service.yaml"
oc apply -f "$BASE_DIR/k8s/db-client/route.yaml"

echo "Waiting for deployment to be ready..."
oc rollout status deployment/db-client-app -n spiffe-edb-demo --timeout=120s

echo -e "${GREEN}✓ Application deployed${NC}"

echo ""
echo "=========================================="
echo -e "${GREEN}Deployment Complete!${NC}"
echo "=========================================="
echo ""
echo "EDB Cluster:"
oc get cluster -n edb
echo ""
echo "Client Application:"
oc get pods -n spiffe-edb-demo
echo ""
echo "Application URL:"
echo "  https://$(oc get route db-client-app -n spiffe-edb-demo -o jsonpath='{.spec.host}')"
echo ""
echo "To check SPIFFE registration:"
echo "  oc get clusterspiffeids"
echo ""
echo "To view EDB logs:"
echo "  oc logs -n edb -l cnpg.io/cluster=edb-spiffe-cluster"
