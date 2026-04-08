#!/bin/bash
# Test script for SPIFFE PostgreSQL connection

echo "=========================================="
echo "Testing SPIFFE PostgreSQL Connection"
echo "=========================================="

# Get pod name
POD=$(oc get pods -n spiffe-edb-demo -l app=db-client-app -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$POD" ]; then
    echo "ERROR: Could not find db-client-app pod"
    exit 1
fi

echo "Testing from pod: $POD"
echo ""

echo "1. Checking SPIFFE identity..."
oc exec -n spiffe-edb-demo $POD -- curl -s http://localhost:8080/api/identity | jq .

echo ""
echo "2. Checking certificate details..."
oc exec -n spiffe-edb-demo $POD -- curl -s http://localhost:8080/api/certificate | jq .

echo ""
echo "3. Testing database connection..."
oc exec -n spiffe-edb-demo $POD -- curl -s http://localhost:8080/api/db/test | jq .

echo ""
echo "4. Querying data..."
oc exec -n spiffe-edb-demo $POD -- curl -s http://localhost:8080/api/db/query | jq .

echo ""
echo "5. Testing insert (may fail if read-only role)..."
oc exec -n spiffe-edb-demo $POD -- curl -s -X POST http://localhost:8080/api/db/insert | jq .
