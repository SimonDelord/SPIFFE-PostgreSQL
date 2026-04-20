"""
SPIFFE-enabled Client App with PostgreSQL JWT Validation

Flow:
1. Get JWT-SVID from SPIRE
2. Exchange JWT-SVID for Entra ID access token
3. Connect to PostgreSQL
4. Pass Entra ID token to PostgreSQL for validation
5. PostgreSQL validates token and applies Row-Level Security

This demonstrates: Client → SPIRE → Entra ID → PostgreSQL (validates token & authZ)
"""

import os
import json
import logging
from datetime import datetime

from flask import Flask, render_template_string, jsonify
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from spiffe import WorkloadApiClient

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SPIFFE configuration
SPIFFE_ENDPOINT_SOCKET = os.environ.get(
    'SPIFFE_ENDPOINT_SOCKET',
    'unix:///spiffe-workload-api/spire-agent.sock'
)

# Azure Entra ID configuration
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID', '64dc69e4-d083-49fc-9569-ebece1dd1408')
AZURE_CLIENT_ID = os.environ.get('AZURE_CLIENT_ID', 'f63d6f2e-f780-4568-a69a-93a07cd8c5db')
AZURE_TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"

# PostgreSQL configuration - connects to the pgjwt-enabled PostgreSQL
DB_HOST = os.environ.get('DB_HOST', 'postgres-jwt.oidc-postgres-demo.svc.cluster.local')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'demo')
DB_USER = os.environ.get('DB_USER', 'jwt_client')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'jwt-client-password')

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>SPIFFE → Entra ID → PostgreSQL JWT Validation Demo</title>
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
        .success { background: #d4edda; border-color: #28a745; color: #155724; padding: 10px; border-radius: 4px; }
        .error { background: #f8d7da; border-color: #dc3545; color: #721c24; padding: 10px; border-radius: 4px; }
        pre { background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px; }
        .diagram { background: #f8f9fa; padding: 20px; border-radius: 4px; font-family: monospace; white-space: pre; overflow-x: auto; font-size: 11px; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
        th { background: #f0f0f0; }
        .highlight { background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 SPIFFE → Entra ID → PostgreSQL JWT Validation</h1>
        
        <div class="card">
            <h2>Architecture</h2>
            <div class="diagram">
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│          POSTGRESQL VALIDATES ENTRA ID TOKEN & PROVIDES AUTHORIZATION                   │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────┐     ┌─────────────────────────────┐     ┌──────────────┐             │
│  │   SPIFFE     │     │        SPIRE Server         │     │   Entra ID   │             │
│  │   Client     │     │  ┌───────────────────────┐  │     │  (Azure AD)  │             │
│  │  (this app)  │     │  │  SPIRE OIDC Discovery │  │     │              │             │
│  │              │     │  │  Provider             │  │     │              │             │
│  └──────┬───────┘     │  └───────────┬───────────┘  │     └──────┬───────┘             │
│         │             └──────────────┼──────────────┘            │                     │
│         │                            │                           │  ┌───────────────┐  │
│         │                            │                           │  │ PostgreSQL    │  │
│         │                            │                           │  │ + pgjwt       │  │
│         │                            │                           │  │ + RLS         │  │
│         │                            │                           │  └───────┬───────┘  │
│         │                            │                           │          │          │
│    1.   │ Get JWT-SVID ─────────────►│                           │          │          │
│         │◄───────────────────────────│                           │          │          │
│         │                            │                           │          │          │
│    2.   │ Exchange JWT-SVID ─────────────────────────────────────►          │          │
│         │                            │                           │          │          │
│    3.   │                            │◄──────────────────────────│ Validate │          │
│         │                            │  Fetch JWKS               │ JWT-SVID │          │
│         │◄───────────────────────────────────────────────────────│ token    │          │
│         │                Entra ID Access Token                   │          │          │
│         │                                                        │          │          │
│    4.   │ Connect to PostgreSQL ─────────────────────────────────────────────►         │
│         │ SELECT set_session_token('entra-id-token')             │          │          │
│         │                                                        │          │          │
│    5.   │                                                        │◄─────────│ Validate │
│         │                                                        │ pgjwt    │ Entra ID │
│         │                                                        │ decodes  │ token    │
│         │                                                        │ & checks │          │
│         │                                                        │ claims   │          │
│         │                                                        │          │          │
│    6.   │ SELECT * FROM products (RLS applied!) ─────────────────────────────►         │
│         │◄────────────────────────────────────────────────────────────────────         │
│         │                       Filtered results based on token  │          │          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
            </div>
            
            <div class="highlight">
                <strong>Key Point:</strong> PostgreSQL validates the Entra ID token directly using pgjwt, 
                then applies Row-Level Security policies based on token claims for authorization.
            </div>
        </div>
        
        <div class="card">
            <h2>Configuration</h2>
            <table>
                <tr><th>Setting</th><th>Value</th></tr>
                <tr><td>SPIFFE Endpoint</td><td>{{ spiffe_endpoint }}</td></tr>
                <tr><td>Azure Tenant ID</td><td>{{ azure_tenant_id }}</td></tr>
                <tr><td>Azure Client ID</td><td>{{ azure_client_id }}</td></tr>
                <tr><td>PostgreSQL Host</td><td>{{ db_host }}</td></tr>
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
                <span class="step-num">Step 2-3:</span> Exchange JWT-SVID for Entra ID Token
                <br><button onclick="exchangeToken()">Exchange for Entra ID Token</button>
                <div id="exchange-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Step 4-6:</span> PostgreSQL Validates Token & Query with RLS
                <br><button onclick="queryWithToken()">Query PostgreSQL (Token Validated by DB)</button>
                <div id="db-result"></div>
            </div>
            
            <div class="step">
                <span class="step-num">Full Flow:</span> Run complete demonstration
                <br><button onclick="runFullDemo()">Run Full Demo</button>
                <div id="full-demo-result"></div>
            </div>
        </div>
    </div>
    
    <script>
        async function getJwtSvid() {
            const resultDiv = document.getElementById('jwt-svid-result');
            resultDiv.innerHTML = '<div class="status">Fetching JWT-SVID from SPIRE...</div>';
            try {
                const response = await fetch('/api/jwt-svid');
                const data = await response.json();
                resultDiv.innerHTML = `<div class="${data.status === 'success' ? 'success' : 'error'}">
                    ${data.status === 'success' ? '✓' : '✗'} ${data.status}</div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>`;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function exchangeToken() {
            const resultDiv = document.getElementById('exchange-result');
            resultDiv.innerHTML = '<div class="status">Exchanging JWT-SVID for Entra ID token...</div>';
            try {
                const response = await fetch('/api/exchange-token');
                const data = await response.json();
                resultDiv.innerHTML = `<div class="${data.status === 'success' ? 'success' : 'error'}">
                    ${data.status === 'success' ? '✓' : '✗'} ${data.status}</div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>`;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function queryWithToken() {
            const resultDiv = document.getElementById('db-result');
            resultDiv.innerHTML = '<div class="status">Connecting to PostgreSQL and validating token...</div>';
            try {
                const response = await fetch('/api/query-with-token');
                const data = await response.json();
                resultDiv.innerHTML = `<div class="${data.status === 'success' ? 'success' : 'error'}">
                    ${data.status === 'success' ? '✓' : '✗'} ${data.status}</div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>`;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
        
        async function runFullDemo() {
            const resultDiv = document.getElementById('full-demo-result');
            resultDiv.innerHTML = '<div class="status">Running full demo...</div>';
            try {
                const response = await fetch('/api/full-demo');
                const data = await response.json();
                resultDiv.innerHTML = `<div class="${data.overall_status === 'success' ? 'success' : 'error'}">
                    ${data.overall_status === 'success' ? '✓' : '✗'} Full Demo ${data.overall_status}</div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>`;
            } catch (e) {
                resultDiv.innerHTML = `<div class="error">✗ Error: ${e.message}</div>`;
            }
        }
    </script>
</body>
</html>
'''


def get_jwt_svid():
    """Fetch a JWT-SVID from SPIRE."""
    try:
        client = WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET)
        jwt_svid = client.fetch_jwt_svid(audience={AZURE_CLIENT_ID})
        return {
            'status': 'success',
            'spiffe_id': str(jwt_svid.spiffe_id),
            'audience': AZURE_CLIENT_ID,
            'token': jwt_svid.token,
            'token_preview': jwt_svid.token[:50] + '...'
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def exchange_jwt_svid_for_entra_token(jwt_svid_token):
    """Exchange JWT-SVID for Entra ID access token via Workload Identity Federation."""
    try:
        data = {
            'grant_type': 'client_credentials',
            'client_id': AZURE_CLIENT_ID,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': jwt_svid_token,
            'scope': f'{AZURE_CLIENT_ID}/.default'
        }
        
        response = requests.post(AZURE_TOKEN_ENDPOINT, data=data, timeout=30)
        
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
        return {'status': 'error', 'error': str(e)}


def query_with_validated_token(entra_token):
    """
    Connect to PostgreSQL, pass the Entra ID token for validation,
    then query data with RLS applied.
    """
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10
        )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Step 1: Call PostgreSQL function to validate the Entra ID token
        # PostgreSQL will decode and validate the JWT claims
        logger.info("Calling set_session_token() to have PostgreSQL validate the token...")
        cursor.execute("SELECT set_session_token(%s, %s) as validated", (entra_token, AZURE_CLIENT_ID))
        validation_result = cursor.fetchone()
        
        if not validation_result or not validation_result['validated']:
            return {
                'status': 'error',
                'error': 'PostgreSQL rejected the token',
                'step': 'Token Validation by PostgreSQL'
            }
        
        # Step 2: Get the validated token info from session
        cursor.execute("""
            SELECT 
                current_setting('app.token_sub', true) as token_sub,
                current_setting('app.token_appid', true) as token_appid,
                current_setting('app.token_name', true) as token_name,
                current_setting('app.token_iss', true) as token_iss,
                current_setting('app.token_validated', true) as validated
        """)
        session_info = cursor.fetchone()
        
        # Step 3: Query products - RLS will be applied based on token validation
        cursor.execute("SELECT * FROM products ORDER BY id")
        products = cursor.fetchall()
        
        # Step 4: Log the query
        cursor.execute("""
            INSERT INTO access_log (token_sub, token_appid, action, details)
            VALUES (%s, %s, %s, %s)
        """, (
            session_info['token_sub'],
            session_info['token_appid'],
            'QUERY_PRODUCTS',
            f'Retrieved {len(products)} products'
        ))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return {
            'status': 'success',
            'message': 'Token validated by PostgreSQL, RLS applied!',
            'token_validation': {
                'validated_by': 'PostgreSQL (pgjwt)',
                'token_sub': session_info['token_sub'],
                'token_appid': session_info['token_appid'],
                'token_name': session_info['token_name'],
                'token_issuer': session_info['token_iss']
            },
            'authorization': {
                'method': 'Row-Level Security (RLS)',
                'policy': 'is_token_validated() must be true'
            },
            'products': [dict(p) for p in products],
            'product_count': len(products)
        }
        
    except psycopg2.Error as e:
        return {
            'status': 'error',
            'error': f'PostgreSQL error: {str(e)}',
            'hint': 'Check if token is valid and not expired'
        }
    except Exception as e:
        logger.exception("Error in query_with_validated_token")
        return {'status': 'error', 'error': str(e)}


@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        spiffe_endpoint=SPIFFE_ENDPOINT_SOCKET,
        azure_tenant_id=AZURE_TENANT_ID[:8] + '...',
        azure_client_id=AZURE_CLIENT_ID[:8] + '...',
        db_host=f"{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


@app.route('/api/jwt-svid')
def api_get_jwt_svid():
    return jsonify(get_jwt_svid())


@app.route('/api/exchange-token')
def api_exchange_token():
    svid_result = get_jwt_svid()
    if svid_result['status'] != 'success':
        return jsonify(svid_result)
    return jsonify(exchange_jwt_svid_for_entra_token(svid_result['token']))


@app.route('/api/query-with-token')
def api_query_with_token():
    # Get JWT-SVID
    svid_result = get_jwt_svid()
    if svid_result['status'] != 'success':
        return jsonify({'status': 'error', 'step': 'Get JWT-SVID', 'error': svid_result.get('error')})
    
    # Exchange for Entra ID token
    exchange_result = exchange_jwt_svid_for_entra_token(svid_result['token'])
    if exchange_result['status'] != 'success':
        return jsonify({'status': 'error', 'step': 'Exchange Token', 'error': exchange_result.get('error')})
    
    # Query PostgreSQL with token validation
    return jsonify(query_with_validated_token(exchange_result['access_token']))


@app.route('/api/full-demo')
def api_full_demo():
    results = {'timestamp': datetime.utcnow().isoformat(), 'steps': []}
    
    # Step 1: Get JWT-SVID
    step1 = get_jwt_svid()
    results['steps'].append({
        'step': '1',
        'name': 'Get JWT-SVID from SPIRE',
        'result': {'status': step1['status'], 'spiffe_id': step1.get('spiffe_id'), 'error': step1.get('error')}
    })
    if step1['status'] != 'success':
        results['overall_status'] = 'failed'
        return jsonify(results)
    
    # Step 2-3: Exchange for Entra ID token
    step2 = exchange_jwt_svid_for_entra_token(step1['token'])
    results['steps'].append({
        'step': '2-3',
        'name': 'Exchange JWT-SVID for Entra ID token',
        'result': {'status': step2['status'], 'expires_in': step2.get('expires_in'), 'error': step2.get('error')}
    })
    if step2['status'] != 'success':
        results['overall_status'] = 'failed'
        return jsonify(results)
    
    # Step 4-6: PostgreSQL validates token and query with RLS
    step3 = query_with_validated_token(step2['access_token'])
    results['steps'].append({
        'step': '4-6',
        'name': 'PostgreSQL validates token & query with RLS',
        'result': step3
    })
    
    results['overall_status'] = 'success' if step3['status'] == 'success' else 'failed'
    results['summary'] = {
        'spiffe_id': step1.get('spiffe_id'),
        'token_validated_by': 'PostgreSQL (pgjwt)',
        'authorization_method': 'Row-Level Security',
        'products_retrieved': step3.get('product_count', 0)
    }
    
    return jsonify(results)


@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    logger.info("Starting SPIFFE → Entra ID → PostgreSQL JWT Validation Demo")
    logger.info(f"PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    app.run(host='0.0.0.0', port=8080, debug=False)
