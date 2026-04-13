#!/bin/bash
set -e

echo "=========================================="
echo "SPIRE Deployment via Zero Trust Workload"
echo "Identity Manager Operator"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if logged into OpenShift
if ! oc whoami &> /dev/null; then
    echo -e "${RED}ERROR: Not logged into OpenShift. Please run 'oc login' first.${NC}"
    exit 1
fi

echo -e "${GREEN}Logged in as: $(oc whoami)${NC}"
echo ""

# Check for placeholder values
if grep -q "YOUR-CLUSTER-DOMAIN" "$SCRIPT_DIR/k8s/"*.yaml; then
    echo -e "${RED}ERROR: Please update the configuration files with your cluster domain.${NC}"
    echo ""
    echo "Files that need updating:"
    grep -l "YOUR-CLUSTER-DOMAIN" "$SCRIPT_DIR/k8s/"*.yaml
    echo ""
    echo "Replace 'YOUR-CLUSTER-DOMAIN' with your actual cluster apps domain."
    echo "Example: apps.rosa.my-cluster.xxxx.p3.openshiftapps.com"
    exit 1
fi

echo -e "${YELLOW}Step 1: Creating namespace${NC}"
oc apply -f "$SCRIPT_DIR/k8s/01-namespace.yaml"
echo -e "${GREEN}✓ Namespace created${NC}"

echo -e "${YELLOW}Step 2: Creating OperatorGroup${NC}"
oc apply -f "$SCRIPT_DIR/k8s/02-operatorgroup.yaml"
echo -e "${GREEN}✓ OperatorGroup created${NC}"

echo -e "${YELLOW}Step 3: Subscribing to operator${NC}"
oc apply -f "$SCRIPT_DIR/k8s/03-subscription.yaml"
echo ""
echo "Waiting for operator to be installed..."

# Wait for CSV to be ready (timeout after 5 minutes)
TIMEOUT=300
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    PHASE=$(oc get csv -n zero-trust-workload-identity-manager -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Pending")
    if [ "$PHASE" == "Succeeded" ]; then
        echo -e "${GREEN}✓ Operator installed successfully${NC}"
        break
    fi
    echo "  Operator status: $PHASE (waiting...)"
    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo -e "${YELLOW}Warning: Operator installation taking longer than expected.${NC}"
    echo "Check with: oc get csv -n zero-trust-workload-identity-manager"
fi

echo -e "${YELLOW}Step 4: Creating ZeroTrustWorkloadIdentityManager${NC}"
oc apply -f "$SCRIPT_DIR/k8s/04-zerotrustworkloadidentitymanager.yaml"
sleep 5
echo -e "${GREEN}✓ ZeroTrustWorkloadIdentityManager created${NC}"

echo -e "${YELLOW}Step 5: Deploying SPIRE Server${NC}"
oc apply -f "$SCRIPT_DIR/k8s/05-spireserver.yaml"
echo "Waiting for SPIRE Server to be ready..."
sleep 10

# Wait for SPIRE Server pod
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    READY=$(oc get pods -n zero-trust-workload-identity-manager -l app=spire-server -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
    if [ "$READY" == "true" ]; then
        echo -e "${GREEN}✓ SPIRE Server is ready${NC}"
        break
    fi
    echo "  Waiting for SPIRE Server..."
    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

echo -e "${YELLOW}Step 6: Deploying SPIRE Agent${NC}"
oc apply -f "$SCRIPT_DIR/k8s/06-spireagent.yaml"
echo "Waiting for SPIRE Agents..."
sleep 15
echo -e "${GREEN}✓ SPIRE Agent deployed${NC}"

echo -e "${YELLOW}Step 7: Deploying SPIFFE CSI Driver${NC}"
oc apply -f "$SCRIPT_DIR/k8s/07-spiffecsidriver.yaml"
sleep 10
echo -e "${GREEN}✓ SPIFFE CSI Driver deployed${NC}"

echo -e "${YELLOW}Step 8: Deploying OIDC Discovery Provider${NC}"
oc apply -f "$SCRIPT_DIR/k8s/08-spireoidcdiscoveryprovider.yaml"
sleep 10
echo -e "${GREEN}✓ OIDC Discovery Provider deployed${NC}"

echo ""
echo "=========================================="
echo -e "${GREEN}SPIRE Deployment Complete!${NC}"
echo "=========================================="
echo ""

echo "Deployed Components:"
oc get pods -n zero-trust-workload-identity-manager
echo ""

echo "CSI Driver:"
oc get csidrivers | grep spiffe || echo "  (may take a moment to register)"
echo ""

OIDC_ROUTE=$(oc get route -n zero-trust-workload-identity-manager -o jsonpath='{.items[0].spec.host}' 2>/dev/null || echo "")
if [ -n "$OIDC_ROUTE" ]; then
    echo "OIDC Discovery Provider:"
    echo "  https://$OIDC_ROUTE/.well-known/openid-configuration"
fi
echo ""

echo "SPIRE Bundle ConfigMap:"
oc get configmap spire-bundle -n zero-trust-workload-identity-manager &>/dev/null && echo "  ✓ Available" || echo "  (may take a moment to be created)"
echo ""

echo "Next steps:"
echo "  1. Create a ClusterSPIFFEID to register your workloads"
echo "  2. Deploy your application with SPIFFE CSI volume"
echo "  3. See main README.md for PostgreSQL demo"
