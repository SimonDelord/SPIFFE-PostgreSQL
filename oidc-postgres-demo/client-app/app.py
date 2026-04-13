"""
SPIFFE-enabled Client App that exchanges JWT-SVID for Entra ID token.

Flow:
1. Get JWT-SVID from SPIRE Agent
2. Exchange JWT-SVID for Entra ID access token via Workload Identity Federation
3. Call the API Server with the Entra ID token
"""

import os
import json
import logging
import time
from datetime import datetime

from flask import Flask, render_template_string, jsonify, request
import requests
from spiffe import WorkloadApiClient

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SPIFFE configuration
SPIFFE_ENDPOINT_SOCKET = os.environ.get(
    'SPIFFE_ENDPOINT_SOCKET',
    'unix:///spiffe-workload-api/spire-agent.sock'
)

# Azure Entra ID configuration for Workload Identity Federation
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID', '')
AZURE_CLIENT_ID = os.environ.get('AZURE_CLIENT_ID', '')
AZURE_TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token" if AZURE_TENANT_ID else ''

# API Server URL
API_SERVER_URL = os.environ.get('API_SERVER_URL', 'http://api-server:8080')

# HTML template for the UI
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>SPIFFE to Entra ID - Client App</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #333; border-bottom: 2px solid #0078d4; padding-bottom: 10px; }
        h2 { color: #0078d4; margin-top: 30px; }
        .card { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .step { background: #e7f3ff; border-left: 4px solid #0078d4; padding: 15px; margin: 10px 0; }
        .step-num { font-weight: bold; color: #0078d4; }
        button { background: #0078d4; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; margin: 5px; font-size: 14px; }
        button:hover { background: #106ebe; }
        button:disabled { background: #ccc; cursor: not-allowed; }
        .success { background: #d4edda; border-color: #28a745; color: #155724; }
        .error { background: #f8d7da; border-color: #dc3545; color: #721c24; }
        pre { background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px; }
        .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
        .config-table { width: 100%; border-collapse: collapse; }
        .config-table td { padding: 8px; border-bottom: 1px solid #eee; }
        .config-table td:first-child { font-weight: bold; width: 200px; }
        .diagram { background: #f8f9fa; padding: 20px; border-radius: 4px; font-family: monospace; white-space: pre; overflow-x: auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SPIFFE to Entra ID Token Exchange Demo</h1>
        
        <div class="card">
            <h2>Architecture</h2>
            <div class="diagram">
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     WORKLOAD IDENTITY FEDERATION FLOW                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐ │
│  │   SPIFFE     │     │   Entra ID   │     │  API Server  │     │ PostgreSQL │ │
│  │   Client     │     │  (Azure AD)  │     │              │     │            │ │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘     └──────┬─────┘ │
│         │                    │                    │                    │       │
│    1.   │ Get JWT-SVID       │                    │                    │       │
│         │ from SPIRE         │                    │                    │       │
│         │◄───────────────────│                    │                    │       │
│         │                    │                    │                    │       │
│    2.   │ Exchange JWT-SVID  │                    │                    │       │
│         │ for Entra ID token │                    │                    │       │
│         │───────────────────►│                    │                    │       │
│         │                    │                    │                    │       │
│    3.   │◄───────────────────│ Return Entra ID   │                    │       │
│         │    access token    │ access token       │                    │       │
│         │                    │                    │                    │       │
│    4.   │ Call API with      │                    │                    │       │
│         │ Entra ID token     │                    │                    │       │
│         │────────────────────────────────────────►│                    │       │
│         │                    │                    │                    │       │
│    5.   │                    │                    │ Validate token     │       │
│         │                    │◄───────────────────│ against Entra ID   │       │
│         │                    │    JWKS/OIDC       │                    │       │
│         │                    │───────────────────►│                    │       │
│         │                    │                    │                    │       │
│    6.   │                    │                    │ Query database     │       │
│         │                    │                    │───────────────────►│       │
│         │                    │                    │◄───────────────────│       │
│         │                    │                    │                    │       │
│    7.   │◄────────────────────────────────────────│ Return data        │       │
│         │                    │                    │                    │       │
└─────────────────────────────────────────────────────────────────────────────────┘
            </div>
        </div>
        
        <div class="card">
            <h2>Configuration</h2>
            <table class="config-table">
                <tr><td>SPIFFE Endpoint</td><td>{{ spiffe_endpoint }}</td></tr>
                <tr><td>Azure Tenant ID</td><td>{{ azure_tenant_id }}</td></tr>
                <tr><td>Azure Client ID</td><td>{{ azure_client_id }}</td></tr>
                <tr><td>API Server URL</td><td>{{ api_server_url }}</td></tr>
                <tr><td>Entra ID Configured</td><td>{{ entra_configured }}</td></tr>
            </table>
        </div>
        
        <div class="card">
            <h2>Demo Steps</h2>
            
            <div class="step">
                <span class="step-num">Step 1:</span> Get JWT-SVID from SPIRE
                <br><button onclick="getJwtSvid()">Get JWT-SVID</button>
                <div id="jwt-svid-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Step 2:</span> Exchange JWT-SVID for Entra ID Token
                <br><button onclick="exchangeToken()" id="exchange-btn" disabled>Exchange for Entra ID Token</button>
                <div id="exchange-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Step 3:</span> Call API Server with Entra ID Token
                <br><button onclick="callApi()" id="api-btn" disabled>Get Products from API</button>
                <div id="api-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Full Flow:</span> Run complete demonstration
                <br><button onclick="runFullDemo()">Run Full Demo</button>
                <div id="full-demo-result"></div>
            </div>
        </div>
    </div>
    
    <script>
        let currentJwtSvid = null;
        let currentEntraToken = null;
        
        async function getJwtSvid() {
            const resultDiv = document.getElementById('jwt-svid-result');
            resultDiv.innerHTML = '<div class="status">Fetching JWT-SVID from SPIRE...</div>';
            
            try {
                const response = await fetch('/api/jwt-svid');
                const data = await response.json();
                
                if (data.status === 'success') {
                    currentJwtSvid = data.token;
                    document.getElementById('exchange-btn').disabled = false;
                    resultDiv.innerHTML = `
                        <div class="status success">✓ JWT-SVID obtained successfully!</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                } else {
                    resultDiv.innerHTML = `
                        <div class="status error">✗ Failed to get JWT-SVID</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                }
            } catch (e) {
                resultDiv.innerHTML = `<div class="status error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function exchangeToken() {
            const resultDiv = document.getElementById('exchange-result');
            resultDiv.innerHTML = '<div class="status">Exchanging JWT-SVID for Entra ID token...</div>';
            
            try {
                const response = await fetch('/api/exchange-token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({jwt_svid: currentJwtSvid})
                });
                const data = await response.json();
                
                if (data.status === 'success') {
                    currentEntraToken = data.access_token;
                    document.getElementById('api-btn').disabled = false;
                    resultDiv.innerHTML = `
                        <div class="status success">✓ Entra ID token obtained!</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                } else {
                    resultDiv.innerHTML = `
                        <div class="status error">✗ Token exchange failed</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                }
            } catch (e) {
                resultDiv.innerHTML = `<div class="status error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function callApi() {
            const resultDiv = document.getElementById('api-result');
            resultDiv.innerHTML = '<div class="status">Calling API Server with Entra ID token...</div>';
            
            try {
                const response = await fetch('/api/call-api', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        entra_token: currentEntraToken,
                        endpoint: '/api/products'
                    })
                });
                const data = await response.json();
                
                if (data.status === 'success') {
                    resultDiv.innerHTML = `
                        <div class="status success">✓ API call successful!</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                } else {
                    resultDiv.innerHTML = `
                        <div class="status error">✗ API call failed</div>
                        <pre>${JSON.stringify(data, null, 2)}</pre>
                    `;
                }
            } catch (e) {
                resultDiv.innerHTML = `<div class="status error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function runFullDemo() {
            const resultDiv = document.getElementById('full-demo-result');
            resultDiv.innerHTML = '<div class="status">Running full demo...</div>';
            
            try {
                const response = await fetch('/api/full-demo');
                const data = await response.json();
                
                resultDiv.innerHTML = `
                    <div class="status ${data.overall_status === 'success' ? 'success' : 'error'}">
                        ${data.overall_status === 'success' ? '✓' : '✗'} Full Demo ${data.overall_status}
                    </div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (e) {
                resultDiv.innerHTML = `<div class="status error">✗ Error: ${e.message}</div>`;
            }
        }
    </script>
</body>
</html>
'''


def get_jwt_svid(audience=None):
    """Fetch a JWT-SVID from SPIRE."""
    try:
        client = WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
        if audience is None:
            audience = AZURE_CLIENT_ID or "api://default"
        
        jwt_svid = client.fetch_jwt_svid(audience={audience})
        return {
            'status': 'success',
            'spiffe_id': str(jwt_svid.spiffe_id),
            'audience': audience,
            'token': jwt_svid.token,
            'token_preview': jwt_svid.token[:50] + '...' if len(jwt_svid.token) > 50 else jwt_svid.token
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Error fetching JWT-SVID: {str(e)}'
        }


def exchange_jwt_svid_for_entra_token(jwt_svid):
    """
    Exchange a JWT-SVID for an Entra ID access token using Workload Identity Federation.
    
    This uses the client_credentials grant with client_assertion.
    The JWT-SVID serves as the client_assertion proving the workload's identity.
    """
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        return {
            'status': 'error',
            'error': 'Entra ID not configured (missing AZURE_TENANT_ID or AZURE_CLIENT_ID)'
        }
    
    try:
        # Token exchange request using federated credentials
        data = {
            'grant_type': 'client_credentials',
            'client_id': AZURE_CLIENT_ID,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': jwt_svid,
            'scope': f'{AZURE_CLIENT_ID}/.default'
        }
        
        response = requests.post(
            AZURE_TOKEN_ENDPOINT,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        if response.status_code == 200:
            token_data = response.json()
            return {
                'status': 'success',
                'access_token': token_data.get('access_token'),
                'token_type': token_data.get('token_type'),
                'expires_in': token_data.get('expires_in'),
                'token_preview': token_data.get('access_token', '')[:50] + '...'
            }
        else:
            return {
                'status': 'error',
                'error': f'Token exchange failed: {response.status_code}',
                'details': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            }
            
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Token exchange error: {str(e)}'
        }


def call_api_with_token(token, endpoint='/api/products'):
    """Call the API Server with an Entra ID token."""
    try:
        response = requests.get(
            f"{API_SERVER_URL}{endpoint}",
            headers={'Authorization': f'Bearer {token}'},
            timeout=10
        )
        
        return {
            'status': 'success' if response.status_code == 200 else 'error',
            'status_code': response.status_code,
            'data': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': f'API call error: {str(e)}'
        }


@app.route('/')
def index():
    """Main UI page."""
    return render_template_string(
        HTML_TEMPLATE,
        spiffe_endpoint=SPIFFE_ENDPOINT_SOCKET,
        azure_tenant_id=AZURE_TENANT_ID[:8] + '...' if AZURE_TENANT_ID else 'Not configured',
        azure_client_id=AZURE_CLIENT_ID[:8] + '...' if AZURE_CLIENT_ID else 'Not configured',
        api_server_url=API_SERVER_URL,
        entra_configured='Yes ✓' if (AZURE_TENANT_ID and AZURE_CLIENT_ID) else 'No ✗'
    )


@app.route('/api/jwt-svid')
def api_get_jwt_svid():
    """API endpoint to get JWT-SVID."""
    return jsonify(get_jwt_svid())


@app.route('/api/exchange-token', methods=['POST'])
def api_exchange_token():
    """API endpoint to exchange JWT-SVID for Entra ID token."""
    data = request.get_json() or {}
    jwt_svid = data.get('jwt_svid')
    
    if not jwt_svid:
        # Get a fresh JWT-SVID if not provided
        svid_result = get_jwt_svid()
        if svid_result['status'] != 'success':
            return jsonify(svid_result)
        jwt_svid = svid_result['token']
    
    return jsonify(exchange_jwt_svid_for_entra_token(jwt_svid))


@app.route('/api/call-api', methods=['POST'])
def api_call_api():
    """API endpoint to call the API Server."""
    data = request.get_json() or {}
    entra_token = data.get('entra_token')
    endpoint = data.get('endpoint', '/api/products')
    
    if not entra_token:
        return jsonify({
            'status': 'error',
            'error': 'No Entra ID token provided'
        })
    
    return jsonify(call_api_with_token(entra_token, endpoint))


@app.route('/api/full-demo')
def api_full_demo():
    """Run the complete demo flow."""
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'steps': []
    }
    
    # Step 1: Get JWT-SVID
    step1 = get_jwt_svid()
    results['steps'].append({
        'step': 1,
        'name': 'Get JWT-SVID from SPIRE',
        'result': step1
    })
    
    if step1['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 1: Get JWT-SVID'
        return jsonify(results)
    
    # Step 2: Exchange for Entra ID token
    step2 = exchange_jwt_svid_for_entra_token(step1['token'])
    results['steps'].append({
        'step': 2,
        'name': 'Exchange JWT-SVID for Entra ID token',
        'result': step2
    })
    
    if step2['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 2: Token Exchange'
        return jsonify(results)
    
    # Step 3: Call API Server
    step3 = call_api_with_token(step2['access_token'])
    results['steps'].append({
        'step': 3,
        'name': 'Call API Server with Entra ID token',
        'result': step3
    })
    
    if step3['status'] != 'success':
        results['overall_status'] = 'failed'
        results['failed_at'] = 'Step 3: API Call'
        return jsonify(results)
    
    results['overall_status'] = 'success'
    return jsonify(results)


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'entra_configured': bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)
    })


if __name__ == '__main__':
    logger.info("Starting SPIFFE Client App")
    logger.info(f"SPIFFE Endpoint: {SPIFFE_ENDPOINT_SOCKET}")
    logger.info(f"Entra ID configured: {bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)}")
    logger.info(f"API Server URL: {API_SERVER_URL}")
    
    app.run(host='0.0.0.0', port=8080, debug=False)
